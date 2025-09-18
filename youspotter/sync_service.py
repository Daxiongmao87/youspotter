import os
import threading
import time
from datetime import datetime, timezone
from typing import List, Dict, Callable, Optional
from youspotter.sync_lock import sync_lock
from youspotter.status import set_status, get_status, set_totals, set_queue, queue_move_to_current, queue_complete, add_recent
from youspotter.queue import DedupQueue, identity_key
from youspotter.utils.matching import song_match, song_match_fuzzy
from youspotter.downloader import attempt_with_retries
from youspotter.storage import DB
from youspotter.config import load_config


class SyncService:
    def __init__(
        self,
        fetch_spotify_tracks: Callable[[], List[Dict]],
        search_youtube: Callable[[Dict], List[Dict]],
        download_func: Callable[[Dict, Dict, Dict], tuple[bool, Optional[str]]],
        concurrency_cap: int = 3,
        db: DB | None = None,
        fetch_playlist_strategies: Optional[Callable[[], Dict[str,str]]] = None,
        spotify_client: Optional[object] = None,
        catalog_refresh_callback: Optional[Callable[[], None]] = None,
        enable_watchdog: bool = True,
    ):
        self.fetch_spotify_tracks = fetch_spotify_tracks
        self.search_youtube = search_youtube
        self.download_func = download_func
        self.concurrency_cap = concurrency_cap
        self.db = db
        self._enable_watchdog = enable_watchdog
        self._stop = threading.Event()
        self._paused = threading.Event()
        self._timer_reset = threading.Event()  # Signal for scheduler timer reset
        self._thread: Optional[threading.Thread] = None
        self._download_thread: Optional[threading.Thread] = None
        self._current_download_future = None  # Track current download for cancellation

        # Lightweight status tracking (deadlock-free) - now master
        self._status_lock = threading.Lock()
        self._live_status = {
            "current": [],  # Currently downloading items
            "pending": [],  # Pending queue items
            "completed": []  # Completed items with status
        }

        # Load persistent queue into live queue on startup
        self._load_persistent_into_live()
        self.fetch_playlist_strategies = fetch_playlist_strategies or (lambda: {})
        self.spotify_client = spotify_client
        self.catalog_refresh_callback = catalog_refresh_callback
        self.interval_seconds = int(concurrency_cap and 0)  # placeholder; set in scheduler
        self.next_run_at: Optional[int] = None

        self._watched_path: Optional[str] = None
        self._fs_observer = None
        self._fs_watch_stop = threading.Event()
        self._fs_poll_thread: Optional[threading.Thread] = None
        self._pending_reconcile = threading.Event()
        self._last_reconcile = 0.0
        self._reconcile_interval = 10.0

    def sync_spotify_tracks(self) -> bool:
        """Sync Spotify track data and update pending queue"""
        raw_tracks = self.fetch_spotify_tracks() or []
        tracks = list(raw_tracks)
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
                    try:
                        artist_tracks = self.spotify_client.get_artist_songs(aid) or []
                        for artist_track in artist_tracks:
                            artist_track['expanded_from'] = 'artist'
                            expanded.append(artist_track)
                    except Exception:
                        pass
                for aid in list(album_ids)[:100]:  # cap to avoid explosion
                    try:
                        album_tracks = self.spotify_client.get_album_songs(aid) or []
                        for album_track in album_tracks:
                            album_track['expanded_from'] = 'album'
                            expanded.append(album_track)
                    except Exception:
                        pass
                tracks = expanded
        except Exception:
            pass

        # Deduplicate tracks using identity key to avoid duplicate queue entries
        deduped_tracks: List[Dict] = []
        seen_identities = set()
        for track in tracks:
            try:
                ident = identity_key(track)
            except Exception:
                ident = None
            if not ident:
                continue
            if ident in seen_identities:
                continue
            seen_identities.add(ident)
            deduped_tracks.append(dict(track))

        tracks = deduped_tracks

        # Compute totals for tracking using deduplicated list
        songs = artists = albums = 0
        try:
            songs = len(tracks)
            artists = len({t.get('artist','') for t in tracks})
            albums = len({t.get('album','') for t in tracks if t.get('album')})
            from youspotter.status import set_totals
            set_totals(songs, artists, albums)
        except Exception:
            pass

        from youspotter.status import add_recent

        catalog_items: List[Dict] = []
        for track in tracks:
            artist = track.get('artist', '').strip() or 'Unknown'
            title = track.get('title', '').strip() or 'Unknown'
            album = track.get('album') or ''
            duration = int(track.get('duration') or 0)
            ident = identity_key(track)
            catalog_items.append({
                'identity': ident,
                'artist': artist,
                'title': title,
                'album': album,
                'duration': duration,
                'playlist_id': track.get('playlist_id'),
                'spotify_id': track.get('id') or track.get('spotify_id'),
                'expanded_from': track.get('expanded_from', 'playlist'),
            })

        if self.db:
            try:
                self.db.upsert_tracks(catalog_items)
            except Exception as db_err:
                print(f"Warning: failed to upsert catalog: {db_err}")

        reconciliation = self.reconcile_catalog(force=True)
        if reconciliation:
            pending_count = len(reconciliation.get('pending', []))
        else:
            live = self.get_live_queue_status()
            pending_count = len(live.get('pending', []))

        add_recent(
            f"Synced {len(tracks)} tracks from Spotify ({songs} songs, {artists} artists, {albums} albums) — pending: {pending_count}",
            "SUCCESS",
        )

        return True

    def reconcile_catalog(self, force: bool = False) -> Optional[Dict]:
        if not self.db:
            return None

        try:
            now = time.time()
            if not force and now - self._last_reconcile < self._reconcile_interval:
                return None

            self.db.reconcile_catalog_paths()
            counts = self.db.get_catalog_counts()

            from youspotter.status import set_totals, set_status, set_queue

            set_totals(counts['songs'], counts['artists'], counts['albums'])
            set_status({
                'missing': counts['missing'],
                'downloaded': counts['downloaded'],
            })

            pending_records = self.db.select_tracks_for_queue()
            pending_queue = [
                {
                    'artist': item['artist'],
                    'title': item['title'],
                    'album': item['album'],
                    'duration': item['duration'],
                    'identity': item['identity'],
                }
                for item in pending_records
            ]

            self.set_live_pending_queue(pending_queue)
            set_queue([{k: v for k, v in item.items() if k != 'identity'} for item in pending_queue])

            self._last_reconcile = now

            if self.catalog_refresh_callback:
                try:
                    threading.Thread(target=self.catalog_refresh_callback, daemon=True).start()
                except Exception as refresh_err:
                    print(f"Warning: failed to refresh catalog cache: {refresh_err}")

            self._ensure_watchdog()

            return {
                'pending': pending_queue,
                'counts': counts,
            }
        except Exception as exc:
            print(f"Warning: catalog reconciliation failed: {exc}")
            return None

    def _ensure_watchdog(self):
        if not self._enable_watchdog or not self.db:
            return
        try:
            cfg = load_config(self.db)
            host_path = (cfg.get('host_path') or '').strip()
        except Exception:
            host_path = ''

        normalized = host_path if host_path and os.path.isdir(host_path) else None
        if normalized == self._watched_path:
            return

        self._stop_filesystem_monitor()
        self._watched_path = normalized
        if normalized:
            self._start_filesystem_monitor(normalized)

    def _start_filesystem_monitor(self, path: str):
        if not self._enable_watchdog:
            return
        self._fs_watch_stop.clear()
        try:
            from watchdog.observers import Observer
            from watchdog.events import FileSystemEventHandler
        except ImportError:
            print("Watchdog not available; falling back to polling monitor")
            self._start_polling_monitor(path)
            return

        class CatalogHandler(FileSystemEventHandler):
            def __init__(self, outer):
                self._outer = outer

            def on_any_event(self, event):
                self._outer._schedule_reconcile()

        observer = Observer()
        handler = CatalogHandler(self)
        try:
            observer.schedule(handler, path, recursive=True)
            observer.start()
            self._fs_observer = observer
        except Exception as e:
            print(f"Warning: unable to start filesystem observer: {e}")
            self._start_polling_monitor(path)

    def _start_polling_monitor(self, path: str):
        if self._fs_poll_thread and self._fs_poll_thread.is_alive():
            return

        stop_event = self._fs_watch_stop

        def snapshot() -> tuple[int, int]:
            try:
                stat = os.stat(path)
                return int(stat.st_mtime), int(stat.st_size)
            except FileNotFoundError:
                return 0, 0

        last_snapshot = snapshot()

        def poll_loop():
            nonlocal last_snapshot
            while not stop_event.wait(30):
                current = snapshot()
                if current != last_snapshot:
                    self._schedule_reconcile()
                last_snapshot = current

        thread = threading.Thread(target=poll_loop, daemon=True)
        thread.start()
        self._fs_poll_thread = thread

    def _stop_filesystem_monitor(self):
        if self._fs_observer:
            try:
                self._fs_observer.stop()
                self._fs_observer.join(timeout=2)
            except Exception:
                pass
            finally:
                self._fs_observer = None
        if self._fs_poll_thread:
            self._fs_watch_stop.set()
            self._fs_poll_thread.join(timeout=2)
            self._fs_poll_thread = None
            self._fs_watch_stop.clear()
        self._watched_path = None

    def _schedule_reconcile(self):
        if self._pending_reconcile.is_set():
            return
        self._pending_reconcile.set()

        def run():
            try:
                time.sleep(1)
                self.reconcile_catalog(force=True)
            finally:
                self._pending_reconcile.clear()

        threading.Thread(target=run, daemon=True).start()

    def run_once(self, reason: str = "manual") -> bool:
        """Run a single sync cycle, logging the trigger reason."""
        with sync_lock() as acquired:
            if not acquired:
                return False
            try:
                from youspotter.status import add_recent
                add_recent(f"Sync starting ({reason})", "INFO")
            except Exception:
                pass
            return self.sync_spotify_tracks()

    def _download_worker_loop(self):
        """Continuously process download queue"""
        print("Download worker loop starting...")
        heartbeat_counter = 0
        while not self._stop.is_set():
            try:
                # Check if paused and wait for resume
                if self._paused.is_set():
                    print("Download worker: Paused, waiting for resume...")
                    # Wait until paused is cleared
                    while self._paused.is_set() and not self._stop.is_set():
                        time.sleep(0.1)  # Small sleep to avoid busy waiting
                    if self._stop.is_set():
                        break
                    print("Download worker: Resumed")
                    continue

                # Heartbeat logging every 5 iterations (5 seconds)
                heartbeat_counter += 1
                if heartbeat_counter % 5 == 0:
                    status = get_status()
                    pending_count = len(status.get('queue', {}).get('pending', []))
                    current_count = len(status.get('queue', {}).get('current', []))
                    print(f"Download worker heartbeat: {pending_count} pending, {current_count} current")

                self._process_download_queue()
            except Exception as e:
                print(f"Download worker error: {e}")
                import traceback
                traceback.print_exc()
                add_recent(f"Download worker exception: {str(e)}", "ERROR")
            self._stop.wait(1)  # Check for new items every 1 second
        print("Download worker loop stopped.")

    def _process_download_queue(self):
        """Process downloads sequentially for concurrency=1"""
        from youspotter.status import add_recent
        from youspotter.queue import identity_key

        try:
            print("Download worker: Starting queue processing")
            reconciliation = self.reconcile_catalog()
            live_status = self.get_live_queue_status()
            pending = live_status.get('pending', [])
            current = live_status.get('current', [])

            print(f"Download worker: Queue status - {len(pending)} pending, {len(current)} current")

            if current:
                print(f"Download worker: Skipping - already downloading {len(current)} items")
                return

            if not pending:
                print("Download worker: No pending items to process")
                return

            item_to_process = dict(pending[0])
            print(f"Download worker: Selected item: {item_to_process.get('artist','unknown')} - {item_to_process.get('title','')}")
        except Exception as e:
            print(f"Download worker: Error preparing queue: {e}")
            import traceback
            traceback.print_exc()
            return

        try:
            print("Download worker: Loading configuration")
            from youspotter.config import load_config
            cfg = load_config(self.db) if self.db else {}
            if not cfg.get('host_path'):
                cfg = {
                    "host_path": "/home/patrick/Music",
                    "bitrate": 192,
                    "format": "mp3",
                    "path_template": "{artist}/{album}/{artist} - {title}.{ext}",
                    "yt_cookie": ""
                }
                print("Download worker: Using fallback config")
            else:
                print(f"Download worker: Loaded config - host_path: {cfg.get('host_path', 'N/A')}")
        except Exception as e:
            print(f"Download worker: Error loading config: {e}")
            import traceback
            traceback.print_exc()
            cfg = {"host_path": "/home/patrick/Music", "bitrate": 192, "format": "mp3"}

        try:
            print("Download worker: Moving item to current queue")
            print(f"Download worker: Item details: {item_to_process}")
            self.live_move_to_current(item_to_process)
            print(f"Download worker: Starting download: {item_to_process.get('artist','unknown')} - {item_to_process.get('title','')}")
        except Exception as e:
            print(f"Download worker: Error moving to current queue: {e}")
            import traceback
            traceback.print_exc()
            return

        # Search YouTube for track
        try:
            print("Download worker: Searching YouTube for track")
            search_query = f"{item_to_process.get('artist', 'unknown')} - {item_to_process.get('title', '')}"
            print(f"Download worker: Search query: '{search_query}'")

            candidates = self.search_youtube(item_to_process) or []
            print(f"Download worker: Found {len(candidates)} YouTube candidates")

            if candidates:
                print("Download worker: Top candidates:")
                for i, c in enumerate(candidates[:3]):
                    print(f"  {i+1}. {c.get('title', 'N/A')} (duration: {c.get('duration', 'N/A')}s)")

            picked = None
            use_strict = cfg.get('use_strict_matching', False)
            for i, c in enumerate(candidates):
                if song_match_fuzzy(c, item_to_process, use_strict=use_strict):
                    picked = c
                    mode = "strict" if use_strict else "fuzzy"
                    print(f"Download worker: Selected candidate #{i+1} ({mode} matching): {c.get('title', 'N/A')}")
                    break
                else:
                    mode = "strict" if use_strict else "fuzzy"
                    print(f"Download worker: Candidate #{i+1} rejected by {mode} matching algorithm: {c.get('title', 'N/A')}")

            if not picked:
                reason = "no search results" if not candidates else f"no matches among {len(candidates)} candidates"
                print(f"Download worker: No match found - {reason}")
                artist = item_to_process.get('artist', 'unknown')
                title = item_to_process.get('title', '')
                add_recent(f"No YouTube match for {artist} - {title} ({reason})", "ERROR")
        except Exception as e:
            print(f"Download worker: Error in YouTube search: {e}")
            import traceback
            traceback.print_exc()
            picked = None

        success = False
        was_cancelled = False
        downloaded_path = None
        error_reason = None

        if picked:
            try:
                from youspotter.status import queue_update_progress

                def progress_callback(percent: int):
                    self.live_update_progress(item_to_process, percent)
                    queue_update_progress(item_to_process, percent)

                cfg_with_progress = dict(cfg)
                cfg_with_progress['progress_cb'] = progress_callback

                import concurrent.futures
                download_timeout = 300
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                    print(f"Download worker: Starting download with {download_timeout}s timeout")
                    future = executor.submit(self.download_func, picked, item_to_process, cfg_with_progress)
                    self._current_download_future = future
                    try:
                        result = future.result(timeout=download_timeout)
                        if isinstance(result, tuple):
                            success, downloaded_path = result
                        else:
                            success = bool(result)
                        print(f"Download worker: Download {'successful' if success else 'failed'}")
                    except concurrent.futures.TimeoutError:
                        success = False
                        was_cancelled = True
                        error_reason = f"timeout after {download_timeout}s"
                        add_recent(f"Download timeout for {item_to_process.get('artist', 'unknown')} - {item_to_process.get('title', '')}", "ERROR")
                        future.cancel()
                    except concurrent.futures.CancelledError:
                        success = False
                        was_cancelled = True
                        error_reason = "cancelled"
                    finally:
                        self._current_download_future = None
            except Exception as e:
                success = False
                error_reason = str(e)
                print(f"Download worker: Download exception: {error_reason}")
                import traceback
                traceback.print_exc()
        else:
            error_reason = "no candidate"

        try:
            if success:
                artist = item_to_process.get('artist', 'unknown')
                title = item_to_process.get('title', '')
                add_recent(f"Downloaded {artist} - {title}", "SUCCESS")
                if self.db and downloaded_path:
                    self.db.mark_download_success(identity_key(item_to_process), downloaded_path)
            else:
                if not was_cancelled and self.db:
                    reason_message = error_reason or "download failed"
                    self.db.mark_download_failure(identity_key(item_to_process), reason_message)

            self.live_complete_item(item_to_process, success)
            self.sync_to_persistent_queue()
        except Exception as e:
            print(f"Download worker: Error in completion handling: {e}")
            import traceback
            traceback.print_exc()

        if self.db:
            self.reconcile_catalog(force=True)

        print("Download worker: Processing completed for this iteration")

    def get_schedule(self) -> dict:
        return {
            "running": bool(self._thread and self._thread.is_alive()),
            "interval_seconds": getattr(self, "_interval", None) or 900,
            "next_sync_epoch": self.next_run_at,
        }

    def start_scheduler(self, interval_seconds: int = 900):
        if self._thread and self._thread.is_alive():
            return
        def loop():
            import time as _t
            while not self._stop.is_set():
                # Indicate sync is running by clearing next_run_at
                self.next_run_at = None
                self.run_once(reason="scheduled")

                completed_at = _t.time()
                try:
                    self.next_run_at = int(completed_at + int(interval_seconds))
                except Exception:
                    self.next_run_at = None

                # Wait the remaining interval duration (accounting for sync duration)
                while not self._stop.is_set():
                    now = _t.time()
                    wait_seconds = (completed_at + int(interval_seconds)) - now
                    if wait_seconds <= 0:
                        break
                    # Check for manual sync timer reset
                    if self._timer_reset.is_set():
                        self._timer_reset.clear()
                        # Reset timer: restart interval from now
                        completed_at = now
                        try:
                            self.next_run_at = int(completed_at + int(interval_seconds))
                        except Exception:
                            self.next_run_at = None
                        continue
                    # Wait in small increments so stop signal is responsive
                    sleep_for = min(wait_seconds, 1.0)
                    self._stop.wait(sleep_for)
                completed_at = _t.time()
        self._stop.clear()
        # Record configured interval for status/debugging
        self._interval = int(interval_seconds)
        self._thread = threading.Thread(target=loop, daemon=True)
        self._thread.start()

    def stop_scheduler(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1.0)

    def start_download_worker(self):
        """Start the continuous download worker"""
        if self._download_thread and self._download_thread.is_alive():
            return
        self._download_thread = threading.Thread(target=self._download_worker_loop, daemon=True)
        self._download_thread.start()

    def stop_download_worker(self):
        """Stop the download worker"""
        if self._download_thread:
            self._download_thread.join(timeout=1.0)
        self._stop_filesystem_monitor()

    def sync_now(self) -> bool:
        result = self.run_once(reason="manual")
        if result:
            # Reset scheduler timer after successful manual sync
            self._timer_reset.set()
        return result

    def notify_config_updated(self):
        self._ensure_watchdog()
        self._schedule_reconcile()

    def pause_downloads(self):
        """Pause the download worker and cancel current download"""
        print("Download worker: Pausing downloads...")
        self._paused.set()  # Set pause flag

        # Cancel current download if running
        if self._current_download_future:
            try:
                self._current_download_future.cancel()
                print("Download worker: Cancelled current download")
            except Exception as e:
                print(f"Download worker: Error cancelling download: {e}")

    def resume_downloads(self):
        """Resume the download worker"""
        print("Download worker: Resuming downloads...")
        self._paused.clear()  # Clear pause flag

    def is_paused(self) -> bool:
        """Check if downloads are currently paused"""
        return self._paused.is_set()

    def get_download_status(self) -> dict:
        """Get current download worker status"""
        return {
            "worker_running": bool(self._download_thread and self._download_thread.is_alive()),
            "paused": self.is_paused(),
            "has_current_download": bool(self._current_download_future)
        }

    # Lightweight status tracking methods (deadlock-free)
    def get_live_queue_status(self) -> dict:
        """Get current queue status without database persistence"""
        with self._status_lock:
            return {
                "current": list(self._live_status["current"]),
                "pending": list(self._live_status["pending"]),
                "completed": list(self._live_status["completed"])
            }

    def bootstrap_live_queue_from_status(self):
        """Refresh live queue snapshot from persisted status state."""
        self._load_persistent_into_live()

    def set_live_pending_queue(self, items: List[Dict]):
        """Set pending queue items"""
        with self._status_lock:
            self._live_status["pending"] = list(items)

    def live_move_to_current(self, item: Dict):
        """Move item to current downloads"""
        with self._status_lock:
            from youspotter.queue import identity_key
            # Add to current with progress tracking
            current_item = dict(item)
            current_item['progress'] = 0
            self._live_status["current"].append(current_item)

            # Remove from pending
            item_key = identity_key(item)
            self._live_status["pending"] = [
                p for p in self._live_status["pending"]
                if identity_key(p) != item_key
            ]

    def live_update_progress(self, item: Dict, progress: int):
        """Update progress for current download"""
        with self._status_lock:
            from youspotter.queue import identity_key
            item_key = identity_key(item)
            for current_item in self._live_status["current"]:
                if identity_key(current_item) == item_key:
                    current_item['progress'] = progress
                    break

    def live_complete_item(self, item: Dict, success: bool):
        """Complete an item (move from current to completed)"""
        with self._status_lock:
            from youspotter.queue import identity_key
            from datetime import datetime

            # Remove from current
            item_key = identity_key(item)
            self._live_status["current"] = [
                c for c in self._live_status["current"]
                if identity_key(c) != item_key
            ]

            # Add to completed
            completed_item = dict(item)
            completed_item["status"] = "downloaded" if success else "missing"
            completed_item["timestamp"] = datetime.now(timezone.utc).isoformat()
            self._live_status["completed"].insert(0, completed_item)

    def sync_to_persistent_queue(self):
        """Sync live queue state to persistent queue for UI and persistence"""
        try:
            from youspotter.status import set_queue
            with self._status_lock:
                # Sync pending and current items to persistent queue
                pending_items = list(self._live_status["pending"])
                current_items = list(self._live_status["current"])

                # Combine for persistent queue (UI expects pending to include current)
                all_pending = current_items + pending_items
                set_queue(all_pending)

                print(f"Synced to persistent: {len(current_items)} current + {len(pending_items)} pending")
        except Exception as e:
            print(f"Error syncing to persistent queue: {e}")
            import traceback
            traceback.print_exc()

    def _load_persistent_into_live(self):
        """Load persistent queue into live queue on startup"""
        try:
            from youspotter.status import get_status
            status = get_status()
            persistent_pending = status.get('queue', {}).get('pending', [])
            persistent_current = status.get('queue', {}).get('current', [])

            with self._status_lock:
                # Restore any pending items to live queue
                self._live_status["pending"] = list(persistent_pending)
                # Any items that were "current" should go back to pending
                # (they weren't completed in previous session)
                self._live_status["pending"].extend(persistent_current)
                # Clear current - download worker will populate as needed
                self._live_status["current"] = []

                print(f"Loaded persistent queue: {len(persistent_pending + persistent_current)} items restored to pending")
        except Exception as e:
            print(f"Error loading persistent queue: {e}")
            import traceback
            traceback.print_exc()
