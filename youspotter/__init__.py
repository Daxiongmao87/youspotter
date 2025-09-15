import os
from flask import Flask, request, jsonify
from typing import Optional

from pathlib import Path
from .status import get_status
from .storage import DB
from .sync_service import SyncService
from .storage import TokenStore


def create_app(service: Optional[SyncService] = None, db_path: Optional[str] = None):
    app = Flask(__name__)

    db = DB(Path(db_path)) if db_path else None

    @app.get('/status')
    def status():
        return get_status(), 200

    @app.get('/queue')
    def queue_view():
        st = get_status()
        return jsonify(st.get('queue', {})), 200

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
        concurrency = int(data.get('concurrency', 3))
        client_id = (data.get('spotify_client_id') or '').strip()
        path_template = (data.get('path_template') or '{artist}/{album}/{artist} - {title}.{ext}').strip()
        # Validation per spec
        if bitrate not in VALID_BITRATES:
            return jsonify({"error": "invalid bitrate"}), 400
        if fmt not in VALID_FORMATS:
            return jsonify({"error": "invalid format"}), 400
        if not host_path.startswith('/'):
            return jsonify({"error": "host_path must be an absolute folder path"}), 400
        # Validate path template
        from .utils.path_template import validate_user_template
        try:
            validate_user_template(path_template)
        except Exception as e:
            return jsonify({"error": f"invalid path_template: {e}"}), 400
        if not (1 <= concurrency <= 10):
            return jsonify({"error": "invalid concurrency"}), 400
        cfg = {
            'host_path': host_path,
            'bitrate': bitrate,
            'format': fmt,
            'concurrency': concurrency,
            'spotify_client_id': client_id,
            'path_template': path_template,
        }
        save_config(db, cfg)
        # Auto-start scheduler if configured and service provided
        try:
            if service and _config_ready(db):
                service.concurrency_cap = concurrency
                service.start_scheduler(interval_seconds=900)
        except Exception:
            pass
        return jsonify({"saved": True}), 200

    # Attach web UI if DB provided
    if db:
        from .web import init_web  # lazy import
        init_web(app, db, service)
    return app
