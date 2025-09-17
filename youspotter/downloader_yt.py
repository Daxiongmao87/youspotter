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
        try:
            from .status import add_recent
            add_recent(f"Download aborted: no URL for {track.get('artist','unknown')} - {track.get('title','')}", "ERROR")
        except Exception:
            pass
        return False
    
    # Simplified yt-dlp options similar to LidaTube
    ydl_opts = {
        'format': f"bestaudio[abr>={min_kbps}]/bestaudio/best",
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
    
    # Add cookie support if provided
    cookie_header = cfg.get('yt_cookie', '').strip()
    if cookie_header and cookie_header.startswith('# Netscape HTTP Cookie File'):
        # User provided a full cookies.txt; write verbatim and use as cookiefile
        import tempfile
        cf = tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False)
        cf.write(cookie_header)
        cf.close()
        ydl_opts['cookiefile'] = cf.name
    elif cookie_header:
        # Create temporary cookie file for yt-dlp
        import tempfile
        cookie_file = tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False)
        try:
            # Convert header cookies to Netscape format
            cookie_file.write("# Netscape HTTP Cookie File\n")
            for cookie in cookie_header.split(';'):
                cookie = cookie.strip()
                if '=' in cookie:
                    name, value = cookie.split('=', 1)
                    # Simple Netscape format: domain, flag, path, secure, expiration, name, value
                    cookie_file.write(f".youtube.com\tTRUE\t/\tFALSE\t0\t{name.strip()}\t{value.strip()}\n")
            cookie_file.close()
            ydl_opts['cookiefile'] = cookie_file.name
        except Exception:
            if cookie_file and not cookie_file.closed:
                cookie_file.close()
            # Fallback to headers if cookie file creation fails
            ydl_opts.setdefault('http_headers', {})
            ydl_opts['http_headers']['Cookie'] = cookie_header
    
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
    
    YDL = _get_YoutubeDL()
    try:
        with YDL(ydl_opts) as ydl:
            ydl.download([url])

        # Clean up any leftover thumbnail files
        try:
            import glob
            # Get the base path without extension from the template
            base_path = outtmpl.replace('%(' + 'ext' + ')s', '*')
            # Look for common thumbnail extensions
            for ext in ['webp', 'jpg', 'jpeg', 'png']:
                thumb_pattern = base_path.replace('*', ext)
                for thumb_file in glob.glob(thumb_pattern):
                    try:
                        os.remove(thumb_file)
                    except OSError:
                        pass
        except Exception:
            # Don't fail the download if cleanup fails
            pass

        return True
    except Exception as e:
        from .logging import get_logger, with_context
        with_context(get_logger(__name__), attempt=1)[0].error(f"yt-dlp download failed: {e}")
        try:
            from .status import add_recent
            add_recent(f"Download failed ({type(e).__name__}): {track.get('artist','unknown')} - {track.get('title','')} — {str(e)}", "ERROR")
        except Exception:
            pass
        return False
