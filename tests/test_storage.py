import logging
from pathlib import Path
from youspotter.storage import DB, TokenStore

def test_settings_roundtrip(tmp_path: Path):
    db = DB(tmp_path / 'test.db')
    db.set_setting('foo', 'bar')
    assert db.get_setting('foo') == 'bar'

def test_token_store_no_logging(tmp_path: Path, caplog):
    db = DB(tmp_path / 'test.db')
    ts = TokenStore(db)
    caplog.set_level(logging.DEBUG)
    ts.save('ACCESS_TOKEN', 'REFRESH_TOKEN')
    # Ensure nothing emitted the actual token values in logs
    logs = '\n'.join(r.message for r in caplog.records)
    assert 'ACCESS_TOKEN' not in logs
    assert 'REFRESH_TOKEN' not in logs
    at, rt = ts.load()
    assert at == 'ACCESS_TOKEN'
    assert rt == 'REFRESH_TOKEN'

