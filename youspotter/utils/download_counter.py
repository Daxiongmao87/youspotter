import os
import time
from typing import Optional

_CACHE = {
    'host': None,  # type: Optional[str]
    'ext': None,   # type: Optional[str]
    'count': 0,    # type: int
    'ts': 0.0,     # type: float
}


def invalidate():
    """Invalidate the cached counter so the next read refreshes."""
    _CACHE['ts'] = 0.0


def count_files(host_path: str, ext: str, ttl_seconds: int = 10) -> int:
    """Count files with given extension under host_path with lightweight caching.

    - Uses a simple time-based cache. If the host or ext changes, forces refresh.
    - Only counts exact extension matches (case-insensitive).
    """
    host = (host_path or '').strip()
    extension = (ext or '').strip().lstrip('.').lower()

    now = time.time()
    if (
        _CACHE['host'] == host and
        _CACHE['ext'] == extension and
        (_CACHE['ts'] and (now - float(_CACHE['ts']) < max(1, int(ttl_seconds))))
    ):
        return int(_CACHE['count'] or 0)

    count = 0
    if host and os.path.isabs(host) and os.path.isdir(host):
        ext_dot = f'.{extension}' if extension else ''
        for root, _dirs, files in os.walk(host):
            for fn in files:
                if not extension:
                    count += 1
                else:
                    if fn.lower().endswith(ext_dot):
                        count += 1

    _CACHE['host'] = host
    _CACHE['ext'] = extension
    _CACHE['count'] = int(count)
    _CACHE['ts'] = now
    return count
