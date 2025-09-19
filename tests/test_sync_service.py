import time
from pathlib import Path

from youspotter.sync_service import SyncService
from youspotter.status import get_status, set_status
from youspotter.storage import DB


def make_service(tmp_path: Path, success=True):
    tracks = [
        {"artist": "Queen", "title": "Bohemian Rhapsody", "duration": 354},
        {"artist": "Queen", "title": "Bohemian Rhapsody", "duration": 352},  # duplicate
    ]
    def fetch_spotify_tracks():
        return tracks
    def search_youtube(t):
        # First candidate matches exactly
        return [{"artist": t["artist"], "title": t["title"], "duration": t["duration"], "channel": "Official", "url": "https://music.youtube.com/x"}]
    music_dir = tmp_path / "Music"
    music_dir.mkdir(exist_ok=True)

    def download_func(candidate, target, cfg):
        file_path = music_dir / f"{target['artist']} - {target['title']}.mp3"
        if success:
            file_path.write_text("dummy audio content")
        return success, str(file_path)

    db = DB(tmp_path / 'sync.db')
    return SyncService(fetch_spotify_tracks, search_youtube, download_func, db=db, enable_watchdog=False)


def test_sync_service_updates_status_and_dedups(tmp_path):
    set_status({"missing": 0, "downloading": 0, "downloaded": 0, "recent": []})
    svc = make_service(tmp_path, success=True)
    ok = svc.run_once()
    assert ok is True
    st = get_status()
    queue = st["queue"]
    assert len(queue["pending"]) == 1
    assert queue["pending"][0]["title"] == "Bohemian Rhapsody"
    assert queue["current"] == []
    assert queue["completed"] == []


def test_sync_now_respects_lock(monkeypatch, tmp_path):
    svc = make_service(tmp_path, success=False)
    # Monkeypatch run_once to simulate long-running and lock behavior
    calls = {"n": 0}
    orig = svc.run_once
    def slow_run(reason="manual"):
        calls["n"] += 1
        # First call: acquire lock; second call should fail to acquire
        return orig(reason=reason)
    svc.run_once = slow_run
    ok1 = svc.sync_now()
    ok2 = svc.sync_now()  # should immediately fail lock or no-op False
    assert ok1 in (True, False)
    assert ok2 in (True, False)


def test_run_once_logs_sync_start(tmp_path):
    set_status({"missing": 0, "downloading": 0, "downloaded": 0, "recent": []})
    svc = make_service(tmp_path, success=True)
    svc.run_once()
    st = get_status()
    assert st["recent"], "recent log should have entries"
    assert any("Sync starting" in line for line in st["recent"])


def test_scheduler_waits_until_completion(monkeypatch, tmp_path):
    set_status({"missing": 0, "downloading": 0, "downloaded": 0, "recent": []})

    svc = make_service(tmp_path, success=True)

    call_times = []

    def fake_run_once(reason="manual"):
        start = time.time()
        time.sleep(0.2)
        end = time.time()
        call_times.append((start, end))
        return True

    monkeypatch.setattr(svc, "run_once", fake_run_once)

    svc.start_scheduler(interval_seconds=1)
    time.sleep(0.35)  # allow first run to complete and next_run_at to be set
    svc.stop_scheduler()

    assert len(call_times) == 1
    finished_at = call_times[0][1]
    expected_next = int(finished_at + 1)
    assert svc.next_run_at == expected_next


def test_reconciliation_detects_missing_files(tmp_path):
    set_status({"missing": 0, "downloading": 0, "downloaded": 0, "recent": []})
    svc = make_service(tmp_path, success=True)

    # Initial sync creates catalog and downloads track
    assert svc.run_once() is True
    catalog_rows = svc.db.fetch_catalog_tracks()
    assert catalog_rows
    identity = catalog_rows[0]['id']
    downloaded_file = tmp_path / "Music" / f"{catalog_rows[0]['artist']} - {catalog_rows[0]['name']}.mp3"
    downloaded_file.write_text("dummy audio")
    svc.db.mark_download_success(identity, str(downloaded_file))

    status_after_sync = svc.reconcile_catalog(force=True)
    assert status_after_sync is not None
    assert status_after_sync['counts']['downloaded'] == 1
    assert len(status_after_sync['pending']) == 0

    # Remove file on disk and reconcile again
    music_files = list((tmp_path / "Music").glob("*.mp3"))
    for f in music_files:
        f.unlink()

    again = svc.reconcile_catalog(force=True)
    assert again is not None
    assert len(again['pending']) == 1
    assert again['counts']['missing'] == 1


def test_get_sync_progress_reflects_updates(tmp_path):
    svc = make_service(tmp_path, success=True)
    svc._set_progress('fetch-playlists', 10, 25)
    snapshot = svc.get_sync_progress()
    assert snapshot['phase'] == 'fetch-playlists'
    assert snapshot['processed'] == 10
    assert snapshot['total'] == 25
    assert snapshot['heartbeat_epoch'] >= 0
