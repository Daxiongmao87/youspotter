import os
from flask import Flask, request, jsonify
from typing import Dict, Optional

from pathlib import Path
from .status import get_status
from .storage import DB
from .sync_service import SyncService
from .storage import TokenStore
from .config import (
    save_config,
    load_config,
    VALID_BITRATES,
    VALID_FORMATS,
    VALID_CONCURRENCY,
)


def create_app(service: Optional[SyncService] = None, db_path: Optional[str] = None):
    app = Flask(__name__)
    
    # Configure Flask to prefer HTTPS for external URLs
    # This ensures that url_for() generates HTTPS URLs even when the app runs on HTTP
    app.config['PREFERRED_URL_SCHEME'] = 'https'

    db = DB(Path(db_path)) if db_path else None

    @app.get('/status')
    def status():
        st = get_status()
        # Normalize headline counters from catalog database
        try:
            if db:
                counts = db.get_catalog_counts()
                st['songs'] = counts['songs']
                st['artists'] = counts['artists']
                st['albums'] = counts['albums']
                st['downloaded'] = counts['downloaded']
                st['missing'] = counts['missing']
        except Exception as catalog_err:
            print(f"Warning: unable to read catalog counts: {catalog_err}")

        # Derive downloading from queue snapshot (current items)
        try:
            q = (st or {}).get('queue', {}) or {}
            current = q.get('current', []) or []
            st['downloading'] = len(current)
        except Exception:
            st['downloading'] = st.get('downloading', 0)
        # Surface scheduler info if available
        try:
            if service and hasattr(service, 'get_schedule'):
                st['schedule'] = service.get_schedule()
        except Exception:
            pass
        return st, 200

    @app.get('/queue')
    def queue_view():
        # Use lightweight status tracking (deadlock-free)
        if service:
            queue_data = service.get_live_queue_status()
        else:
            # Fallback to traditional status if no service
            st = get_status()
            queue_data = st.get('queue', {})

        # Add pagination support
        page = int(request.args.get('page', 1))
        page_size = int(request.args.get('page_size', 100))

        def paginate_list(items, page_num, size):
            start = (page_num - 1) * size
            end = start + size
            return items[start:end]

        # Paginate each queue section
        paginated_queue = {}
        for key in ['pending', 'current', 'completed']:
            items = queue_data.get(key, [])
            paginated_queue[key] = paginate_list(items, page, page_size)
            paginated_queue[f'{key}_total'] = len(items)

        # Success/failure breakdown of completed
        try:
            completed_items = queue_data.get('completed', []) or []
            paginated_queue['completed_success_total'] = len([x for x in completed_items if x.get('status') == 'downloaded'])
            paginated_queue['completed_failed_total'] = len([x for x in completed_items if x.get('status') == 'missing'])
        except Exception:
            paginated_queue['completed_success_total'] = 0
            paginated_queue['completed_failed_total'] = 0

        paginated_queue['page'] = page
        paginated_queue['page_size'] = page_size
        total_items = sum(len(queue_data.get(k, [])) for k in ['pending', 'current', 'completed'])
        paginated_queue['total_pages'] = (total_items + page_size - 1) // page_size
        paginated_queue['total_items'] = total_items

        return jsonify(paginated_queue), 200

    @app.get('/app/state')
    def app_state():
        configured = False
        client_ready = False
        if db:
            configured = bool((db.get_setting('host_path') or '').strip())
            client_ready = bool((db.get_setting('spotify_client_id') or '').strip())
        from .storage import TokenStore
        ts = TokenStore(db) if db else None
        at, rt = ts.load() if ts else (None, None)
        return jsonify({
            'configured': configured and client_ready,
            'authenticated': bool(at and rt),
        }), 200

    @app.post('/sync-now')
    def sync_now():
        if not service:
            return jsonify({"started": False, "reason": "service not configured"}), 200
        ok = service.sync_now()
        return jsonify({"started": ok}), 200

    @app.post('/reset-errors')
    def reset_errors():
        if not db:
            return jsonify({"reset": False, "reason": "db not configured"}), 200
        try:
            # Clear the retry schedule to reset timeout timers
            db.set_setting('retry_schedule', '{}')

            # Reset failed items tracking in sync service
            if service:
                service._failed_items.clear()

            # Move failed items back to pending queue and reset error counts
            from .status import reset_false_completions, set_status, get_status
            failed_count, success_count = reset_false_completions()

            # Reset error counts in status
            status = get_status()
            status['missing'] = 0  # Reset error count
            status['downloading'] = 0  # Reset downloading count
            set_status(status)

            return jsonify({
                "reset": True,
                "requeued_failed": failed_count,
                "kept_successful": success_count
            }), 200
        except Exception as e:
            return jsonify({"reset": False, "reason": f"error: {str(e)}"}), 500

    @app.post('/pause-downloads')
    def pause_downloads():
        if not service:
            return jsonify({"paused": False, "reason": "service not configured"}), 200
        try:
            service.pause_downloads()
            return jsonify({"paused": True}), 200
        except Exception as e:
            return jsonify({"paused": False, "reason": f"error: {str(e)}"}), 500

    @app.post('/resume-downloads')
    def resume_downloads():
        if not service:
            return jsonify({"resumed": False, "reason": "service not configured"}), 200
        try:
            service.resume_downloads()
            return jsonify({"resumed": True}), 200
        except Exception as e:
            return jsonify({"resumed": False, "reason": f"error: {str(e)}"}), 500

    @app.get('/download-status')
    def download_status():
        if not service:
            return jsonify({"status": "service not configured"}), 200
        try:
            status = service.get_download_status()
            return jsonify(status), 200
        except Exception as e:
            return jsonify({"status": "error", "reason": str(e)}), 500

    @app.post('/reset-queue')
    def reset_queue():
        """Reset stale queue items that are stuck in 'current' status"""
        try:
            from .status import get_status, set_status
            status = get_status()
            queue_data = status.get('queue', {})

            # Move all current items to completed as "missing" (since they're stale)
            current_items = queue_data.get('current', [])
            completed_items = queue_data.get('completed', [])

            # Mark current items as failed/missing and move to completed
            for item in current_items:
                item_copy = dict(item)
                item_copy['status'] = 'missing'
                from datetime import datetime, timezone
                item_copy['timestamp'] = datetime.now(timezone.utc).isoformat()
                completed_items.insert(0, item_copy)

            # Update status with cleared current queue
            updated_status = dict(status)
            updated_status['queue']['current'] = []
            updated_status['queue']['completed'] = completed_items

            set_status(updated_status)

            return jsonify({
                "reset": True,
                "moved_to_completed": len(current_items),
                "message": f"Moved {len(current_items)} stale items from current to completed"
            }), 200

        except Exception as e:
            return jsonify({"reset": False, "reason": f"error: {str(e)}"}), 500

    @app.get('/auth/status')
    def auth_status():
        if not db:
            return jsonify({"authenticated": False}), 200
        ts = TokenStore(db)
        at, rt = ts.load()
        return jsonify({"authenticated": bool(at and rt)}), 200

    # Config endpoints (simple key-value for MVP)
    from .config import VALID_BITRATES, VALID_FORMATS, load_config, save_config

    @app.get('/config')
    def get_config():
        if not db:
            return jsonify({}), 200
        return jsonify(load_config(db)), 200

    def _config_ready(db_inst: DB) -> bool:
        host = db_inst.get_setting('host_path') or ''
        playlists = db_inst.get_setting('selected_playlists') or ''
        return bool(host.strip()) and bool(playlists.strip())

    @app.post('/config')
    def set_config():
        if not db:
            return jsonify({"saved": False, "reason": "db not configured"}), 400
        data = request.get_json(force=True, silent=True) or {}
        host_path = data.get('host_path') or ''
        bitrate = int(data.get('bitrate', 128))
        fmt = (data.get('format') or 'mp3').lower()
        current_cfg = load_config(db)
        concurrency = int(data.get('concurrency', current_cfg.get('concurrency', 3)))
        client_id = (data.get('spotify_client_id') or '').strip()
        path_template = (data.get('path_template') or '{artist}/{album}/{artist} - {title}.{ext}').strip()
        # Validation per spec
        if bitrate not in VALID_BITRATES:
            return jsonify({"error": "invalid bitrate"}), 400
        if fmt not in VALID_FORMATS:
            return jsonify({"error": "invalid format"}), 400
        if not host_path.startswith('/'):
            return jsonify({"error": "host_path must be an absolute folder path"}), 400
        if concurrency not in VALID_CONCURRENCY:
            return jsonify({"error": "invalid concurrency"}), 400
        # Validate path template
        from .utils.path_template import validate_user_template
        try:
            validate_user_template(path_template)
        except Exception as e:
            return jsonify({"error": f"invalid path_template: {e}"}), 400
        cfg = {
            'host_path': host_path,
            'bitrate': bitrate,
            'format': fmt,
            'concurrency': concurrency,
            'spotify_client_id': client_id,
            'path_template': path_template,
            'yt_cookie': (data.get('yt_cookie') or '').strip(),
            'use_strict_matching': bool(data.get('use_strict_matching', False)),
        }
        save_config(db, cfg)
        if service:
            try:
                service.notify_config_updated()
            except Exception as cfg_err:
                print(f"Warning: failed to refresh configuration: {cfg_err}")
        # Auto-start scheduler if configured and service provided
        try:
            if service and _config_ready(db):
                # Kick off a scheduler and an immediate sync so users don't need to click
                service.start_scheduler(interval_seconds=900)
                try:
                    service.sync_now()
                except Exception:
                    pass
        except Exception:
            pass
        return jsonify({"saved": True}), 200

    # Catalog cache - populated on startup and during sync
    catalog_cache = {
        'songs': [],
        'artists': [],
        'albums': [],
        'last_updated': 0,
    }

    def refresh_catalog_cache():
        """Background task to refresh all catalog data"""
        print("Starting catalog cache refresh...")
        if not db:
            print("No database available for cache refresh")
            return

        try:
            import time
            # Check if cache is recent enough (5 minutes TTL)
            cache_age = time.time() - catalog_cache.get('last_updated', 0)
            if cache_age < 300:  # 5 minutes
                print(f"Catalog cache is recent ({cache_age:.1f}s old); skipping refresh")
                return

            # Get all tracked items from persistent catalog
            songs = _get_tracked_songs(db)
            artists = _get_tracked_artists(db)
            albums = _get_tracked_albums(db)
            print(f"Retrieved data: {len(songs)} songs, {len(artists)} artists, {len(albums)} albums")

            # Enhanced catalog with cached metadata
            enhanced_songs = _enhance_songs_with_metadata(songs, db)
            enhanced_artists = artists  # Use all artists
            enhanced_albums = albums  # Use all albums

            # Update cache atomically
            catalog_cache.update({
                'songs': enhanced_songs,
                'artists': enhanced_artists,
                'albums': enhanced_albums,
                'last_updated': time.time(),
            })
            print(f"Cache updated with {len(enhanced_songs)} songs, {len(enhanced_artists)} artists, {len(enhanced_albums)} albums")

        except Exception as e:
            # Log error but don't crash
            import traceback
            print(f"Error refreshing catalog cache: {e}")
            print("Traceback:")
            traceback.print_exc()

    # Catalog endpoints - now serve from cache
    @app.get('/catalog/<mode>')
    def get_catalog(mode):
        if mode not in ['songs', 'artists', 'albums']:
            return jsonify({"error": "Invalid catalog mode"}), 400

        # Serve from cache instantly
        return jsonify({"items": catalog_cache.get(mode, [])}), 200

    @app.get('/catalog/<mode>/<item_id>')
    def get_catalog_item(mode, item_id):
        if mode not in ['songs', 'artists', 'albums']:
            return jsonify({"error": "Invalid catalog mode"}), 400

        if not db:
            return jsonify({"error": "Database not configured"}), 500

        try:
            from .youtube_client import YouTubeMusicClient
            yt = YouTubeMusicClient()

            # Find the item in our catalog
            items = []
            if mode == 'songs':
                items = _get_tracked_songs(db)
            elif mode == 'artists':
                items = _get_tracked_artists(db)
            elif mode == 'albums':
                items = _get_tracked_albums(db)

            # Find the specific item
            item = None
            for i in items:
                if i['id'] == item_id:
                    item = i
                    break

            if not item:
                return jsonify({"error": "Item not found"}), 404

            # Get enhanced metadata
            enhanced_data = _fetch_ytm_metadata(yt, mode, item, db)
            if not enhanced_data:
                return jsonify({"error": "Failed to fetch metadata"}), 500

            # Add related items based on mode
            related = []
            if mode == 'songs':
                # For songs, show other songs by the same artist
                artist_songs = [s for s in _get_tracked_songs(db) if s['artist'] == item['artist'] and s['id'] != item_id]
                for song in artist_songs[:6]:  # Limit to 6 related items
                    related.append({
                        'id': song['id'],
                        'name': song['name'],
                        'type': 'songs',
                        'image': None
                    })
            elif mode == 'artists':
                # For artists, show their songs
                artist_songs = [s for s in _get_tracked_songs(db) if s['artist'] == item['name']]
                for song in artist_songs[:6]:
                    related.append({
                        'id': song['id'],
                        'name': song['name'],
                        'type': 'songs',
                        'image': None
                    })

            enhanced_data['related'] = related
            return jsonify(enhanced_data), 200

        except Exception as e:
            return jsonify({"error": str(e)}), 500

    def _get_tracked_songs(db_inst):
        if not db_inst:
            return []
        try:
            return db_inst.fetch_catalog_tracks()
        except Exception as exc:
            print(f"Error fetching catalog tracks: {exc}")
            return []

    def _get_tracked_artists(db_inst):
        if not db_inst:
            return []
        try:
            songs = db_inst.fetch_catalog_tracks()
            counts: Dict[str, int] = {}
            for song in songs:
                artist_name = song.get('artist') or 'Unknown'
                counts[artist_name] = counts.get(artist_name, 0) + 1

            artists = db_inst.fetch_catalog_artists()
            return [
                {
                    'id': artist['id'],
                    'name': artist['name'],
                    'song_count': counts.get(artist['name'], 0),
                }
                for artist in artists
            ]
        except Exception as exc:
            print(f"Error fetching catalog artists: {exc}")
            return []

    def _get_tracked_albums(db_inst):
        if not db_inst:
            return []
        try:
            songs = db_inst.fetch_catalog_tracks()
            counts: Dict[tuple, int] = {}
            for song in songs:
                album_name = (song.get('album') or '').strip()
                artist_name = song.get('artist') or 'Unknown'
                if not album_name:
                    continue
                key = (album_name, artist_name)
                counts[key] = counts.get(key, 0) + 1

            albums = db_inst.fetch_catalog_albums()
            return [
                {
                    'id': album['id'],
                    'name': album['name'],
                    'artist': album.get('artist'),
                    'track_count': counts.get((album['name'], album.get('artist')), 0),
                }
                for album in albums
            ]
        except Exception as exc:
            print(f"Error fetching catalog albums: {exc}")
            return []

    def _fetch_ytm_metadata(yt_client, mode, item, db_inst=None):
        if mode == 'songs':
            # Search for the song to get YTM metadata
            track = {'artist': item['artist'], 'title': item['name']}
            results = yt_client.search_song(track)
            if results:
                result = results[0]
                return {
                    'id': item['id'],
                    'name': item['name'],
                    'artist': item['artist'],
                    'image': result.get('thumbnail'),  # Extract thumbnail from YTM search
                    'url': result.get('url', ''),
                    'duration': result.get('duration', 0),
                    'status': item.get('status', 'unknown')
                }
        elif mode == 'artists':
            # For artists, we could search for their top songs, but for now just return basic info
            return {
                'id': item['id'],
                'name': item['name'],
                'image': None,
                'song_count': 0  # Could be enhanced with actual count
            }
        elif mode == 'albums':
            # For albums, return basic info with track count
            songs = _get_tracked_songs(db_inst) if hasattr(db_inst, 'get_setting') else []
            track_count = len([s for s in songs if s.get('album') == item['name']])
            return {
                'id': item['id'],
                'name': item['name'],
                'artist': item.get('artist', 'Unknown'),
                'image': None,  # Could be enhanced with album art search
                'track_count': track_count
            }

        return None

    def _enhance_songs_with_metadata(songs, db_inst):
        """Enhance songs with cached metadata, fetching new metadata for uncached songs"""
        if not db_inst:
            return songs

        enhanced_songs = []
        songs_to_fetch = []

        # Check cache for each song
        for song in songs:
            cache_key = f"metadata_{song['id']}"
            cached_data = db_inst.get_setting(cache_key)

            if cached_data:
                try:
                    import json
                    metadata = json.loads(cached_data)
                    # Use cached metadata
                    enhanced_song = dict(song)
                    enhanced_song['image'] = metadata.get('image')
                    enhanced_songs.append(enhanced_song)
                except Exception:
                    # Invalid cache, add to fetch list
                    songs_to_fetch.append(song)
                    enhanced_songs.append(song)
            else:
                # No cache, add to fetch list
                songs_to_fetch.append(song)
                enhanced_songs.append(song)

        # Fetch metadata for uncached songs (limit to avoid API overwhelm)
        if songs_to_fetch:
            print(f"Fetching metadata for {len(songs_to_fetch)} uncached songs (limiting to first 50)")
            try:
                from .youtube_client import YouTubeMusicClient
                yt = YouTubeMusicClient()

                # Limit to first 50 songs to avoid overwhelming the API
                for song in songs_to_fetch[:50]:
                    try:
                        # Search for the song
                        track = {'artist': song['artist'], 'title': song['name']}
                        results = yt.search_song(track)

                        if results:
                            result = results[0]  # Take first match
                            metadata = {
                                'image': result.get('thumbnail'),
                                'url': result.get('url', ''),
                                'duration': result.get('duration', 0)
                            }

                            # Cache the metadata
                            cache_key = f"metadata_{song['id']}"
                            import json
                            db_inst.set_setting(cache_key, json.dumps(metadata))

                            # Update the enhanced song
                            for i, enhanced_song in enumerate(enhanced_songs):
                                if enhanced_song['id'] == song['id']:
                                    enhanced_songs[i]['image'] = metadata['image']
                                    break
                    except Exception as e:
                        print(f"Failed to fetch metadata for {song['name']}: {e}")

            except Exception as e:
                print(f"Error initializing YouTube client for metadata: {e}")

        return enhanced_songs

    # Initialize catalog cache on startup
    print(f"Debug: db={db}, service={service}")
    if db and service:
        print("Starting background catalog cache refresh...")
        import threading
        def startup_cache_refresh():
            import time
            time.sleep(2)  # Let service initialize first
            refresh_catalog_cache()

        # Start cache refresh in background thread
        cache_thread = threading.Thread(target=startup_cache_refresh, daemon=True)
        cache_thread.start()
    else:
        print("Not starting cache refresh: db or service is None")

    # Attach web UI if DB provided
    if db:
        from .web import init_web  # lazy import
        init_web(app, db, service)

    # Make cache refresh function available to service
    app.refresh_catalog_cache = refresh_catalog_cache

    return app
