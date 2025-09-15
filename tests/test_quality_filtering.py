from youspotter.downloader_yt import download_audio


class FakeYDL:
    def __init__(self, opts):
        self.opts = opts
    def __enter__(self):
        return self
    def __exit__(self, exc_type, exc, tb):
        return False
    def extract_info(self, url, download=False):
        return {
            'formats': [
                {'format_id': 'low', 'abr': 96},
                {'format_id': 'ok', 'abr': 128},
                {'format_id': 'good', 'abr': 160},
            ]
        }
    def download(self, urls):
        # simulate success
        return


def test_download_rejects_below_min(monkeypatch, tmp_path):
    # Monkeypatch YoutubeDL used within function
    import youspotter.downloader_yt as d
    class ProbeOnly(FakeYDL):
        pass
    monkeypatch.setattr(d, '_get_YoutubeDL', lambda: ProbeOnly)
    cfg = {'host_path': str(tmp_path), 'bitrate': 160, 'format': 'mp3'}
    # Will accept since 160 is available
    ok = download_audio({'url': 'http://x'}, {'artist': 'A', 'title': 'T'}, cfg)
    assert ok is True
    # Require 192 → reject
    cfg2 = {'host_path': str(tmp_path), 'bitrate': 192, 'format': 'mp3'}
    ok2 = download_audio({'url': 'http://x'}, {'artist': 'A', 'title': 'T'}, cfg2)
    assert ok2 is False
