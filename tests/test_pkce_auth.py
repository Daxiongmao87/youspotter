from urllib.parse import urlparse, parse_qs

from youspotter.storage import DB
from youspotter.spotify_client import SpotifyClient


def test_pkce_authorize_url_contains_required_params(tmp_path):
    db = DB(tmp_path / 't.db')
    db.set_setting('spotify_client_id', 'CLIENT')
    sc = SpotifyClient(db)
    url = sc.get_auth_url('http://localhost:5000/auth/callback', client_id='CLIENT')
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    assert qs['client_id'][0] == 'CLIENT'
    assert qs['response_type'][0] == 'code'
    assert qs['redirect_uri'][0] == 'http://localhost:5000/auth/callback'
    assert qs['code_challenge_method'][0] == 'S256'
    assert 'code_challenge' in qs and qs['code_challenge'][0]
    assert 'state' in qs and qs['state'][0]

