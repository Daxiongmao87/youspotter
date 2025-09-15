from typing import Optional, Dict, List, Set, Tuple
from threading import Lock
from youspotter.utils.matching import normalize_text


def identity_key(track: Dict) -> str:
    artist = normalize_text(track.get('artist', ''))
    title = normalize_text(track.get('title', ''))
    dur = int(track.get('duration', 0)) // 5  # 5-second bucket
    return f"{artist}|{title}|{dur}"


class DedupQueue:
    def __init__(self, cap: int = 10000):
        self._cap = cap
        self._q: List[Dict] = []
        self._seen: Set[str] = set()
        self._lock = Lock()

    def enqueue(self, track: Dict) -> bool:
        key = identity_key(track)
        with self._lock:
            if key in self._seen:
                return False
            if len(self._q) >= self._cap:
                return False
            self._q.append(track)
            self._seen.add(key)
            return True

    def dequeue(self) -> Optional[Dict]:
        with self._lock:
            if not self._q:
                return None
            item = self._q.pop(0)
            # keep key in _seen to avoid re-enqueue during same session
            return item

    def __len__(self) -> int:
        with self._lock:
            return len(self._q)

