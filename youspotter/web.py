import json
import time

from flask import Blueprint, render_template, redirect, request, jsonify, url_for
from .storage import DB
from .spotify_client import SpotifyClient


def init_web(app, db: DB, service):
    bp = Blueprint('web', __name__)
    sc = SpotifyClient(db)

    def _get_redirect_uri():
        # Use request context to generate the redirect URI with HTTPS
        # Spotify requires HTTPS redirect URIs for security
        return url_for('web.auth_callback', _external=True, _scheme='https')

    @bp.route('/')
    def index():
        return render_template('index.html')

    @bp.route('/auth/login')
    def auth_login():
        # Determine redirect_uri based on current request host
        redirect_uri = _get_redirect_uri()
        client_id = db.get_setting('spotify_client_id') or None
        return redirect(sc.get_auth_url(redirect_uri=redirect_uri, client_id=client_id))

    @bp.route('/auth/expected')
    def auth_expected():
        # Small diagnostic endpoint to confirm exact redirect_uri and client_id used
        redirect_uri = _get_redirect_uri()
        client_id = db.get_setting('spotify_client_id') or ''
        return jsonify({
            'redirect_uri': redirect_uri,
            'client_id': client_id,
        }), 200

    @bp.route('/auth/callback')
    def auth_callback():
        code = request.args.get('code')
        state = request.args.get('state') or ''
        if code:
            redirect_uri = _get_redirect_uri()
            client_id = db.get_setting('spotify_client_id') or None
            try:
                sc.handle_callback(code, state, redirect_uri=redirect_uri, client_id=client_id)
            except Exception:
                # On error, redirect back with a flag so UI can show guidance
                return redirect('/?auth_error=1')
        return redirect('/')

    @bp.get('/playlists')
    def list_playlists():
        cache_ttl = 900
        now = int(time.time())

        def load_cache():
            raw_cache = db.get_kv('playlist_cache') or ''
            if not raw_cache:
                return {}
            try:
                return json.loads(raw_cache)
            except Exception:
                return {}

        def save_cache(data):
            payload = {
                'timestamp': now,
                'expires_at': now + cache_ttl,
                'data': data,
            }
            db.set_kv('playlist_cache', json.dumps(payload))
            db.set_kv('playlist_rate_limited_until', '0')

        def apply_selection(pls):
            raw = db.get_setting('selected_playlists') or ''
            strategies = {}
            try:
                strategies = json.loads(raw) if raw else {}
            except Exception:
                for pid in (raw.split(',') if raw else []):
                    strategies[pid] = {'song': False, 'artist': False, 'album': False}
            selected_ids = set(strategies.keys())
            result = []
            for p in pls:
                entry = dict(p)
                entry['selected'] = entry.get('id') in selected_ids
                st = strategies.get(entry.get('id'), {'song': False, 'artist': False, 'album': False})
                if not isinstance(st, dict):
                    st = {'song': False, 'artist': False, 'album': False}
                entry['song'] = bool(st.get('song'))
                entry['artist'] = bool(st.get('artist'))
                entry['album'] = bool(st.get('album'))
                result.append(entry)
            return result

        cache = load_cache()
        cached_data = cache.get('data') if cache else []
        cache_valid = bool(cache and cache.get('expires_at', 0) > now)
        if cache_valid:
            return jsonify(apply_selection(cached_data)), 200

        rate_limited_until = int(db.get_kv('playlist_rate_limited_until') or 0)
        if rate_limited_until > now:
            remaining = rate_limited_until - now
            if cached_data:
                return jsonify(apply_selection(cached_data)), 200
            return jsonify({"error": "Spotify rate limited", "retry_after": remaining}), 429

        try:
            pls = sc.current_user_playlists()
        except RuntimeError as e:
            msg = str(e) or 'error'
            if msg.startswith('rate_limited:'):
                retry_after = int(msg.split(':', 1)[1] or 60)
                db.set_kv('playlist_rate_limited_until', str(now + retry_after))
                if cached_data:
                    return jsonify(apply_selection(cached_data)), 200
                return jsonify({"error": "Spotify rate limited", "retry_after": retry_after}), 429
            if cached_data:
                return jsonify(apply_selection(cached_data)), 200
            return jsonify({"error": msg}), 401
        except Exception as e:
            msg = str(e) or 'error'
            if cached_data:
                return jsonify(apply_selection(cached_data)), 200
            return jsonify({"error": msg}), 401

        save_cache(pls)
        enriched = apply_selection(pls)

        from .logging import get_logger, with_context
        try:
            logger, _ = with_context(get_logger(__name__))
            logger.info(f"/playlists -> {len(enriched)} items")
        except Exception:
            pass

        return jsonify(enriched), 200

    def _config_ready(db_inst: DB) -> bool:
        host = db_inst.get_setting('host_path') or ''
        playlists = db_inst.get_setting('selected_playlists') or ''
        return bool(host.strip()) and bool(playlists.strip())

    @bp.post('/playlists')
    def save_playlists():
        import json
        data = request.get_json(force=True, silent=True) or {}
        items = data.get('items') or []
        if not isinstance(items, list):
            return jsonify({"error": "items must be list"}), 400
        strat = {}
        for it in items:
            pid = str(it.get('id') or '')
            song = bool(it.get('song'))
            artist = bool(it.get('artist'))
            album = bool(it.get('album'))
            if pid and (song or artist or album):
                strat[pid] = {'song': song, 'artist': artist, 'album': album}
        db.set_setting('selected_playlists', json.dumps(strat))
        # Auto-start scheduler if configured
        try:
            from .sync_service import SyncService  # type: ignore
            # service passed via closure
            if _config_ready(db) and service:
                service.start_scheduler(interval_seconds=900)
        except Exception:
            pass
        return jsonify({"saved": True}), 200

    app.register_blueprint(bp)
