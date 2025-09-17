import logging
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)


class DB:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Use thread-local connections to prevent deadlocks
        self._local = threading.local()
        self._global_lock = threading.Lock()
        # Initialize the primary connection for migration
        with self._global_lock:
            conn = sqlite3.connect(str(self.path))
            conn.execute("PRAGMA journal_mode=WAL;")
            self._migrate(conn)
            conn.close()

    def _get_connection(self):
        """Get thread-local database connection"""
        if not hasattr(self._local, 'conn') or self._local.conn is None:
            self._local.conn = sqlite3.connect(str(self.path))
            self._local.conn.execute("PRAGMA journal_mode=WAL;")
        return self._local.conn

    def _ensure_column(self, conn: sqlite3.Connection, table: str, column: str, definition: str):
        cur = conn.execute(f"PRAGMA table_info({table})")
        existing = {row[1] for row in cur.fetchall()}
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def _migrate(self, conn):
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            );
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS kvstore (
                key TEXT PRIMARY KEY,
                value TEXT
            );
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS tracks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                artist TEXT NOT NULL,
                title TEXT NOT NULL,
                duration INTEGER NOT NULL,
                identity TEXT UNIQUE
            );
            """
        )
        # Ensure newly introduced columns exist on legacy databases
        self._ensure_column(conn, 'tracks', 'album', 'TEXT')
        self._ensure_column(conn, 'tracks', 'playlist_id', 'TEXT')
        self._ensure_column(conn, 'tracks', 'spotify_id', 'TEXT')
        self._ensure_column(conn, 'tracks', 'expanded_from', 'TEXT')
        self._ensure_column(conn, 'tracks', 'status', 'TEXT')
        self._ensure_column(conn, 'tracks', 'last_seen', 'INTEGER')
        self._ensure_column(conn, 'tracks', 'local_path', 'TEXT')
        self._ensure_column(conn, 'tracks', 'last_error', 'TEXT')
        self._ensure_column(conn, 'tracks', 'retry_after', 'INTEGER')
        self._ensure_column(conn, 'tracks', 'download_attempts', 'INTEGER')
        conn.execute("UPDATE tracks SET download_attempts=0 WHERE download_attempts IS NULL")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tracks_identity ON tracks(identity)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tracks_status ON tracks(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tracks_retry ON tracks(retry_after)")
        conn.commit()

    def set_setting(self, key: str, value: str):
        conn = self._get_connection()
        conn.execute(
            "INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        conn.commit()

    def get_setting(self, key: str) -> Optional[str]:
        conn = self._get_connection()
        cur = conn.execute("SELECT value FROM settings WHERE key=?", (key,))
        row = cur.fetchone()
        return row[0] if row else None

    def set_kv(self, key: str, value: str):
        conn = self._get_connection()
        conn.execute(
            "INSERT INTO kvstore(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        conn.commit()

    def get_kv(self, key: str) -> Optional[str]:
        conn = self._get_connection()
        cur = conn.execute("SELECT value FROM kvstore WHERE key=?", (key,))
        row = cur.fetchone()
        return row[0] if row else None

    # Catalog persistence helpers
    def upsert_tracks(self, tracks: Iterable[Dict]) -> None:
        """Upsert catalog track metadata while preserving download state."""
        conn = self._get_connection()
        epoch_seconds = int(time.time())
        rows: List[Tuple] = []
        for track in tracks:
            identity = (track.get('identity') or '').strip()
            artist = (track.get('artist') or 'Unknown').strip()
            title = (track.get('title') or 'Unknown').strip()
            if not identity:
                continue
            album = (track.get('album') or '').strip()
            duration = int(track.get('duration') or 0)
            playlist_id = track.get('playlist_id')
            spotify_id = track.get('spotify_id')
            expanded_from = track.get('expanded_from') or 'playlist'
            rows.append((
                identity,
                artist,
                title,
                album,
                duration,
                playlist_id,
                spotify_id,
                expanded_from,
                epoch_seconds,
            ))

        if not rows:
            return

        conn.executemany(
            """
            INSERT INTO tracks (identity, artist, title, album, duration, playlist_id, spotify_id, expanded_from, last_seen)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(identity) DO UPDATE SET
                artist=excluded.artist,
                title=excluded.title,
                album=excluded.album,
                duration=excluded.duration,
                playlist_id=excluded.playlist_id,
                spotify_id=excluded.spotify_id,
                expanded_from=excluded.expanded_from,
                last_seen=excluded.last_seen
            """,
            rows,
        )
        version_token = str(time.time_ns())
        conn.execute(
            "INSERT INTO kvstore(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            ("catalog_version", version_token),
        )
        conn.commit()

    def mark_download_success(self, identity: str, local_path: str):
        conn = self._get_connection()
        now = int(time.time())
        conn.execute(
            """
            UPDATE tracks
            SET status='downloaded', local_path=?, last_error=NULL, retry_after=NULL,
                download_attempts=0, last_seen=?
            WHERE identity=?
            """,
            (local_path, now, identity),
        )
        conn.commit()

    def mark_download_failure(self, identity: str, error: str):
        conn = self._get_connection()
        current = conn.execute(
            "SELECT download_attempts FROM tracks WHERE identity=?",
            (identity,),
        ).fetchone()
        attempts_val = (current[0] if current else 0) or 0
        new_attempts = attempts_val + 1
        base_delay = 300  # 5 minutes
        delay = min(base_delay * (3 ** (new_attempts - 1)), 21600)  # cap at 6 hours
        retry_after = int(time.time()) + delay
        conn.execute(
            """
            UPDATE tracks
            SET status='missing', last_error=?, retry_after=?, download_attempts=?
            WHERE identity=?
            """,
            (error, retry_after, new_attempts, identity),
        )
        conn.commit()

    def reconcile_catalog_paths(self) -> Dict[str, int]:
        """Ensure catalog status matches filesystem presence."""
        conn = self._get_connection()
        rows = conn.execute(
            "SELECT identity, local_path, status FROM tracks"
        ).fetchall()
        now = int(time.time())
        updated_downloaded = 0
        updated_missing = 0

        for identity, local_path, status in rows:
            path_exists = bool(local_path and os.path.isfile(local_path))
            if path_exists and status != 'downloaded':
                conn.execute(
                    "UPDATE tracks SET status='downloaded', last_error=NULL, retry_after=NULL, last_seen=? WHERE identity=?",
                    (now, identity),
                )
                updated_downloaded += 1
            elif not path_exists and status != 'missing':
                conn.execute(
                    "UPDATE tracks SET status='missing' WHERE identity=?",
                    (identity,),
                )
                updated_missing += 1
        conn.commit()
        return {
            'downloaded': updated_downloaded,
            'missing': updated_missing,
        }

    def select_tracks_for_queue(self, limit: Optional[int] = None) -> List[Dict]:
        conn = self._get_connection()
        now = int(time.time())
        sql = (
            "SELECT identity, artist, title, album, duration "
            "FROM tracks "
            "WHERE status='missing' AND (retry_after IS NULL OR retry_after <= ?) "
            "ORDER BY last_seen ASC"
        )
        params = [now]
        if limit:
            sql += " LIMIT ?"
            params.append(limit)
        cur = conn.execute(sql, params)
        rows = cur.fetchall()
        return [
            {
                'identity': row[0],
                'artist': row[1],
                'title': row[2],
                'album': row[3],
                'duration': row[4],
            }
            for row in rows
        ]

    def fetch_catalog_tracks(self) -> List[Dict]:
        conn = self._get_connection()
        cur = conn.execute(
            """
            SELECT identity, artist, title, album, duration, status, spotify_id, playlist_id, local_path
            FROM tracks
            ORDER BY artist COLLATE NOCASE, title COLLATE NOCASE
            """
        )
        rows = cur.fetchall()
        result: List[Dict] = []
        for identity, artist, title, album, duration, status, spotify_id, playlist_id, local_path in rows:
            result.append({
                'id': identity,
                'name': title,
                'artist': artist,
                'album': album,
                'duration': duration,
                'status': status or 'pending',
                'spotify_id': spotify_id,
                'playlist_id': playlist_id,
                'local_path': local_path,
            })
        return result

    def fetch_catalog_artists(self) -> List[Dict]:
        conn = self._get_connection()
        cur = conn.execute(
            """
            SELECT artist, COUNT(*) as song_count
            FROM tracks
            GROUP BY artist
            ORDER BY artist COLLATE NOCASE
            """
        )
        rows = cur.fetchall()
        return [
            {'id': f"artist_{abs(hash(row[0])) % 100000}", 'name': row[0], 'song_count': row[1]}
            for row in rows if row[0]
        ]

    def fetch_catalog_albums(self) -> List[Dict]:
        conn = self._get_connection()
        cur = conn.execute(
            """
            SELECT album, artist, COUNT(*) as track_count
            FROM tracks
            WHERE album IS NOT NULL AND album != ''
            GROUP BY album, artist
            ORDER BY album COLLATE NOCASE
            """
        )
        rows = cur.fetchall()
        return [
            {'id': f"album_{abs(hash((row[0], row[1]))) % 100000}", 'name': row[0], 'artist': row[1], 'track_count': row[2]}
            for row in rows
        ]

    def get_catalog_version(self) -> Optional[str]:
        return self.get_kv('catalog_version')

    def get_catalog_counts(self) -> Dict[str, int]:
        conn = self._get_connection()
        songs = conn.execute("SELECT COUNT(*) FROM tracks").fetchone()[0] or 0
        artists = conn.execute("SELECT COUNT(DISTINCT artist) FROM tracks WHERE artist IS NOT NULL AND artist != ''").fetchone()[0] or 0
        albums = conn.execute("SELECT COUNT(DISTINCT album) FROM tracks WHERE album IS NOT NULL AND album != ''").fetchone()[0] or 0
        downloaded = conn.execute("SELECT COUNT(*) FROM tracks WHERE status='downloaded'").fetchone()[0] or 0
        missing = conn.execute("SELECT COUNT(*) FROM tracks WHERE status='missing'").fetchone()[0] or 0
        return {
            'songs': songs,
            'artists': artists,
            'albums': albums,
            'downloaded': downloaded,
            'missing': missing,
        }


class TokenStore:
    def __init__(self, db: DB):
        self.db = db

    def save(self, access_token: str, refresh_token: str):
        # Prefer OS keyring if available; fall back to DB settings
        try:
            import keyring  # type: ignore
            keyring.set_password('youspotter', 'spotify_access_token', access_token)
            keyring.set_password('youspotter', 'spotify_refresh_token', refresh_token)
        except Exception:
            # Do not log tokens
            self.db.set_setting("spotify_access_token", access_token)
            self.db.set_setting("spotify_refresh_token", refresh_token)

    def load(self):
        try:
            import keyring  # type: ignore
            at = keyring.get_password('youspotter', 'spotify_access_token')
            rt = keyring.get_password('youspotter', 'spotify_refresh_token')
            if at or rt:
                return at, rt
        except Exception:
            pass
        return (
            self.db.get_setting("spotify_access_token"),
            self.db.get_setting("spotify_refresh_token"),
        )

    def clear(self):
        # Clear tokens from both keyring and DB
        try:
            import keyring  # type: ignore
            keyring.delete_password('youspotter', 'spotify_access_token')
            keyring.delete_password('youspotter', 'spotify_refresh_token')
        except Exception:
            pass
        self.db.set_setting("spotify_access_token", "")
        self.db.set_setting("spotify_refresh_token", "")
