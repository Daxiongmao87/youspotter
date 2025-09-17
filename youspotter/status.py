from typing import Dict, List, Callable, Optional
from threading import Lock
from datetime import datetime, timezone

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

def add_recent(message: str, level: str = "INFO", limit: int = 50):
    with _lock:
        timestamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
        formatted_message = f"[{timestamp}] {level}: {message}"
        _state["recent"].insert(0, formatted_message)
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
        from youspotter.queue import identity_key
        it = dict(item)
        it.setdefault('progress', 0)
        _state["queue"]["current"].append(it)
        # remove from pending if present using identity key matching
        item_key = identity_key(item)
        _state["queue"]["pending"] = [p for p in _state["queue"]["pending"] if identity_key(p) != item_key]
        if _persist_save:
            _persist_save(dict(_state))

def queue_complete(item: Dict, ok: bool):
    with _lock:
        from youspotter.queue import identity_key
        # remove from current using identity key matching
        item_key = identity_key(item)
        _state["queue"]["current"] = [c for c in _state["queue"]["current"] if identity_key(c) != item_key]
        rec = dict(item)
        rec["status"] = "downloaded" if ok else "missing"
        rec["timestamp"] = datetime.now(timezone.utc).isoformat()
        _state["queue"]["completed"].insert(0, rec)
        if _persist_save:
            _persist_save(dict(_state))

def queue_update_progress(item: Dict, percent: int):
    with _lock:
        from youspotter.queue import identity_key
        item_key = identity_key(item)
        for c in _state["queue"].get("current", []):
            if identity_key(c) == item_key:
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

def reset_false_completions():
    """Reset false completed items back to pending queue - fixes threading bug aftermath"""
    with _lock:
        completed = _state["queue"]["completed"]
        # Move items marked as "missing" back to pending (these were failed downloads)
        failed_items = [item for item in completed if item.get("status") == "missing"]
        actual_downloads = [item for item in completed if item.get("status") == "downloaded"]

        # Add failed items back to pending queue
        existing_pending = _state["queue"]["pending"]
        for item in failed_items:
            # Remove status and timestamp to return to original format
            clean_item = {k: v for k, v in item.items() if k not in ["status", "timestamp"]}
            if clean_item not in existing_pending:
                existing_pending.append(clean_item)

        # Keep only actual downloads in completed queue
        _state["queue"]["completed"] = actual_downloads

        # Persist the changes
        if _persist_save:
            _persist_save(dict(_state))

        return len(failed_items), len(actual_downloads)

def cleanup_startup_state():
    """Clean up stale download state on app startup"""
    with _lock:
        # Move all "current" (downloading) items back to pending
        current_items = _state["queue"]["current"]
        if current_items:
            # Add current items back to pending queue
            existing_pending = _state["queue"]["pending"]
            for item in current_items:
                # Remove progress and any download-specific fields
                clean_item = {k: v for k, v in item.items() if k not in ["progress", "status", "timestamp"]}
                if clean_item not in existing_pending:
                    existing_pending.append(clean_item)

        # Clear current queue and reset downloading count
        _state["queue"]["current"] = []
        _state["downloading"] = 0

        # Keep other counts but ensure they're consistent
        completed = _state["queue"]["completed"]
        downloaded_count = len([item for item in completed if item.get("status") == "downloaded"])
        missing_count = len([item for item in completed if item.get("status") == "missing"])

        _state["downloaded"] = downloaded_count
        _state["missing"] = missing_count

        # Persist the cleaned state
        if _persist_save:
            _persist_save(dict(_state))

        return len(current_items)
