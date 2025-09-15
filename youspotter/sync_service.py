import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Callable, Optional
from youspotter.sync_lock import sync_lock
from youspotter.status import set_status, get_status, set_totals, set_queue, queue_move_to_current, queue_complete, add_recent
from youspotter.queue import DedupQueue, identity_key
from youspotter.utils.matching import song_match
from youspotter.downloader import attempt_with_retries
from youspotter.storage import DB
from youspotter.config import load_config


class SyncService:
    def __init__(
        self,
        fetch_spotify_tracks: Callable[[], List[Dict]],
        search_youtube: Callable[[Dict], List[Dict]],
        download_func: Callable[[Dict, Dict, Dict], bool],
        concurrency_cap: int = 3,
        db: DB | None = None,
        fetch_playlist_strategies: Optional[Callable[[], Dict[str,str]]] = None,
        spotify_client: Optional[object] = None,
    ):
        self.fetch_spotify_tracks = fetch_spotify_tracks
        self.search_youtube = search_youtube
        self.download_func = download_func
        self.concurrency_cap = concurrency_cap
        self.db = db
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.fetch_playlist_strategies = fetch_playlist_strategies or (lambda: {})
        self.spotify_client = spotify_client

    def run_once(self) -> bool:
        with sync_lock() as acquired:
            if not acquired:
                return False
            tracks = self.fetch_spotify_tracks() or []
            # Expand per playlist strategies if provided
            try:
                strategies = self.fetch_playlist_strategies() or {}
                if strategies and self.spotify_client:
                    # derive artists/albums from base tracks by playlist
                    artist_ids = set()
                    album_ids = set()
                    for t in tracks:
                        pid = t.get('playlist_id')
                        st = strategies.get(str(pid), {})
                        # Support old string strategies for backward-compat
                        if isinstance(st, str):
                            song = (st == 'song-only') or (st == 'all')
                            artist_flag = (st in ('all-artist-songs','all'))
                            album_flag = (st in ('all-album-songs','all'))
                        else:
                            song = bool(st.get('song'))
                            artist_flag = bool(st.get('artist'))
                            album_flag = bool(st.get('album'))
                        if artist_flag and t.get('artist_id'):
                            artist_ids.add(t.get('artist_id'))
                        if album_flag and t.get('album_id'):
                            album_ids.add(t.get('album_id'))
                    expanded: List[Dict] = list(tracks)
                    for aid in list(artist_ids)[:100]:  # cap to avoid explosion
                        expanded.extend(self.spotify_client.artist_all_tracks(aid))
                    for alid in list(album_ids)[:200]:
                        expanded.extend(self.spotify_client.album_tracks(alid))
                    tracks = expanded
            except Exception:
                pass
            # Compute totals for tracking
            try:
                songs = len(tracks)
                artists = len({t.get('artist','') for t in tracks})
                albums = len({t.get('album','') for t in tracks if t.get('album')})
                set_totals(songs, artists, albums)
            except Exception:
                pass
            q = DedupQueue()
            # Load retry schedule
            retry_schedule = {}
            try:
                if self.db:
                    import json
                    rr = self.db.get_setting('retry_schedule') or ''
                    retry_schedule = json.loads(rr) if rr else {}
            except Exception:
                retry_schedule = {}
            now = int(time.time())
            for t in tracks:
                # Skip items scheduled for future retry
                try:
                    ik = identity_key(t)
                    if ik in retry_schedule:
                        nxt = int(retry_schedule.get(ik, {}).get('next', 0))
                        if now < nxt:
                            continue
                except Exception:
                    pass
                q.enqueue(t)
            # Initialize pending queue view
            set_queue([{k: t.get(k) for k in ('artist','title','album','duration')} for t in list(q._q)])

            counts = {"missing": 0, "downloading": 0, "downloaded": 0}
            cfg = load_config(self.db) if self.db else {"host_path": ".", "bitrate": 192, "format": "mp3"}
            # Concurrent processing with simple pool (MVP)
            cap = max(1, min(self.concurrency_cap or 1, 10))
            lock = threading.Lock()

            def process(t: Dict) -> bool:
                candidates = self.search_youtube(t) or []
                picked = None
                for c in candidates:
                    if song_match(c, t):
                        picked = c
                        break
                def one():
                    if not picked:
                        return False
                    try:
                        # Inject progress callback for queue updates
                        def pcb(percent: int):
                            try:
                                from youspotter.status import queue_update_progress
                                queue_update_progress({k: t.get(k) for k in ('artist','title','album','duration')}, percent)
                            except Exception:
                                pass
                        cfg_with_progress = dict(cfg)
                        cfg_with_progress['progress_cb'] = pcb
                        return self.download_func(picked, t, cfg_with_progress)
                    except TypeError:
                        return self.download_func(picked, t)
                ok = attempt_with_retries(one, max_attempts=3, sleep_fn=lambda s: None)
                return ok

            with ThreadPoolExecutor(max_workers=cap) as ex:
                futures = []  # list of (future, track)
                while len(q) > 0:
                    t = q.dequeue()
                    if not t:
                        break
                    with lock:
                        queue_move_to_current({k: t.get(k) for k in ('artist','title','album','duration')})
                        counts["downloading"] += 1
                        set_status({**counts})
                    futures.append((ex.submit(process, t), t))
                for fut, t in futures:
                    ok = fut.result()
                    with lock:
                        counts["downloading"] -= 1
                        if ok:
                            counts["downloaded"] += 1
                            add_recent("Downloaded: {} - {}".format('unknown' if not t.get('artist') else t.get('artist'), t.get('title','')))
                            # Clear retry schedule on success
                            try:
                                ik = identity_key(t)
                                if ik in retry_schedule:
                                    retry_schedule.pop(ik, None)
                            except Exception:
                                pass
                        else:
                            counts["missing"] += 1
                            add_recent("Missing: {} - {}".format('unknown' if not t.get('artist') else t.get('artist'), t.get('title','')))
                            queue_complete({k: t.get(k) for k in ('artist','title','album','duration')}, ok)
                            # Update retry schedule using exponential backoff starting at 60s, cap 24h
                            try:
                                ik = identity_key(t)
                                ent = retry_schedule.get(ik, {"delay": 60})
                                delay = int(ent.get('delay', 60))
                                nxt = int(time.time()) + delay
                                next_delay = min(delay * 2, 24*60*60)
                                retry_schedule[ik] = {"next": nxt, "delay": next_delay}
                            except Exception:
                                pass
                        set_status({**counts})
            # Persist retry schedule
            try:
                if self.db:
                    import json
                    self.db.set_setting('retry_schedule', json.dumps(retry_schedule))
            except Exception:
                pass
            return True

    def start_scheduler(self, interval_seconds: int = 900):
        if self._thread and self._thread.is_alive():
            return
        def loop():
            while not self._stop.is_set():
                self.run_once()
                self._stop.wait(interval_seconds)
        self._stop.clear()
        self._thread = threading.Thread(target=loop, daemon=True)
        self._thread.start()

    def stop_scheduler(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1.0)

    def sync_now(self) -> bool:
        return self.run_once()
