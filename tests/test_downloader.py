from youspotter.downloader import attempt_with_retries

def test_attempt_with_retries_succeeds_after_failures(monkeypatch):
    calls = {"n": 0}
    def task():
        calls["n"] += 1
        return calls["n"] >= 3
    sleeps = []
    def sleep_fn(s):
        sleeps.append(s)
    ok = attempt_with_retries(task, max_attempts=5, sleep_fn=sleep_fn)
    assert ok is True
    assert calls["n"] == 3
    assert len(sleeps) == 2  # slept between first two failures

