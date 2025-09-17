import re
import unicodedata
from typing import Dict

FEAT_PATTERNS = [r"\s*\(feat\..*?\)", r"\s*\[feat\..*?\]", r"\s*feat\..*$"]

def normalize_text(text: str) -> str:
    txt = unicodedata.normalize('NFKD', text or '').encode('ascii', 'ignore').decode('ascii')
    txt = txt.lower()
    for pat in FEAT_PATTERNS:
        txt = re.sub(pat, '', txt).strip()
    txt = re.sub(r"[^a-z0-9\s]", " ", txt)
    txt = re.sub(r"\s+", " ", txt).strip()
    return txt

def duration_within_tolerance(target_seconds: int, candidate_seconds: int, tolerance: int = 5) -> bool:
    return abs(int(target_seconds) - int(candidate_seconds)) <= tolerance

def is_official_source(candidate: Dict) -> bool:
    channel = (candidate.get('channel') or '').lower()
    url = (candidate.get('url') or '').lower()
    return 'official' in channel or 'music.youtube.com' in url

def levenshtein_distance(s1: str, s2: str) -> int:
    """Calculate Levenshtein distance between two strings"""
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)

    if len(s2) == 0:
        return len(s1)

    previous_row = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row

    return previous_row[-1]

def string_similarity(s1: str, s2: str) -> float:
    """Calculate string similarity (0.0 to 1.0) using normalized Levenshtein distance"""
    if not s1 and not s2:
        return 1.0
    if not s1 or not s2:
        return 0.0

    max_len = max(len(s1), len(s2))
    distance = levenshtein_distance(s1, s2)
    return 1.0 - (distance / max_len)

def song_match_fuzzy(candidate: Dict, target: Dict,
                     title_threshold: float = 0.8,
                     artist_threshold: float = 0.7,
                     duration_tolerance: int = 10,
                     use_strict: bool = False) -> bool:
    """
    Fuzzy matching with configurable thresholds
    candidate: { 'artist': str, 'title': str, 'duration': int, 'channel': str, 'url': str }
    target: { 'artist': str, 'title': str, 'duration': int }
    """
    if use_strict:
        return song_match_strict(candidate, target, duration_tolerance)

    ca = normalize_text(candidate.get('artist', ''))
    ct = normalize_text(candidate.get('title', ''))
    ta = normalize_text(target.get('artist', ''))
    tt = normalize_text(target.get('title', ''))

    # Check title similarity
    title_sim = string_similarity(ct, tt)
    if title_sim < title_threshold:
        return False

    # Check artist similarity
    artist_sim = string_similarity(ca, ta)
    if artist_sim < artist_threshold:
        return False

    # Check duration tolerance
    dur_ok = duration_within_tolerance(target.get('duration', 0), candidate.get('duration', 0), duration_tolerance)

    return dur_ok

def song_match_strict(candidate: Dict, target: Dict, duration_tolerance: int = 5) -> bool:
    """
    Strict matching (original algorithm) - requires exact artist and title matches
    candidate: { 'artist': str, 'title': str, 'duration': int, 'channel': str, 'url': str }
    target: { 'artist': str, 'title': str, 'duration': int }
    """
    ca = normalize_text(candidate.get('artist', ''))
    ct = normalize_text(candidate.get('title', ''))
    ta = normalize_text(target.get('artist', ''))
    tt = normalize_text(target.get('title', ''))
    if ca != ta or ct != tt:
        return False
    dur_ok = duration_within_tolerance(target.get('duration', 0), candidate.get('duration', 0), duration_tolerance)
    return dur_ok

def song_match(candidate: Dict, target: Dict) -> bool:
    """
    Default matching function - uses fuzzy matching with default settings
    candidate: { 'artist': str, 'title': str, 'duration': int, 'channel': str, 'url': str }
    target: { 'artist': str, 'title': str, 'duration': int }
    """
    return song_match_fuzzy(candidate, target)

