import threading
import time
from contextlib import contextmanager

_lock = threading.Lock()
_busy = False
_busy_since = None
_SYNC_TIMEOUT = 1800  # 30 minutes max sync time

@contextmanager
def sync_lock():
    global _busy, _busy_since
    acquired = _lock.acquire(blocking=False)
    try:
        if not acquired or _busy:
            # Already running
            yield False
            return
        _busy = True
        _busy_since = time.time()
        yield True
    finally:
        if acquired and _busy:
            _busy = False
            _busy_since = None
            _lock.release()

def is_sync_running() -> bool:
    """Check if a sync is currently running without acquiring the lock. Auto-recovers from timeouts."""
    global _busy, _busy_since

    if not _busy:
        return False

    # Check for timeout - auto-recover stuck locks
    if _busy_since and time.time() - _busy_since > _SYNC_TIMEOUT:
        print(f"WARNING: Sync lock timed out after {_SYNC_TIMEOUT}s, auto-recovering")
        _busy = False
        _busy_since = None
        try:
            _lock.release()
        except RuntimeError:
            # Lock wasn't held, that's fine
            pass
        return False

    return _busy

