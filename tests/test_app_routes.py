from pathlib import Path
from youspotter import create_app
from youspotter.sync_service import SyncService


class DummyService(SyncService):
    def __init__(self):
        super().__init__(lambda: [], lambda t: [], lambda c, t: False)
        self.calls = 0

    def sync_now(self):
        self.calls += 1
        return True


def test_status_route():
    app = create_app()
    client = app.test_client()
    r = client.get('/status')
    assert r.status_code == 200
    assert 'missing' in r.get_json()


def test_sync_now_route_calls_service(tmp_path: Path):
    svc = DummyService()
    app = create_app(service=svc, db_path=str(tmp_path / 'app.db'))
    client = app.test_client()
    r = client.post('/sync-now')
    assert r.status_code == 200
    assert r.get_json()['started'] is True
    assert svc.calls == 1


def test_config_roundtrip(tmp_path: Path):
    app = create_app(db_path=str(tmp_path / 'cfg.db'))
    client = app.test_client()
    # Default config
    r = client.get('/config')
    assert r.status_code == 200
    data = r.get_json()
    assert data['bitrate'] == 128
    # Save new config
    r = client.post('/config', json={
        'host_path': str(tmp_path / 'music'),
        'bitrate': 256,
        'format': 'flac',
        'concurrency': 4,
    })
    assert r.status_code == 200
    assert r.get_json()['saved'] is True
    # Read back
    r = client.get('/config')
    data = r.get_json()
    assert data['bitrate'] == 256
    assert data['format'] == 'flac'
    assert data['concurrency'] == 4


def test_config_validation(tmp_path: Path):
    app = create_app(db_path=str(tmp_path / 'cfg.db'))
    client = app.test_client()
    r = client.post('/config', json={'bitrate': 123})
    assert r.status_code == 400
    r = client.post('/config', json={'bitrate': 128, 'format': 'xyz'})
    assert r.status_code == 400
    r = client.post('/config', json={'bitrate': 128, 'format': 'mp3', 'concurrency': 99})
    assert r.status_code == 400
