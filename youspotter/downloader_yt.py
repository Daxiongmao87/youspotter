import os
from typing import Dict
try:
    from yt_dlp import YoutubeDL as _YDL
except Exception:  # pragma: no cover
    _YDL = None


def _get_YoutubeDL():
    if _YDL is not None:
        return _YDL
    from yt_dlp import YoutubeDL  # type: ignore
    return YoutubeDL


def ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)


def download_audio(candidate: Dict, track: Dict, cfg: Dict) -> bool:
    # cfg: {host_path, bitrate, format}
    host_path = cfg.get('host_path') or '.'
    fmt = cfg.get('format', 'mp3')
    br = int(cfg.get('bitrate', 128))
    ensure_dir(host_path)
    # Path template conversion (user-specified pattern)
    from .utils.path_template import to_ytdlp_outtmpl
    user_tmpl = cfg.get('path_template') or '{artist}/{album}/{artist} - {title}.{ext}'
    try:
        out_part = to_ytdlp_outtmpl(user_tmpl)
    except Exception:
        out_part = '%(artist)s/%(album)s/%(artist)s - %(title)s.%(ext)s'
    outtmpl = os.path.join(host_path, out_part)
    min_kbps = int(br)
    url = candidate.get('url')
    if not url:
        return False
    # Pre-probe formats to enforce min abr
    probe_opts = {
        'quiet': True,
        'noprogress': True,
        'skip_download': True,
    }
    info = None
    YDL = _get_YoutubeDL()
    try:
        with YDL(probe_opts) as y:
            info = y.extract_info(url, download=False)
    except Exception as e:
        from .logging import get_logger, with_context
        with_context(get_logger(__name__), attempt=1)[0].error(f"yt-dlp probe failed: {e}")
        info = None
    if not info:
        return False
    fmts = info.get('formats') or []
    acceptable = [f for f in fmts if f.get('abr') and int(f.get('abr')) >= min_kbps]
    if not acceptable:
        return False
    ydl_opts = {
        'format': f"bestaudio[abr>={min_kbps}]",
        'outtmpl': outtmpl,
        'postprocessors': [
            {
                'key': 'FFmpegExtractAudio',
                'preferredcodec': fmt,
                'preferredquality': str(br),
            },
            {'key': 'FFmpegMetadata'},
            {'key': 'EmbedThumbnail'},
        ],
        'writethumbnail': True,
        'merge_output_format': fmt,
        'quiet': True,
        'noprogress': True,
    }
    # Optional YouTube cookies
    cookie_header = (cfg.get('yt_cookie') or '').strip()
    if cookie_header:
        ydl_opts.setdefault('http_headers', {})['Cookie'] = cookie_header
    # Progress hook
    progress_cb = cfg.get('progress_cb')
    def hook(d):
        if progress_cb and d.get('status') == 'downloading':
            p = d.get('_percent_str') or ''
            try:
                percent = int(float(p.strip().strip('%')))
            except Exception:
                percent = 0
            try:
                progress_cb(percent)
            except Exception:
                pass
    ydl_opts['progress_hooks'] = [hook]
    try:
        with YDL(ydl_opts) as ydl:
            ydl.download([url])
        return True
    except Exception as e:
        from .logging import get_logger, with_context
        with_context(get_logger(__name__), attempt=1)[0].error(f"yt-dlp download failed: {e}")
        return False
