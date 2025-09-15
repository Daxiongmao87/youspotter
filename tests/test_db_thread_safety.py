import threading
from pathlib import Path
from youspotter.storage import DB


def test_db_allows_cross_thread_access(tmp_path: Path):
    db = DB(tmp_path / 't.db')
    errors = []

    def writer(i):
        try:
            db.set_setting(f'k{i}', f'v{i}')
        except Exception as e:
            errors.append(e)

    ts = [threading.Thread(target=writer, args=(i,)) for i in range(10)]
    for t in ts: t.start()
    for t in ts: t.join()

    # Should have no thread errors and be able to read keys
    assert not errors
    assert db.get_setting('k5') == 'v5'

