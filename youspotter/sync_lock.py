import threading
from contextlib import contextmanager

_lock = threading.Lock()
_busy = False

@contextmanager
def sync_lock():
    global _busy
    acquired = _lock.acquire(blocking=False)
    try:
        if not acquired or _busy:
            # Already running
            yield False
            return
        _busy = True
        yield True
    finally:
        if acquired and _busy:
            _busy = False
            _lock.release()

def is_sync_running() -> bool:
    """Check if a sync is currently running without acquiring the lock."""
    global _busy
    return _busy

