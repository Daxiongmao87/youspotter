from copy import deepcopy

from pathlib import Path

from youspotter.sync_service import SyncService
from youspotter.status import get_status, load_state, set_queue
from youspotter.storage import DB


def make_empty_service(tmp_path: Path | None = None):
    def fetch_tracks():
        return []

    def search(_track):
        return []

    def download(_candidate, _target, _cfg=None):
        return False, None

    db = DB(tmp_path / 'bootstrap.db') if tmp_path else None
    return SyncService(fetch_tracks, search, download, db=db, enable_watchdog=False)


def test_bootstrap_live_queue_restores_snapshot():
    original_state = deepcopy(get_status())
    try:
        load_state({
            "missing": 0,
            "downloading": 0,
            "downloaded": 0,
            "songs": 0,
            "artists": 0,
            "albums": 0,
            "recent": [],
            "queue": {"current": [], "pending": [], "completed": []},
        })

        svc = make_empty_service()
        assert svc.get_live_queue_status()["pending"] == []

        pending_items = [
            {"artist": "Artist A", "title": "Song 1", "album": "Album", "duration": 180},
            {"artist": "Artist B", "title": "Song 2", "album": "Album", "duration": 210},
        ]
        set_queue(pending_items)

        svc.bootstrap_live_queue_from_status()

        refreshed = svc.get_live_queue_status()
        assert len(refreshed["pending"]) == len(pending_items)
        assert refreshed["current"] == []
    finally:
        load_state(original_state)
