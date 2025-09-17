import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
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
        download_func: Callable[[Dict, Dict, Dict], bool],
        concurrency_cap: int = 3,
        db: DB | None = None,
        fetch_playlist_strategies: Optional[Callable[[], Dict[str,str]]] = None,
        spotify_client: Optional[object] = None,
        catalog_refresh_callback: Optional[Callable[[], None]] = None,
    ):
        self.fetch_spotify_tracks = fetch_spotify_tracks
        self.search_youtube = search_youtube
        self.download_func = download_func
        self.concurrency_cap = concurrency_cap
        self.db = db
        self._stop = threading.Event()
        self._paused = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._download_thread: Optional[threading.Thread] = None
        self._current_download_future = None  # Track current download for cancellation

        # Lightweight status tracking (deadlock-free)
        self._status_lock = threading.Lock()
        self._live_status = {
            "current": [],  # Currently downloading items
            "pending": [],  # Pending queue items
            "completed": []  # Completed items with status
        }
        self.fetch_playlist_strategies = fetch_playlist_strategies or (lambda: {})
        self.spotify_client = spotify_client
        self.catalog_refresh_callback = catalog_refresh_callback
        self.interval_seconds = int(concurrency_cap and 0)  # placeholder; set in scheduler
        self.next_run_at: Optional[int] = None
        self._failed_items = set()  # Track failed items to skip them

    def sync_spotify_tracks(self) -> bool:
        """Sync Spotify track data and update pending queue"""
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

        # Compute totals for tracking
        try:
            songs = len(tracks)
            artists = len({t.get('artist','') for t in tracks})
            albums = len({t.get('album','') for t in tracks if t.get('album')})
            from youspotter.status import set_totals
            set_totals(songs, artists, albums)
        except Exception:
            pass

        # Add tracks to persistent pending queue, filtered by filesystem presence
        from youspotter.status import set_queue, add_recent
        queue_tracks = [{k: t.get(k) for k in ('artist','title','album','duration')} for t in tracks]

        # Filesystem-as-truth: remove items that already exist on disk
        try:
            existing_pairs = set()
            if self.db:
                from youspotter.config import load_config
                from youspotter.utils.path_template import to_path_regex
                from youspotter.utils.matching import normalize_text
                import os as _os, re as _re
                cfg = load_config(self.db)
                host = (cfg.get('host_path') or '').strip()
                fmt = (cfg.get('format') or 'mp3').lower()
                tmpl = (cfg.get('path_template') or '{artist}/{album}/{artist} - {title}.{ext}').strip()
                if host and _os.path.isabs(host) and _os.path.isdir(host):
                    pattern = _re.compile(to_path_regex(tmpl))
                    for root, _dirs, files in _os.walk(host):
                        for fn in files:
                            if not fn.lower().endswith(f'.{fmt}'):
                                continue
                            rel = _os.path.relpath(_os.path.join(root, fn), host)
                            rel = rel.replace('\\', '/')  # normalize
                            m = pattern.match(rel)
                            if not m:
                                continue
                            gd = m.groupdict()
                            a = normalize_text(gd.get('artist') or '')
                            t = normalize_text(gd.get('title') or '')
                            if a and t:
                                existing_pairs.add((a, t))
            if existing_pairs:
                queue_tracks = [q for q in queue_tracks if (normalize_text(q.get('artist','')), normalize_text(q.get('title',''))) not in existing_pairs]
        except Exception:
            # If anything goes wrong, fall back to unfiltered queue
            pass

        set_queue(queue_tracks)
        # Also populate lightweight status tracking
        self.set_live_pending_queue(queue_tracks)

        add_recent(f"Synced {len(tracks)} tracks from Spotify ({songs} songs, {artists} artists, {albums} albums) — pending after filesystem filter: {len(queue_tracks)}", "SUCCESS")

        return True

    def run_once(self) -> bool:
        """Legacy method - now just syncs Spotify tracks"""
        with sync_lock() as acquired:
            if not acquired:
                return False
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
        from youspotter.status import get_status, queue_move_to_current, queue_complete, add_recent
        from youspotter.queue import identity_key

        try:
            print("Download worker: Starting queue processing")
            status = get_status()
            pending = status.get('queue', {}).get('pending', [])
            current = status.get('queue', {}).get('current', [])

            print(f"Download worker: Queue status - {len(pending)} pending, {len(current)} current")

            # For concurrency=1, only process if nothing is currently downloading
            if current:
                print(f"Download worker: Skipping - already downloading {len(current)} items")
                return  # Already downloading something

            if not pending:
                print("Download worker: No pending items to process")
                return  # Nothing to download

            print(f"Download worker: Found {len(pending)} pending items, starting processing")
        except Exception as e:
            print(f"Download worker: Error in initial queue check: {e}")
            import traceback
            traceback.print_exc()
            return

        # Load retry schedule - database should now be thread-safe
        try:
            if self.db:
                import json
                retry_raw = self.db.get_setting('retry_schedule') or '{}'
                retry_schedule = json.loads(retry_raw)
            else:
                retry_schedule = {}
        except Exception as e:
            print(f"Download worker: Error loading retry schedule: {e}")
            retry_schedule = {}

        # Find first available item considering retry schedule and failed items
        print("Download worker: Selecting item to process")
        import time
        current_time = int(time.time())

        item_to_process = None
        skipped_count = 0
        for item in pending:
            try:
                ik = identity_key(item)

                # Check if item is in temporary failed list (current session)
                if ik in self._failed_items:
                    skipped_count += 1
                    continue

                # Check retry schedule for items that failed in previous sessions
                retry_time = retry_schedule.get(ik, 0)
                if retry_time > current_time:
                    print(f"Download worker: Skipping item {item.get('artist', 'unknown')} - {item.get('title', '')} (retry in {retry_time - current_time}s)")
                    skipped_count += 1
                    continue

                # This item is available for processing
                item_to_process = item
                break

            except Exception as e:
                print(f"Download worker: Error checking item: {e}")
                continue

        if not item_to_process:
            print(f"Download worker: No items available - {skipped_count} items skipped (failed or on retry cooldown)")
            # After checking 50 items, clear failed list to retry everything
            if skipped_count >= 50:
                self._failed_items.clear()
                print("Download worker: Cleared failed items list after checking 50 items, will retry all")
                if pending:
                    # Still check retry schedule for the first item
                    first_item = pending[0]
                    try:
                        ik = identity_key(first_item)
                        retry_time = retry_schedule.get(ik, 0)
                        if retry_time <= current_time:
                            item_to_process = first_item
                        else:
                            print(f"Download worker: First item still on retry cooldown ({retry_time - current_time}s)")
                            return
                    except Exception:
                        item_to_process = first_item
                else:
                    return
            else:
                print("Download worker: No non-failed items found, waiting for next iteration")
                return

        print(f"Download worker: Selected item: {item_to_process.get('artist','unknown')} - {item_to_process.get('title','')}")

        # Load config - database should now be thread-safe
        try:
            print("Download worker: Loading configuration")
            from youspotter.config import load_config
            cfg = load_config(self.db) if self.db else {}
            if not cfg.get('host_path'):
                # Fallback to defaults if no config
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

        # Move item to current status ONLY when actually starting
        try:
            print("Download worker: Moving item to current queue")
            print(f"Download worker: Item details: {item_to_process}")

            # Use lightweight status tracking (deadlock-free)
            self.live_move_to_current(item_to_process)

            # Successfully moved to current queue
            print(f"Download worker: Starting download: {item_to_process.get('artist','unknown')} - {item_to_process.get('title','')}")
            print("Download worker: Moved to current queue, proceeding to download")

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

            # Log the first few candidates for debugging
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

            if not picked and candidates:
                print(f"Download worker: No matching candidate found among {len(candidates)} results")
                print(f"Download worker: Search query was: '{search_query}'")
                print(f"Download worker: Expected: {item_to_process.get('artist', 'unknown')} - {item_to_process.get('title', '')}")
            elif not picked:
                print("Download worker: No matching candidate found - no search results")

        except Exception as e:
            print(f"Download worker: Error in YouTube search: {e}")
            print(f"Download worker: YouTube search failed for {item_to_process.get('artist','unknown')} - {item_to_process.get('title','')}: {str(e)}")
            import traceback
            traceback.print_exc()
            candidates = []
            picked = None

        success = False
        was_cancelled = False
        if not picked:
            reason = "no search results" if not candidates else f"no matches among {len(candidates)} candidates"
            print(f"Download worker: No match found - {reason}")
            print(f"Download worker: No matching YouTube result for {item_to_process.get('artist','unknown')} - {item_to_process.get('title','')}")

            # Add to recent activity log for user visibility
            from youspotter.status import add_recent
            artist = item_to_process.get('artist', 'unknown')
            title = item_to_process.get('title', '')
            add_recent(f"No YouTube match for {artist} - {title} ({reason})", "ERROR")
        else:
            # Download with progress callback
            def progress_cb(percent: int):
                try:
                    # Use lightweight progress tracking
                    self.live_update_progress(item_to_process, percent)
                except Exception as e:
                    print(f"Download worker: Error updating progress: {e}")

            # Download with timeout mechanism
            try:
                print(f"Download worker: Starting download for {item_to_process.get('artist','unknown')} - {item_to_process.get('title','')}")
                cfg_with_progress = dict(cfg)
                cfg_with_progress['progress_cb'] = progress_cb

                # Implement timeout mechanism using ThreadPoolExecutor
                import concurrent.futures
                download_timeout = 300  # 5 minutes timeout

                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                    print(f"Download worker: Starting download with {download_timeout}s timeout")
                    future = executor.submit(self.download_func, picked, item_to_process, cfg_with_progress)
                    self._current_download_future = future  # Track for cancellation
                    try:
                        success = future.result(timeout=download_timeout)
                        print(f"Download worker: Download {'successful' if success else 'failed'}")
                    except concurrent.futures.TimeoutError:
                        print(f"Download worker: Download timed out after {download_timeout} seconds")
                        add_recent(f"Download timeout for {item_to_process.get('artist', 'unknown')} - {item_to_process.get('title', '')}", "ERROR")
                        success = False
                        # Cancel the future to prevent resource leaks
                        future.cancel()
                    except concurrent.futures.CancelledError:
                        print(f"Download worker: Download was cancelled")
                        success = False
                        was_cancelled = True
                    finally:
                        self._current_download_future = None  # Clear tracking

            except Exception as e:
                print(f"Download worker: Download exception: {e}")
                import traceback
                traceback.print_exc()
                print(f"Download worker: Download exception for {item_to_process.get('artist', 'unknown')} - {item_to_process.get('title', '')}: {str(e)}")
                success = False

        # Handle completion
        try:
            print(f"Download worker: Handling completion - success: {success}")
            if success:
                artist = item_to_process.get('artist', 'unknown')
                title = item_to_process.get('title', '')
                print(f"Download worker: Downloaded {artist} - {title}")
                print("Download worker: Download successful")

                # Add to recent activity log for user visibility
                from youspotter.status import add_recent
                add_recent(f"Downloaded {artist} - {title}", "SUCCESS")
            else:
                if was_cancelled:
                    print(f"Download worker: Download was cancelled for {item_to_process.get('artist', 'unknown')} - {item_to_process.get('title', '')}")
                    print("Download worker: Will put cancelled item back at front of queue")
                    # TODO: Put cancelled item back at front of queue when resume happens
                    # For now, just don't mark it as failed so it can be retried
                else:
                    print(f"Download worker: Failed to download {item_to_process.get('artist', 'unknown')} - {item_to_process.get('title', '')}")
                    print("Download worker: Download failed")
                    # Add to failed items and retry schedule
                    try:
                        import time
                        ik = identity_key(item_to_process)
                        self._failed_items.add(ik)

                        # Calculate exponential backoff for retry (5 min, 15 min, 45 min, 2.25 hours, etc)
                        current_retry_time = retry_schedule.get(ik, 0)
                        current_time = int(time.time())

                        if current_retry_time == 0:
                            # First failure - retry in 5 minutes
                            retry_delay = 300  # 5 minutes
                        else:
                            # Exponential backoff - triple the delay each time, max 6 hours
                            last_delay = current_retry_time - current_time if current_retry_time > current_time else 300
                            retry_delay = min(last_delay * 3, 21600)  # Max 6 hours

                        retry_schedule[ik] = current_time + retry_delay
                        print(f"Download worker: Added item to failed list ({len(self._failed_items)} total failed), retry in {retry_delay//60} minutes")
                    except Exception as e:
                        print(f"Download worker: Error adding to failed list: {e}")

            # Use lightweight status tracking (deadlock-free)
            self.live_complete_item(item_to_process, success)
            status_text = "successfully" if success else "with error"
            print(f"Download worker: Completed item {status_text}")

        except Exception as e:
            print(f"Download worker: Error in completion handling: {e}")
            import traceback
            traceback.print_exc()

        # Save retry schedule back to database
        try:
            if self.db and retry_schedule:
                import json
                self.db.set_setting('retry_schedule', json.dumps(retry_schedule))
        except Exception as e:
            print(f"Download worker: Error saving retry schedule: {e}")

        # Refresh catalog cache after downloads
        if self.catalog_refresh_callback:
            try:
                print("Download worker: Starting catalog cache refresh")
                refresh_thread = threading.Thread(target=self.catalog_refresh_callback, daemon=True)
                refresh_thread.start()
            except Exception as e:
                print(f"Download worker: Error starting catalog refresh: {e}")

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
            while not self._stop.is_set():
                # Set next run time before sleeping so UI can show ETA
                try:
                    import time as _t
                    self.next_run_at = int(_t.time()) + int(interval_seconds)
                except Exception:
                    self.next_run_at = None
                self.run_once()
                self._stop.wait(interval_seconds)
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

    def sync_now(self) -> bool:
        return self.run_once()

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
            completed_item["timestamp"] = datetime.utcnow().isoformat() + "Z"
            self._live_status["completed"].insert(0, completed_item)
