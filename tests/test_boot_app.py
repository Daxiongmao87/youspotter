import os
from importlib import reload


def test_build_app_smoke(tmp_path, monkeypatch):
    monkeypatch.setenv('YOUSPOTTER_DB', str(tmp_path / 'youspotter.db'))
    import sys
    # Skip test if optional runtime deps are missing in this environment
    try:
        import ytmusicapi  # noqa: F401
    except Exception:
        import pytest
        pytest.skip('ytmusicapi not installed in test env')
    import app as appmod
    reload(appmod)
    app = appmod.build_app()
    client = app.test_client()
    r = client.get('/')
    assert r.status_code == 200
    r = client.get('/status')
    assert r.status_code == 200
