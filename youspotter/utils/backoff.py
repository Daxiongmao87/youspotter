import random

def exp_backoff_with_jitter(attempt: int, base: float = 2.0, initial: float = 1.0, max_delay: float = 60.0) -> float:
    if attempt < 1:
        attempt = 1
    delay = min(max_delay, initial * (base ** (attempt - 1)))
    jitter = random.uniform(0, delay * 0.25)
    return min(max_delay, delay + jitter)

