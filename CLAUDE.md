# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

YouSpotter is a Python Flask web application that automatically downloads music from YouTube based on Spotify playlists. It uses Spotify OAuth (PKCE), YouTube Music API (ytmusicapi), and yt-dlp for downloading. The application runs continuously with a 15-minute sync scheduler to monitor playlist changes.

## Core Architecture

### Application Structure
- **Frontend**: Single-page HTML/JavaScript interface with real-time status polling
- **Backend**: Flask app with SQLite database and background worker threads
- **Authentication**: Spotify OAuth with Authorization Code + PKCE (no client secret)
- **Music Services**:
  - `SpotifyClient` - playlist access and track metadata
  - `YouTubeMusicClient` - search and metadata via ytmusicapi
  - Download via yt-dlp with concurrent queue management
- **Sync Engine**: `SyncService` - 15-minute scheduler with manual sync capability

### Key Components
- `app.py` - Main application entry point and service initialization
- `youspotter/__init__.py` - Flask app factory with API endpoints
- `youspotter/web.py` - Web UI blueprint with auth callback handling
- `youspotter/sync_service.py` - Background sync scheduler and download orchestration
- `youspotter/storage.py` - SQLite database layer and token management
- `youspotter/status.py` - Real-time status tracking with queue management
- `youspotter/spotify_client.py` - Spotify API integration with PKCE auth
- `youspotter/youtube_client.py` - YouTube Music search and metadata
- `youspotter/downloader_yt.py` - yt-dlp download wrapper with error handling

### Database Schema
SQLite database stores:
- User settings (host path, bitrate, format, selected playlists)
- Spotify OAuth tokens (access/refresh)
- Download queue state and retry schedules
- Metadata cache for UI performance

## Development Commands

### Running the Application
```bash
# Activate virtual environment
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run locally (default port 5000)
python app.py

# Run on custom port
PORT=8080 python app.py

# Run with custom database path
YOUSPOTTER_DB=/path/to/db.sqlite python app.py
```

### Testing and Quality
```bash
# Run tests
make test
# or: pytest

# Run linting
make lint
# or: ruff check .

# Check code formatting
make format-check
# or: black --check .
```

### Docker Development
```bash
# Build and run with docker-compose
docker-compose up --build

# Access at http://localhost:5000
# Data persists in ./data/ and ./downloads/
```

## Configuration and Authentication

### Spotify Setup
1. Create Spotify app at https://developer.spotify.com/dashboard
2. Add redirect URI: `http://localhost:5000/auth/callback` (adjust host/port as needed)
3. Note the Client ID (no client secret needed for PKCE)
4. Configure Client ID in the app settings

### Directory Structure
```
youspotter/
├── config.py           # Settings validation and management
├── storage.py          # Database and token storage
├── spotify_client.py   # Spotify API + OAuth PKCE
├── youtube_client.py   # YouTube Music search
├── sync_service.py     # Background sync scheduler
├── downloader_yt.py    # yt-dlp wrapper
├── status.py           # Queue and status tracking
├── web.py              # Web UI blueprint
├── utils/              # Helper utilities
│   ├── matching.py     # Song matching algorithms
│   ├── backoff.py      # Retry logic with exponential backoff
│   ├── path_template.py # File naming templates
│   └── download_counter.py # File system metrics
└── templates/
    └── index.html      # Single-page web interface
```

## Key Technical Details

### Authentication Flow
- Uses Authorization Code + PKCE for enhanced security
- No client secret stored (PKCE eliminates need)
- Automatic token refresh with fallback to re-authentication
- Tokens stored securely in SQLite with proper error handling

### Download Strategy
- Song-only matching (exact track matches from playlists)
- Quality filtering with configurable bitrate thresholds
- Deduplication based on normalized artist|title|duration
- Exponential backoff retry logic (2s base, 60s max, 3 attempts)
- File organization: `{artist}/{album}/{artist} - {title}.{ext}`

### Concurrency and Threading
- Background sync scheduler (15-minute intervals when configured)
- Concurrent download worker with configurable limits (default: 3)
- Thread-safe status tracking with lock-free live updates
- Graceful shutdown and cleanup of stale download states

### Status and Queue Management
- Three-tier queue: pending → current → completed
- Real-time status polling endpoints for UI updates
- Persistent queue state across application restarts
- Manual sync capability with overlap prevention

## Development Tips

### Database Management
- SQLite database auto-creates on first run
- Use `storage.DB` class for all database operations
- Settings stored as key-value pairs in `settings` table
- Token storage handled by `TokenStore` class with encryption

### Error Handling Patterns
- Errors always log unconditionally (never silenced)
- Structured logging with correlation IDs for tracking
- Graceful degradation when services unavailable
- User-friendly error messages in API responses

### Testing Considerations
- Mock Spotify and YouTube APIs for unit tests
- Test auth flow with invalid/expired tokens
- Verify queue state persistence across restarts
- Test concurrent download limits and error scenarios

### Environment Variables
- `PORT` - HTTP server port (default: 5000)
- `YOUSPOTTER_DB` - Database file path (default: ./youspotter.db)
- `TZ` - Timezone for Docker containers

## API Endpoints

### Core Endpoints
- `GET /status` - Application status and download counters
- `GET /queue` - Paginated download queue with filtering
- `POST /sync-now` - Trigger immediate sync (respects concurrency locks)
- `GET /config` / `POST /config` - User settings management
- `GET /auth/status` - Authentication status check

### Utility Endpoints
- `POST /reset-errors` - Clear retry schedules and requeue failed items
- `POST /pause-downloads` / `POST /resume-downloads` - Download control
- `POST /reset-queue` - Clean up stale queue items
- `GET /catalog/<mode>` - Browse songs/artists/albums with metadata

## Legal and Compliance

The application includes mandatory legal disclaimers about YouTube Terms of Service compliance and copyright responsibilities. Users must acknowledge these before use.