from typing import List, Dict
from ytmusicapi import YTMusic
from .logging import get_logger, with_context


class YouTubeMusicClient:
    def __init__(self):
        # YTMusic can work without headers for search
        self.yt = YTMusic()
        self.logger = get_logger(__name__)

    def search_song(self, track: Dict) -> List[Dict]:
        query = f"{track['artist']} {track['title']}"
        try:
            results = self.yt.search(query, filter="songs")
        except Exception as e:
            with_context(self.logger, attempt=1)[0].error(f"ytmusic search failed: {e}")
            return []
        candidates = []
        for r in results:
            dur_str = r.get("duration") or "0:00"
            dur = 0
            try:
                parts = [int(x) for x in dur_str.split(":")]
                if len(parts) == 2:
                    dur = parts[0] * 60 + parts[1]
                elif len(parts) == 3:
                    dur = parts[0] * 3600 + parts[1] * 60 + parts[2]
            except Exception:
                dur = 0
            # Extract thumbnail URL (get highest quality available)
            thumbnail_url = None
            thumbnails = r.get("thumbnails", [])
            if thumbnails:
                # Get the highest quality thumbnail (last in array)
                thumbnail_url = thumbnails[-1].get("url")

            candidates.append({
                "artist": (r.get("artists") or [{}])[0].get("name", ""),
                "title": r.get("title", ""),
                "duration": dur,
                "channel": r.get("author", ""),
                "url": f"https://www.youtube.com/watch?v={r.get('videoId','')}",
                "thumbnail": thumbnail_url
            })
        return candidates
