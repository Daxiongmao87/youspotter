import threading
import time
from youspotter.sync_lock import sync_lock

def worker(results, delay=0.05):
    with sync_lock() as acquired:
        results.append(acquired)
        if acquired:
            time.sleep(delay)

def test_sync_lock_prevents_overlap():
    results = []
    t1 = threading.Thread(target=worker, args=(results,))
    t2 = threading.Thread(target=worker, args=(results,))
    t1.start(); t2.start(); t1.join(); t2.join()
    assert results.count(True) == 1
    assert results.count(False) == 1

