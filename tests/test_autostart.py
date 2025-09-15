from pathlib import Path
from youspotter import create_app
from youspotter.storage import DB


class DummyService:
    def __init__(self):
        self.started = 0
        self.concurrency_cap = 1
    def start_scheduler(self, interval_seconds=900):
        self.started += 1
    def sync_now(self):
        return True


def test_scheduler_autostarts_when_ready(tmp_path: Path):
    db_path = tmp_path / 'auto.db'
    svc = DummyService()
    app = create_app(service=svc, db_path=str(db_path))
    client = app.test_client()
    # Save config with host_path only → not ready (no playlists)
    r = client.post('/config', json={'host_path': str(tmp_path), 'bitrate': 128, 'format': 'mp3', 'concurrency': 2})
    assert r.status_code == 200
    assert svc.started == 0
    # Set playlists via direct DB (avoids spotipy dependency)
    db = DB(db_path)
    db.set_setting('selected_playlists', 'pl1')
    # Touch config again to trigger check
    r = client.post('/config', json={'host_path': str(tmp_path), 'bitrate': 128, 'format': 'mp3', 'concurrency': 2})
    assert r.status_code == 200
    assert svc.started >= 1

