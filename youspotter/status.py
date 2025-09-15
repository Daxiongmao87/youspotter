from typing import Dict, List, Callable, Optional
from threading import Lock
from datetime import datetime

_lock = Lock()
_state = {
    "missing": 0,
    "downloading": 0,
    "downloaded": 0,
    "songs": 0,
    "artists": 0,
    "albums": 0,
    "recent": [],  # List[str]
    "queue": {
        "current": [],  # List[Dict]
        "pending": [],  # List[Dict]
        "completed": [],  # List[Dict]
    },
}

_persist_save: Optional[Callable[[Dict], None]] = None
_persist_load: Optional[Callable[[], Optional[Dict]]] = None

def get_status() -> Dict:
    with _lock:
        return dict(_state)

def set_status(counts: Dict):
    with _lock:
        _state.update(counts)
        if _persist_save:
            _persist_save(dict(_state))

def set_totals(songs: int, artists: int, albums: int):
    with _lock:
        _state["songs"] = int(songs)
        _state["artists"] = int(artists)
        _state["albums"] = int(albums)
        if _persist_save:
            _persist_save(dict(_state))

def add_recent(message: str, limit: int = 50):
    with _lock:
        _state["recent"].insert(0, message)
        if len(_state["recent"]) > limit:
            _state["recent"] = _state["recent"][:limit]
        if _persist_save:
            _persist_save(dict(_state))

def set_queue(pending: List[Dict]):
    with _lock:
        _state["queue"]["pending"] = list(pending)
        if _persist_save:
            _persist_save(dict(_state))

def queue_move_to_current(item: Dict):
    with _lock:
        it = dict(item)
        it.setdefault('progress', 0)
        _state["queue"]["current"].append(it)
        # remove from pending if present
        _state["queue"]["pending"] = [p for p in _state["queue"]["pending"] if p != item]
        if _persist_save:
            _persist_save(dict(_state))

def queue_complete(item: Dict, ok: bool):
    with _lock:
        # remove from current
        _state["queue"]["current"] = [c for c in _state["queue"]["current"] if c != item]
        rec = dict(item)
        rec["status"] = "downloaded" if ok else "missing"
        rec["timestamp"] = datetime.utcnow().isoformat() + "Z"
        _state["queue"]["completed"].insert(0, rec)
        if _persist_save:
            _persist_save(dict(_state))

def queue_update_progress(item: Dict, percent: int):
    with _lock:
        for c in _state["queue"].get("current", []):
            if c.get('artist') == item.get('artist') and c.get('title') == item.get('title') and c.get('album') == item.get('album'):
                c['progress'] = int(percent)
                break
        if _persist_save:
            _persist_save(dict(_state))

def register_persistence(load_fn: Callable[[], Optional[Dict]], save_fn: Callable[[Dict], None]):
    global _persist_load, _persist_save
    _persist_load = load_fn
    _persist_save = save_fn
    # Attempt initial load
    if _persist_load:
        data = _persist_load() or None
        if isinstance(data, dict):
            with _lock:
                _state.update({k: data.get(k, _state.get(k)) for k in _state.keys()})

def load_state(data: Dict):
    with _lock:
        _state.update(data)
