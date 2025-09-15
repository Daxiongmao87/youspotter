from typing import Dict

VALID_BITRATES = {128, 192, 256, 320}
VALID_FORMATS = {"mp3", "flac", "m4a", "wav"}


def load_config(db) -> Dict:
    return {
        'host_path': db.get_setting('host_path') or '',
        'bitrate': int(db.get_setting('bitrate') or 128),
        'format': (db.get_setting('format') or 'mp3'),
        'concurrency': int(db.get_setting('concurrency') or 3),
        'spotify_client_id': db.get_setting('spotify_client_id') or '',
        'path_template': db.get_setting('path_template') or '{artist}/{album}/{artist} - {title}.{ext}',
        'yt_cookie': db.get_setting('yt_cookie') or '',
    }


def save_config(db, cfg: Dict):
    db.set_setting('host_path', cfg.get('host_path') or '')
    db.set_setting('bitrate', str(int(cfg.get('bitrate', 128))))
    db.set_setting('format', (cfg.get('format') or 'mp3'))
    db.set_setting('concurrency', str(int(cfg.get('concurrency', 3))))
    if 'spotify_client_id' in cfg:
        db.set_setting('spotify_client_id', cfg.get('spotify_client_id') or '')
    if 'path_template' in cfg:
        db.set_setting('path_template', cfg.get('path_template') or '{artist}/{album}/{artist} - {title}.{ext}')
    if 'yt_cookie' in cfg:
        db.set_setting('yt_cookie', cfg.get('yt_cookie') or '')
