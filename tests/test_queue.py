from youspotter.queue import DedupQueue, identity_key

def test_dedup_queue_rejects_duplicates_and_honors_cap():
    q = DedupQueue(cap=2)
    t1 = { 'artist': 'Queen', 'title': 'Bohemian Rhapsody', 'duration': 354 }
    t2 = { 'artist': 'queen', 'title': 'Bohemian  rhapsody', 'duration': 352 }
    t3 = { 'artist': 'Other', 'title': 'Song', 'duration': 200 }
    assert q.enqueue(t1) is True
    assert q.enqueue(t2) is False  # duplicate by identity
    assert q.enqueue(t3) is True
    t4 = { 'artist': 'New', 'title': 'Another', 'duration': 100 }
    assert q.enqueue(t4) is False  # cap reached
    assert len(q) == 2

