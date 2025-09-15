from flask import Blueprint, render_template, redirect, request, jsonify, url_for
from .storage import DB
from .spotify_client import SpotifyClient


def init_web(app, db: DB, service):
    bp = Blueprint('web', __name__)
    sc = SpotifyClient(db)

    @bp.route('/')
    def index():
        return render_template('index.html')

    @bp.route('/auth/login')
    def auth_login():
        # Determine redirect_uri based on current request host
        redirect_uri = url_for('web.auth_callback', _external=True)
        client_id = db.get_setting('spotify_client_id') or None
        return redirect(sc.get_auth_url(redirect_uri=redirect_uri, client_id=client_id))

    @bp.route('/auth/callback')
    def auth_callback():
        code = request.args.get('code')
        state = request.args.get('state') or ''
        if code:
            redirect_uri = url_for('web.auth_callback', _external=True)
            client_id = db.get_setting('spotify_client_id') or None
            sc.handle_callback(code, state, redirect_uri=redirect_uri, client_id=client_id)
        return redirect('/')

    @bp.get('/playlists')
    def list_playlists():
        try:
            pls = sc.current_user_playlists()
        except Exception:
            pls = []
        import json
        raw = db.get_setting('selected_playlists') or ''
        strategies = {}
        try:
            strategies = json.loads(raw) if raw else {}
        except Exception:
            for pid in (raw.split(',') if raw else []):
                strategies[pid] = {'song': True, 'artist': False, 'album': False}
        selected_ids = set(strategies.keys())
        for p in pls:
            p['selected'] = p['id'] in selected_ids
            st = strategies.get(p['id'], {'song': True, 'artist': False, 'album': False})
            p['song'] = bool(st.get('song'))
            p['artist'] = bool(st.get('artist'))
            p['album'] = bool(st.get('album'))
        return jsonify(pls), 200

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
