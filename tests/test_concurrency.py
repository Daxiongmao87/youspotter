import threading
import time
from youspotter.sync_service import SyncService


def test_concurrency_cap_enforced():
    # Prepare 5 tracks
    tracks = [{"artist": "A", "title": f"T{i}", "duration": 100} for i in range(5)]
    def fetch():
        return tracks
    def search(t):
        return [{"artist": t["artist"], "title": t["title"], "duration": t["duration"], "channel": "Official", "url": "http://x"}]
    active = 0
    max_active = 0
    lock = threading.Lock()
    def download(c, t, cfg):
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.05)
        with lock:
            active -= 1
        return True, None
    svc = SyncService(fetch, search, download, concurrency_cap=2, enable_watchdog=False)
    svc.run_once()
    assert max_active <= 2
