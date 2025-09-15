from youspotter.utils.backoff import exp_backoff_with_jitter

def test_backoff_monotonic_and_capped():
    vals = [exp_backoff_with_jitter(i, base=2.0, initial=1.0, max_delay=10.0) for i in range(1, 6)]
    # Should be non-decreasing and not exceed cap
    for i in range(1, len(vals)):
        assert vals[i] >= vals[i-1]
        assert vals[i] <= 10.0

