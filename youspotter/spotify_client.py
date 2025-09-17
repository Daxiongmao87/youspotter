import base64
import hashlib
import os
import secrets
import threading
import time
from urllib.parse import urlencode
from typing import List, Dict, Optional

import requests
from .logging import get_logger, with_context

from .storage import DB, TokenStore


AUTH_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
SCOPE = "playlist-read-private playlist-read-collaborative"


class SpotifyClient:
    def __init__(self, db: DB):
        self.db = db
        self.token_store = TokenStore(db)
        self.logger = get_logger(__name__)
        self._refresh_lock = threading.Lock()
        self._last_refresh_time = 0

    def _client_id(self) -> str:
        # Prefer configured client_id, else env, else empty (requires user to set)
        return self.db.get_setting('spotify_client_id') or os.environ.get('SPOTIFY_CLIENT_ID', '')

    def begin_pkce(self) -> Dict[str, str]:
        verifier = base64.urlsafe_b64encode(os.urandom(64)).decode('utf-8').rstrip('=')
        challenge = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode('utf-8')).digest()
        ).decode('utf-8').rstrip('=')
        state = secrets.token_urlsafe(16)
        self.db.set_setting('spotify_pkce_verifier', verifier)
        self.db.set_setting('spotify_pkce_state', state)
        return {"verifier": verifier, "challenge": challenge, "state": state}

    def get_auth_url(self, redirect_uri: str, client_id: Optional[str] = None) -> str:
        client_id = client_id or self._client_id()
        data = self.begin_pkce()
        params = {
            "client_id": client_id,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "scope": SCOPE,
            "code_challenge_method": "S256",
            "code_challenge": data["challenge"],
            "state": data["state"],
            "show_dialog": "false",
        }
        return f"{AUTH_URL}?{urlencode(params)}"

    def handle_callback(self, code: str, state: str, redirect_uri: str, client_id: Optional[str] = None):
        client_id = client_id or self._client_id()
        expected_state = self.db.get_setting('spotify_pkce_state') or ''
        if not expected_state or state != expected_state:
            raise ValueError("invalid_state")
        verifier = self.db.get_setting('spotify_pkce_verifier') or ''
        if not verifier:
            raise ValueError("missing_verifier")

        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": client_id,
            "code_verifier": verifier,
        }
        headers = {
            "Content-Type": "application/x-www-form-urlencoded"
        }
        log, cid = with_context(self.logger, attempt=1)
        resp = requests.post(TOKEN_URL, data=data, headers=headers, timeout=15)
        try:
            resp.raise_for_status()
        except Exception as e:
            # Include response body to diagnose (e.g., invalid_grant, redirect_uri_mismatch)
            try:
                log.error(f"spotify token exchange failed: {e}; status={resp.status_code}; body={resp.text}")
            except Exception:
                log.error(f"spotify token exchange failed: {e}")
            raise
        token_info = resp.json()
        access_token = token_info.get("access_token")
        refresh_token = token_info.get("refresh_token")
        if not access_token or not refresh_token:
            raise ValueError("token_exchange_failed")
        self.token_store.save(access_token, refresh_token)
        # Clean one-time values
        self.db.set_setting('spotify_pkce_verifier', '')
        self.db.set_setting('spotify_pkce_state', '')

    def refresh_access_token(self, client_id: Optional[str] = None) -> str:
        with self._refresh_lock:
            # Check if another thread just refreshed the token
            current_time = time.time()
            if current_time - self._last_refresh_time < 5:  # 5 second cooldown
                at, _ = self.token_store.load()
                if at:
                    return at

            client_id = client_id or self._client_id()
            at, rt = self.token_store.load()
            if not rt:
                raise RuntimeError("not_authenticated")
            data = {
                "grant_type": "refresh_token",
                "refresh_token": rt,
                "client_id": client_id,
            }
            headers = {
                "Content-Type": "application/x-www-form-urlencoded"
            }
            log, cid = with_context(self.logger, attempt=1)
            resp = requests.post(TOKEN_URL, data=data, headers=headers, timeout=15)

            # Handle all HTTP errors and convert to RuntimeError for consistent handling
            if not resp.ok:
                try:
                    log.error(f"spotify refresh failed: {resp.status_code}; body={resp.text}")
                    # Check if refresh token was revoked
                    if resp.status_code == 400:
                        try:
                            error_data = resp.json()
                            if error_data.get("error") == "invalid_grant":
                                log.info("refresh token revoked, clearing stored tokens")
                                self.token_store.clear()
                                raise RuntimeError("refresh_token_revoked")
                        except (ValueError, KeyError):
                            pass
                except Exception:
                    log.error(f"spotify refresh failed: HTTP {resp.status_code}")

                # Convert any HTTP error to RuntimeError for consistent handling
                raise RuntimeError(f"spotify_refresh_failed_http_{resp.status_code}")
            token_info = resp.json()
            access_token = token_info.get("access_token")
            if access_token:
                self.token_store.save(access_token, token_info.get("refresh_token", rt))
                self._last_refresh_time = current_time
                return access_token
            raise RuntimeError("refresh_failed")

    # Data fetching methods remain same signature used by SyncService
    def current_user_playlists(self) -> List[Dict]:
        at, _ = self.token_store.load()
        if not at:
            raise RuntimeError("not_authenticated")
        headers = {"Authorization": f"Bearer {at}"}
        url = "https://api.spotify.com/v1/me/playlists?limit=50"
        items: List[Dict] = []
        while url:
            try:
                r = requests.get(url, headers=headers, timeout=15)
            except Exception as e:
                with_context(self.logger, attempt=1)[0].error(f"spotify playlists request error: {e}")
                raise
            if r.status_code == 401:
                try:
                    at = self.refresh_access_token()
                    headers = {"Authorization": f"Bearer {at}"}
                    r = requests.get(url, headers=headers, timeout=15)
                except RuntimeError as re:
                    error_str = str(re)
                    if error_str in ("refresh_token_revoked", "not_authenticated") or error_str.startswith("spotify_refresh_failed_http_"):
                        raise re  # Re-raise for higher level handling
                    else:
                        raise
            if r.status_code == 429:
                retry_after = int(r.headers.get('Retry-After', 60))
                with_context(self.logger, attempt=1)[0].warning(f"Spotify playlists rate limited, retry in {retry_after} seconds")
                raise RuntimeError(f"rate_limited:{retry_after}")
            r.raise_for_status()
            data = r.json()
            for p in data.get("items", []):
                items.append({"id": p.get("id"), "name": p.get("name"), "tracks": p.get("tracks", {}).get("total", 0)})
            url = data.get("next")
        return items

    def playlist_tracks(self, playlist_id: str) -> List[Dict]:
        at, _ = self.token_store.load()
        if not at:
            raise RuntimeError("not_authenticated")
        headers = {"Authorization": f"Bearer {at}"}
        url = f"https://api.spotify.com/v1/playlists/{playlist_id}/tracks?additional_types=track&limit=100"
        items: List[Dict] = []
        while url:
            try:
                r = requests.get(url, headers=headers, timeout=15)
            except Exception as e:
                with_context(self.logger, attempt=1)[0].error(f"spotify playlist items error: {e}")
                raise
            if r.status_code == 401:
                try:
                    at = self.refresh_access_token()
                    headers = {"Authorization": f"Bearer {at}"}
                    r = requests.get(url, headers=headers, timeout=15)
                except RuntimeError as re:
                    error_str = str(re)
                    if error_str in ("refresh_token_revoked", "not_authenticated") or error_str.startswith("spotify_refresh_failed_http_"):
                        raise re  # Re-raise for higher level handling
                    else:
                        raise
            if r.status_code == 429:
                # Rate limited - check Retry-After header
                retry_after = int(r.headers.get('Retry-After', 60))
                with_context(self.logger, attempt=1)[0].warning(f"Spotify rate limited, waiting {retry_after} seconds")
                time.sleep(retry_after)
                continue
            r.raise_for_status()
            data = r.json()
            for it in data.get("items", []):
                tr = (it or {}).get("track") or {}
                if not tr or tr.get("is_local"):
                    continue
                artist_obj = (tr.get("artists") or [{}])[0]
                artist = artist_obj.get("name", "")
                artist_id = artist_obj.get("id", "")
                album_obj = (tr.get("album") or {})
                album = album_obj.get("name", "")
                album_id = album_obj.get("id", "")
                title = tr.get("name", "")
                duration_ms = tr.get("duration_ms", 0)
                items.append({
                    "artist": artist,
                    "artist_id": artist_id,
                    "album": album,
                    "album_id": album_id,
                    "title": title,
                    "duration": int((duration_ms or 0) // 1000)
                })
            url = data.get("next")
        return items

    def artist_all_tracks(self, artist_id: str) -> List[Dict]:
        at, _ = self.token_store.load()
        if not at:
            raise RuntimeError("not_authenticated")
        headers = {"Authorization": f"Bearer {at}"}
        # Get albums, then tracks
        items: List[Dict] = []
        url = f"https://api.spotify.com/v1/artists/{artist_id}/albums?include_groups=album,single&limit=50"
        albums = []
        while url:
            r = requests.get(url, headers=headers, timeout=15)
            if r.status_code == 401:
                try:
                    at = self.refresh_access_token()
                    headers = {"Authorization": f"Bearer {at}"}
                    r = requests.get(url, headers=headers, timeout=15)
                except RuntimeError as re:
                    error_str = str(re)
                    if error_str in ("refresh_token_revoked", "not_authenticated") or error_str.startswith("spotify_refresh_failed_http_"):
                        raise re  # Re-raise for higher level handling
                    else:
                        raise
            r.raise_for_status()
            data = r.json()
            albums.extend([a.get('id') for a in data.get('items', []) if a.get('id')])
            url = data.get('next')
        for aid in albums:
            items.extend(self.album_tracks(aid))
        return items

    def album_tracks(self, album_id: str) -> List[Dict]:
        at, _ = self.token_store.load()
        if not at:
            raise RuntimeError("not_authenticated")
        headers = {"Authorization": f"Bearer {at}"}
        url = f"https://api.spotify.com/v1/albums/{album_id}/tracks?limit=50"
        out: List[Dict] = []
        album_name = None
        # fetch album name
        r0 = requests.get(f"https://api.spotify.com/v1/albums/{album_id}", headers=headers, timeout=15)
        if r0.status_code == 401:
            try:
                at = self.refresh_access_token()
                headers = {"Authorization": f"Bearer {at}"}
                r0 = requests.get(f"https://api.spotify.com/v1/albums/{album_id}", headers=headers, timeout=15)
            except RuntimeError as re:
                if str(re) in ("refresh_token_revoked", "not_authenticated"):
                    raise re  # Re-raise for higher level handling
                else:
                    raise
        if r0.ok:
            album_name = (r0.json() or {}).get('name')
        while url:
            r = requests.get(url, headers=headers, timeout=15)
            if r.status_code == 401:
                try:
                    at = self.refresh_access_token()
                    headers = {"Authorization": f"Bearer {at}"}
                    r = requests.get(url, headers=headers, timeout=15)
                except RuntimeError as re:
                    error_str = str(re)
                    if error_str in ("refresh_token_revoked", "not_authenticated") or error_str.startswith("spotify_refresh_failed_http_"):
                        raise re  # Re-raise for higher level handling
                    else:
                        raise
            r.raise_for_status()
            data = r.json()
            for tr in data.get('items', []):
                artist_obj = (tr.get("artists") or [{}])[0]
                out.append({
                    "artist": artist_obj.get('name',''),
                    "artist_id": artist_obj.get('id',''),
                    "album": album_name or '',
                    "album_id": album_id,
                    "title": tr.get('name',''),
                    "duration": int((tr.get('duration_ms',0) or 0)//1000)
                })
            url = data.get('next')
        return out
