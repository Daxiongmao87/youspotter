import os
from pathlib import Path
from youspotter import create_app
from youspotter.storage import DB
from youspotter.spotify_client import SpotifyClient
from youspotter.youtube_client import YouTubeMusicClient
from youspotter.downloader_yt import download_audio
from youspotter.sync_service import SyncService
import json


def _config_ready(db: DB) -> bool:
    host = db.get_setting('host_path') or ''
    playlists = db.get_setting('selected_playlists') or ''
    return bool(host.strip()) and bool(playlists.strip())


def build_app():
    db_path = os.environ.get('YOUSPOTTER_DB', str(Path.cwd() / 'youspotter.db'))
    db = DB(Path(db_path))
    sp = SpotifyClient(db)
    yt = YouTubeMusicClient()

    def fetch_tracks():
        # For MVP: read selected playlist IDs from settings, else empty list
        raw = db.get_setting('selected_playlists') or ''
        strategies = {}
        try:
            strategies = json.loads(raw) if raw else {}
        except Exception:
            for pid in (raw.split(',') if raw else []):
                strategies[pid] = {'song': True, 'artist': False, 'album': False}
        ids = list(strategies.keys())
        tracks = []
        try:
            for pid in ids:
                for t in sp.playlist_tracks(pid):
                    t['playlist_id'] = pid
                    tracks.append(t)
        except RuntimeError as e:
            error_str = str(e)
            if error_str == "refresh_token_revoked":
                # Token was revoked, user needs to re-authenticate
                return []
            elif error_str == "not_authenticated":
                # No tokens available, user needs to authenticate
                return []
            elif error_str.startswith("spotify_refresh_failed_http_"):
                # HTTP error during token refresh, treat as authentication failure
                return []
            else:
                raise
        return tracks

    def fetch_strategies():
        raw = db.get_setting('selected_playlists') or ''
        try:
            return json.loads(raw) if raw else {}
        except Exception:
            return {}

    # Create app first to get the refresh function
    app = create_app(service=None, db_path=db_path)

    # Now create service with the catalog refresh callback
    service = SyncService(
        fetch_tracks,
        yt.search_song,
        download_audio,
        concurrency_cap=1,
        db=db,
        fetch_playlist_strategies=fetch_strategies,
        spotify_client=sp,
        catalog_refresh_callback=app.refresh_catalog_cache,
    )
    # Register status persistence snapshot hooks
    from youspotter import status as st
    def load_snapshot():
        try:
            raw = db.get_setting('status_snapshot') or ''
            return json.loads(raw) if raw else None
        except Exception:
            return None
    def save_snapshot(data: dict):
        try:
            db.set_setting('status_snapshot', json.dumps(data))
        except Exception:
            pass
    st.register_persistence(load_snapshot, save_snapshot)

    # Clean up stale download state from previous sessions
    cleaned_items = st.cleanup_startup_state()
    if cleaned_items > 0:
        print(f"Cleaned up {cleaned_items} stale download items from previous session")

    # Now create the app with the service
    app_with_service = create_app(service=service, db_path=db_path)

    # Start download worker immediately (processes pending downloads)
    service.start_download_worker()

    # Start scheduler only when minimal config is present (daemon behavior once configured)
    if _config_ready(db):
        service.start_scheduler(interval_seconds=900)
    return app_with_service


if __name__ == '__main__':
    app = build_app()
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 9191)))
