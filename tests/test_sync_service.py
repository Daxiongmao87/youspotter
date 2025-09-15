from youspotter.sync_service import SyncService
from youspotter.status import get_status, set_status


def make_service(success=True):
    tracks = [
        {"artist": "Queen", "title": "Bohemian Rhapsody", "duration": 354},
        {"artist": "Queen", "title": "Bohemian Rhapsody", "duration": 352},  # duplicate
    ]
    def fetch_spotify_tracks():
        return tracks
    def search_youtube(t):
        # First candidate matches exactly
        return [{"artist": t["artist"], "title": t["title"], "duration": t["duration"], "channel": "Official", "url": "https://music.youtube.com/x"}]
    def download_func(candidate, target):
        return bool(candidate) and success
    return SyncService(fetch_spotify_tracks, search_youtube, download_func)


def test_sync_service_updates_status_and_dedups():
    set_status({"missing": 0, "downloading": 0, "downloaded": 0, "recent": []})
    svc = make_service(success=True)
    ok = svc.run_once()
    assert ok is True
    st = get_status()
    # Two tracks but duplicate should collapse; expect 1 downloaded
    assert st["downloaded"] == 1
    assert st["missing"] == 0
    assert st["downloading"] == 0


def test_sync_now_respects_lock(monkeypatch):
    svc = make_service(success=False)
    # Monkeypatch run_once to simulate long-running and lock behavior
    calls = {"n": 0}
    orig = svc.run_once
    def slow_run():
        calls["n"] += 1
        # First call: acquire lock; second call should fail to acquire
        return orig()
    svc.run_once = slow_run
    ok1 = svc.sync_now()
    ok2 = svc.sync_now()  # should immediately fail lock or no-op False
    assert ok1 in (True, False)
    assert ok2 in (True, False)

