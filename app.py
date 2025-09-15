import os
from pathlib import Path
from youspotter import create_app
from youspotter.storage import DB
from youspotter.spotify_client import SpotifyClient
from youspotter.youtube_client import YouTubeClient
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
    yt = YouTubeClient()

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
        for pid in ids:
            for t in sp.playlist_tracks(pid):
                t['playlist_id'] = pid
                tracks.append(t)
        return tracks

    def fetch_strategies():
        raw = db.get_setting('selected_playlists') or ''
        try:
            return json.loads(raw) if raw else {}
        except Exception:
            return {}

    service = SyncService(fetch_tracks, yt.search_song, download_audio, db=db, fetch_playlist_strategies=fetch_strategies, spotify_client=sp)
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
    app = create_app(service=service, db_path=db_path)
    # Start scheduler only when minimal config is present (daemon behavior once configured)
    if _config_ready(db):
        service.start_scheduler(interval_seconds=900)
    return app


if __name__ == '__main__':
    app = build_app()
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
