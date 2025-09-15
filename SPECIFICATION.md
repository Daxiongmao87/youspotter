# Specification Document

## Title
**Feature/Module Name:** YouSpotter - Automated Spotify-to-YouTube Music Downloader

## Overview
**Brief description of purpose and scope:**
> YouSpotter is a simple, straightforward automated Spotify music downloader with a web frontend for configuring Spotify and YouTube sync. Users authenticate with Spotify, select playlists with granular download options (song-only, all artist's songs, all album's songs, or all), configure settings, and the system automatically syncs every 15 minutes to download new tracks from YouTube Music with full metadata preservation.

## Requirements

### Functional Requirements:
- [x] **FR1:** Spotify OAuth (Authorization Code with PKCE, no client secret) for playlist access
- [x] **FR2:** YouTube Music search and download via ytmusicapi + yt-dlp
- [x] **FR3:** Web interface for configuration and monitoring
- [x] **FR4:** Playlist selection with per‑playlist strategy options:
  - song-only (exact track matches)
  - all-artist-songs (full discographies for artists found in the playlist)
  - all-album-songs (full albums containing any playlist tracks)
  - all (union of artist + album expansions with dedup)
- [x] **FR5:** Configurable audio quality (default: 128kbps) and format (default: MP3)
- [x] **FR6:** Configurable concurrent downloads (default: 3 simultaneous)
- [x] **FR7:** Automatic 15-minute sync interval for playlist updates
- [x] **FR8:** Download status tracking (missing, downloading, downloaded)
- [x] **FR9:** Metadata preservation including album art from music.youtube.com
- [x] **FR10:** User-specified host folder path for downloads
- [x] **FR11:** Re-authentication and playlist reconfiguration capability
- [x] **FR12:** Quality filtering - reject downloads below specified bitrate

### Non-Functional Requirements:
- [x] **NFR1:** Performance - Handle typical small playlists reliably; correctness over throughput
- [x] **NFR2:** Reliability - Resume interrupted downloads automatically
- [x] **NFR3:** Security - Secure token storage and API key management
- [x] **NFR4:** Usability - Intuitive web interface with real-time status updates
- [x] **NFR5:** Compliance - Include TOS warnings and legal disclaimers

## Inputs

### User Authentication
- **Field:** Spotify OAuth Tokens
- **Type:** Access/Refresh tokens (opaque strings)
- **Constraints:** Valid, non-expired Spotify access token with refresh token; refreshed automatically server-side

- **Field:** Spotify Client ID (required)
- **Type:** String
- **Constraints:** User supplies their own Client ID and registers the redirect URI shown in the UI (e.g., `http://<host>:<port>/auth/callback`) in the Spotify dashboard. No client secret required (PKCE).

#### Security Storage (MVP)
- Access and refresh tokens are stored at rest using OS keyring (preferred) or encrypted/DB fallback with file permissions locked to the service user.
- No client secret is required or stored (PKCE).
- Tokens are never logged. Secrets may be provided via environment variables or a config file excluded from logs/exports (advanced custom Client ID only).
- Refresh policy follows Spotify guidelines; rotation happens automatically; failures trigger re-authentication flow.

### Playlist Configuration
- **Field:** Selected Playlists
- **Type:** Array of Playlist Objects
- **Constraints:** User-owned or followed Spotify playlists (all unchecked by default)

- **Field:** Download Strategy Per Playlist
- **Type:** Enum ["song-only", "all-artist-songs", "all-album-songs", "all"]
- **Constraints:** One selection required per selected playlist

### Download Settings
- **Field:** Host Folder Path
- **Type:** String (file system path)
- **Constraints:** Valid, writable directory path on host system

- **Field:** Audio Bitrate
- **Type:** Integer
- **Constraints:** User selectable (default: 192kbps)

- **Field:** Audio Format
- **Type:** String
- **Constraints:** User selectable (default: "mp3")

- **Field:** Concurrent Downloads
- **Type:** Integer
- **Constraints:** User configurable (default: 3)

## Outputs

### Download Files
- **Field:** Audio Files
- **Type:** Binary audio files with embedded metadata
- **Rules:** Named with artist/title, includes album art from YouTube Music
 - **Filesystem Safety (MVP):** Sanitize filenames/paths cross-platform (strip/replace invalid characters, normalize whitespace). Resolve collisions by appending a short disambiguator (e.g., track ID). Folder structure: `Artist/Album/Artist - Title.ext`.

### Status Information
- **Field:** Download Status
- **Type:** Object containing real-time status
- **Rules:** Shows missing, downloading, downloaded states

### System Logs
- **Field:** Operation Logs
- **Type:** Structured log entries
- **Rules:** Includes timestamps, search results, download outcomes
 - **Diagnostics Policy (MVP):** Errors/warnings always log unconditionally; info/debug behind a single debug flag. Errors include correlation ID, component, attempt/retry count, and root cause. No hidden toggles for errors.

