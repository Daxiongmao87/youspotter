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

def song_match(candidate: Dict, target: Dict) -> bool:
    """
    candidate: { 'artist': str, 'title': str, 'duration': int, 'channel': str, 'url': str }
    target: { 'artist': str, 'title': str, 'duration': int }
    """
    ca = normalize_text(candidate.get('artist', ''))
    ct = normalize_text(candidate.get('title', ''))
    ta = normalize_text(target.get('artist', ''))
    tt = normalize_text(target.get('title', ''))
    if ca != ta or ct != tt:
        return False
    dur_ok = duration_within_tolerance(target.get('duration', 0), candidate.get('duration', 0))
    return dur_ok

