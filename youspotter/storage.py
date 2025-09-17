import logging
import sqlite3
import threading
from pathlib import Path
from typing import Optional

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
