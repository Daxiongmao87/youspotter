import json
from pathlib import Path

from youspotter.storage import DB
from youspotter.sync_service import SyncService
from youspotter import create_app


def test_catalog_persisted_and_served_from_db(tmp_path: Path):
    db_path = tmp_path / 'catalog.db'
    db = DB(db_path)
    music_dir = tmp_path / 'music'
    music_dir.mkdir()

    db.set_setting('host_path', str(music_dir))
    db.set_setting('format', 'mp3')
    db.set_setting('selected_playlists', json.dumps({'playlist-1': {'song': True}}))

    tracks = [
        {
            'id': 'track-1',
            'artist': 'Artist A',
            'title': 'Song 1',
            'album': 'Album X',
            'duration': 180,
            'playlist_id': 'playlist-1',
        },
        {
            'id': 'track-2',
            'artist': 'Artist B',
            'title': 'Song 2',
            'album': 'Album Y',
            'duration': 200,
            'playlist_id': 'playlist-1',
        },
    ]

    def fetch_tracks():
        return tracks

    service = SyncService(fetch_tracks, lambda _: [], lambda *_: (True, None), db=db, enable_watchdog=False)
    assert service.sync_spotify_tracks() is True

    # Data persisted to DB
    stored_tracks = db.fetch_catalog_tracks()
    assert len(stored_tracks) == 2

    app = create_app(db_path=str(db_path))
    app.refresh_catalog_cache()

    client = app.test_client()
    songs_response = client.get('/catalog/songs')
    assert songs_response.status_code == 200
    songs_payload = songs_response.get_json()
    assert len(songs_payload['items']) == 2

    artists_response = client.get('/catalog/artists')
    assert artists_response.status_code == 200
    assert len(artists_response.get_json()['items']) == 2

    albums_response = client.get('/catalog/albums')
    assert albums_response.status_code == 200
    assert len(albums_response.get_json()['items']) == 2
