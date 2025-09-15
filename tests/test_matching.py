from youspotter.utils.matching import normalize_text, duration_within_tolerance, song_match

def test_normalization_feat_and_case():
    assert normalize_text('Bohemian Rhapsody (feat. X)') == 'bohemian rhapsody'
    assert normalize_text('Queen') == 'queen'

def test_duration_tolerance():
    assert duration_within_tolerance(354, 350, tolerance=5)
    assert not duration_within_tolerance(354, 340, tolerance=5)

def test_song_match_exact_artist_title_and_duration():
    candidate = { 'artist': 'Queen', 'title': 'Bohemian Rhapsody', 'duration': 354, 'channel': 'Queen Official', 'url': 'https://music.youtube.com/xyz' }
    target = { 'artist': 'Queen', 'title': 'Bohemian Rhapsody', 'duration': 352 }
    assert song_match(candidate, target)

def test_song_match_rejects_title_mismatch():
    candidate = { 'artist': 'Queen', 'title': 'Bohemian Rhapsody - Live', 'duration': 354 }
    target = { 'artist': 'Queen', 'title': 'Bohemian Rhapsody', 'duration': 352 }
    assert not song_match(candidate, target)

