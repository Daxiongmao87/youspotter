from youspotter import create_app

def test_status_endpoint_returns_structure():
    app = create_app()
    client = app.test_client()
    resp = client.get('/status')
    assert resp.status_code == 200
    data = resp.get_json()
    for key in ['missing', 'downloading', 'downloaded', 'recent']:
        assert key in data

