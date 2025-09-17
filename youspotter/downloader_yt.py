import os
from typing import Dict, List, Optional, Tuple
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


def download_audio(candidate: Dict, track: Dict, cfg: Dict) -> Tuple[bool, Optional[str]]:
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
        return False, None
    
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
    downloaded_files: List[str] = []

    def hook(d):
        status = d.get('status')
        if status == 'finished':
            filename = d.get('filename') or d.get('_filename')
            if filename:
                downloaded_files.append(filename)
        if progress_cb and status == 'downloading':
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
            probe_info = None
            try:
                probe_info = ydl.extract_info(url, download=False)
            except Exception as probe_error:
                from .status import add_recent
                add_recent(
                    f"Download probe failed ({type(probe_error).__name__}): {track.get('artist','unknown')} - {track.get('title','')}",
                    "ERROR",
                )
                return False, None

            formats = (probe_info or {}).get('formats') or []
            available_kbps = [int(fmt.get('abr') or 0) for fmt in formats if fmt.get('abr')]
            max_available = max(available_kbps) if available_kbps else 0
            if min_kbps > max_available:
                from .status import add_recent
                add_recent(
                    f"Download blocked: requires ≥{min_kbps}kbps but max available is {max_available}kbps for {track.get('artist','unknown')} - {track.get('title','')}",
                    "ERROR",
                )
                return False, None

            ydl.download([url])

        # Clean up any leftover thumbnail files
        try:
            import glob
            # Build thumbnail pattern based on the output path structure
            # yt-dlp saves thumbnails with the same base name but different extensions
            base_name = outtmpl.replace('%(' + 'ext' + ')s', '')  # Remove extension placeholder

            # Look for common thumbnail extensions
            for ext in ['webp', 'jpg', 'jpeg', 'png']:
                thumb_pattern = base_name + ext
                for thumb_file in glob.glob(thumb_pattern):
                    try:
                        os.remove(thumb_file)
                        print(f"Cleaned up thumbnail: {thumb_file}")
                    except OSError:
                        pass
        except Exception:
            # Don't fail the download if cleanup fails
            pass

        final_path = None
        if downloaded_files:
            final_path = downloaded_files[-1]
            if final_path and not os.path.isabs(final_path):
                final_path = os.path.abspath(final_path)

        return True, final_path
    except Exception as e:
        from .logging import get_logger, with_context
        with_context(get_logger(__name__), attempt=1)[0].error(f"yt-dlp download failed: {e}")
        try:
            from .status import add_recent
            add_recent(f"Download failed ({type(e).__name__}): {track.get('artist','unknown')} - {track.get('title','')} — {str(e)}", "ERROR")
        except Exception:
            pass
        return False, None