## Behaviors / Flows

### Primary Flow:
1. **User Authentication (PKCE)**
   - User accesses web application
   - System redirects to Spotify OAuth with Authorization Code + PKCE
   - User grants playlist access permissions
   - System stores access/refresh tokens securely

2. **Playlist Configuration & Spotify Auth (PKCE)**
   - System fetches user's Spotify playlists
   - All playlists shown unchecked/disabled by default
   - User selects desired playlists
   - User chooses download strategy for each selected playlist
   - User configures host folder path, bitrate, format, concurrent downloads
   - User clicks "Authenticate with Spotify" to begin OAuth Authorization Code with PKCE
   - Frontend generates `code_verifier` and `code_challenge` (S256), sets `state`, and redirects to Spotify authorize with the default/bundled Client ID (localhost) or optional custom Client ID
   - Backend handles callback: validates `state`, exchanges `code` + `code_verifier` for access/refresh tokens, persists tokens securely, and enables scheduler refresh

3. **Initial Sync**
   - System catalogs all tracks from selected playlists
   - For "all-artist-songs": catalogs complete artist discographies of artists from selected playlists
   - For "all-album-songs": catalogs complete albums containing any selected playlist tracks
   - For "all": union of the above with deduplication
   - System searches YouTube Music for matches using ytmusicapi
   - System queues downloads that meet quality requirements
   - Downloads begin with configured concurrency limit

4. **Continuous Monitoring**
   - Every 15 minutes, system checks for playlist updates on Spotify
   - New tracks are cataloged and queued for download
   - Missing songs are searched again
   - Failed downloads are retried
   - Retries & Backoff (MVP): Exponential backoff with jitter; default max attempts: 3 per sync cycle, then mark as "missing" and retry on next schedule; backoff base 2s, max 60s.

5. **Manual Sync & Overlap Lock (MVP)**
   - User can trigger a "Sync Now" action from the UI
   - A lock prevents overlap with the 15-minute scheduler; concurrent sync attempts queue or no-op with a status message

### Edge Cases:
- [x] **Case 1:** Track not found on YouTube Music - Log as missing, retry in next sync
- [x] **Case 2:** Download quality below threshold - Reject and log reason
- [x] **Case 3:** Spotify token expires - Prompt user for re-authentication
- [x] **Case 4:** Network connectivity issues - Pause downloads, resume when available
- [x] **Case 5:** Insufficient disk space - Pause downloads, alert user
- [x] **Case 6:** YouTube Music rate limiting - Implement backoff and retry

### Matching Criteria (MVP: Song-only)
- Exact match: normalized primary artist name and track title must match; album name, when present, improves score but is not mandatory.
- Normalization: case-insensitive; remove punctuation/diacritics; ignore common featuring patterns ("feat.", "ft."); trim and collapse whitespace.
- Duration tolerance: ±5 seconds between Spotify track length and YouTube result.
- Source preference: prefer official music tracks from `music.youtube.com` or official artist channels; otherwise the top-ranked result meeting criteria.
- Locale/region: prefer global/English metadata when multiple variants exist; allow fallback if criteria met.

### Deduplication Policy (MVP)
- Track identity key: normalized `artist|title|duration_bucket` (e.g., 5-second bucket) or a stable hash.
- Skip enqueueing duplicates based on identity key across repeated playlist entries or duplicate search results; first-seen source wins.
- On disk, filename collisions are disambiguated per Filesystem Safety without duplicate logical entries in the database.

## Examples (Acceptance Cases)

### Example 1 - Song-Only Download:
**Input:** Playlist with "Bohemian Rhapsody by Queen", strategy="song-only"
**Output:** Single file "Queen - Bohemian Rhapsody.mp3" with correct metadata and album art

### Example 2 - Quality Filtering:
**Input:** Track search returns only 96kbps version, user requires 128kbps minimum
**Output:** Track marked as "missing" in status, no download performed

### Example 3 - 15-Minute Sync:
**Input:** User adds new song to monitored Spotify playlist
**Output:** Within 15 minutes, new song detected, searched, and downloaded automatically

## Test Cases (for TDD seed)

### Authentication Tests:
- **FR1 (PKCE) → Test:** Authorize URL builder includes S256 `code_challenge`, `state`, and correct `client_id` (default or custom)
- **FR1 (PKCE) → Test:** Callback handler exchanges `code` with `code_verifier`, persists access/refresh tokens
- **FR1 → Test:** Invalid/expired token triggers refresh; if refresh fails, UI prompts re-authentication
- **FR11 → Test:** User can re-authenticate and update playlist selections

