import time
from typing import Callable
from youspotter.utils.backoff import exp_backoff_with_jitter


def attempt_with_retries(task: Callable[[], bool], max_attempts: int = 3, sleep_fn: Callable[[float], None] = time.sleep) -> bool:
    """Run task up to max_attempts times. Returns True on success, False otherwise.
    Uses exponential backoff with jitter between attempts.
    """
    attempt = 1
    while attempt <= max_attempts:
        ok = False
        try:
            ok = bool(task())
        except Exception:
            ok = False
        if ok:
            return True
        if attempt == max_attempts:
            break
        delay = exp_backoff_with_jitter(attempt, base=2.0, initial=1.0, max_delay=60.0)
        sleep_fn(delay)
        attempt += 1
    return False