### Download Strategy Tests:
- **FR4 → Test:** Song-only downloads exact matches only
- **FR4 → Test:** All-artist-songs catalogs and downloads discography tracks
- **FR4 → Test:** All-album-songs catalogs and downloads full album tracks
- **FR4 → Test:** "All" option combines both expansions with dedup
- **Matching Criteria → Test:** Normalization handles case, punctuation, and "feat." variations; duration tolerance respected; prefers official sources
- **Deduplication → Test:** Duplicate results are not enqueued or downloaded twice

### Quality Control Tests:
- **FR5 → Test:** User can configure bitrate and format settings
- **FR14 → Test:** Downloads reject files below specified bitrate
- **FR8 → Test:** Status accurately reflects missing vs downloaded states

### Sync Process Tests:
- **FR7 → Test:** 15-minute sync detects new playlist additions
- **NFR2 → Test:** Interrupted downloads resume automatically
- **Manual Sync → Test:** "Sync Now" triggers immediate sync and does not overlap with scheduled sync (lock enforced)
- **Retries & Backoff → Test:** After failures, attempts follow exponential backoff with configured max attempts, then mark as missing until next schedule
- **Concurrency Cap → Test:** User-configured concurrency above cap is limited; active downloads never exceed cap
- **Status Endpoint → Test:** Polling the status endpoint returns consistent, current states without duplication

## UI/UX Design

### Main Interface Layout:
- **Main Page:** Single view showing basic download status (missing, downloading, downloaded) and recent activity

### Configuration Interface:
- **Config Sidebar:** Collapsible sidebar panel that slides out from the side
- **Config Sections:**
  - Spotify re-authentication button
  - Playlist selection with checkboxes (all unchecked by default)
  - Download strategy selection per playlist (song-only only)
  - Host folder path input
  - Audio quality settings (bitrate, format)
  - Concurrent download count setting
- **Apply Button:** Saves all configuration changes and triggers sync process

### Navigation Flow:
1. User clicks config button/icon to open sidebar
2. User modifies settings in sidebar panels
3. User clicks Apply to save changes
4. Sidebar closes, main view shows updated status
5. User can view current status at any time

## Planning Addendum (for OOD / Implementation Strategy)

### Components / Modules:
- **Frontend:** Simple HTML/JavaScript with periodic status polling
- **Backend API:** Flask with background task scheduling
- **Authentication Service:** Spotify OAuth handler with token refresh
- **Music Service:** ytmusicapi wrapper for YouTube Music searches
- **Download Manager:** yt-dlp integration with concurrent queue management
- **Database Layer:** SQLite for tracking songs, status, and user preferences
- **Sync Service:** 15-minute scheduler for playlist monitoring

### Classes & Interfaces:
- **SpotifyClient:** OAuth and playlist API interactions
- **YouTubeMusicClient:** Search and metadata retrieval via ytmusicapi
- **DownloadManager:** Concurrent queue management and yt-dlp orchestration
- **SyncService:** Periodic playlist monitoring and catalog updates
- **StatusTracker:** Real-time status updates for web interface

### Reuse / DRY considerations:
- **Shared Models:** Track, Playlist, DownloadStatus objects
- **Common Utilities:** Metadata extraction, file naming, quality validation
- **Configuration Management:** Centralized user settings and preferences

### MVP task breakdown:
1. **Setup Flask project with SQLite database**
2. **Implement Spotify OAuth and playlist fetching**
3. **Create web interface for playlist selection and configuration**
4. **Integrate ytmusicapi for YouTube Music searches**
5. **Implement yt-dlp download functionality with concurrency**
6. **Add basic status tracking (polling)**
7. **Implement 15-minute sync scheduler**
   - Add overlap lock and manual "Sync Now" trigger
8. **Add comprehensive error handling and retry mechanisms**
9. **Include legal disclaimers and TOS warnings**
10. **Test all download strategies and edge cases**

### Legal and Compliance Considerations:
- **Disclaimer:** This application may violate YouTube's Terms of Service
- **User Responsibility:** Users assume full legal responsibility for downloads
- **Copyright Notice:** Downloading copyrighted material without permission is illegal
- **Recommendation:** Use only for personal use and content you own or have rights to

### Technical Architecture Decisions:
- **ytmusicapi + yt-dlp hybrid:** Leverage ytmusicapi for search/metadata, yt-dlp for downloads
- **Database Choice:** SQLite for simplicity and data integrity
- **Concurrency:** Thread-based download management with configurable limits
- **Status Updates:** Simple HTTP polling endpoint for current status
- **Sync Concurrency Guardrail (MVP):** Enforce a hard cap on concurrent downloads (e.g., max 10) regardless of user configuration
- **File Organization:** Artist/Album folder structure with consistent naming
- **Sync Scheduling:** Background thread with 15-minute intervals

### Status
- [x] Specification matches exact user requirements
- [ ] Tests derived from spec requirements
- [ ] Implementation strategy confirmed
- [ ] Verification plan established
