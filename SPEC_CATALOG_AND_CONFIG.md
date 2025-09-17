# Specification Document

## Title
[x] Feature/Module Name: Config persistence, download filter, catalog persistence overhaul

## Overview
[x] Brief description of purpose and scope:  
> Address outstanding config and quality issues, then persist synced tracks/artists/albums to SQLite so the catalog API reads from the database instead of ephemeral status snapshots.  
> Ensure sync/auto-sync updates the database and catalog cache refresh detects changes.

## Requirements
- [x] Functional Requirements:  
  - [x] Req 1: Saving config via `/config` must persist user-specified concurrency; GET must reflect stored value.  
  - [x] Req 2: `download_audio` must abort when no available YouTube bitrate meets requested threshold and surface error in recent log.  
  - [x] Req 3: Sync operations must store tracks, artists, and albums in SQLite tables; catalog endpoints must read from DB and only refresh cache when freshness markers change.  
  - [x] Req 4: `tests/test_sync_service` expectations must align with actual behavior (queue counts, not fabricated download totals).  

- [x] Non-Functional Requirements:  
  - [x] Req 1: DB writes should be batched/transactional to avoid per-track overhead.  
  - [x] Req 2: Schema changes must be backward compatible (migrations for new columns/tables).  
  - [x] Req 3: Catalog cache refresh must avoid repeated heavy Spotify calls; it should detect changes via version/timestamp stored in DB.  

## Inputs
- [x] Define expected inputs:  
  - Config payloads with `concurrency`.  
  - Sync track list from Spotify (existing structure).  
  - YouTube format list via yt-dlp probe.  

## Outputs
- [x] Define expected outputs:  
  - Updated config responses reflecting saved concurrency.  
  - Download attempts aborting with clear log when quality insufficient.  
  - DB tables `tracks`, `artists`, `albums` populated; catalog endpoints returning DB-backed data.  
  - Updated tests verifying new behavior.  

## Behaviors / Flows
- [x] Primary flow:  
  1. User saves config; concurrency persisted/read back.  
  2. Sync runs → normalize tracks → upsert into DB tables inside transaction; update `catalog_version` marker.  
  3. Catalog refresh compares cached version to DB marker; rebuilds in-memory cache only on change using DB queries.  
  4. Download worker probes formats; if no adequate bitrate, log error and return False.  

- [x] Edge cases:  
  - [x] Case 1: Legacy DB lacking new columns → migration adds them without dropping data.  
  - [x] Case 2: Sync yields zero tracks → DB clears stale rows and updates version.  
  - [x] Case 3: Download without bitrate info → treat as failure with diagnostic.  

## Examples (Acceptance Cases)
- [x] Example 1: POST `/config` with `concurrency: 4` → GET returns 4; DB `settings` stores `concurrency=4`.  
- [x] Example 2: Track requires 192 kbps but yt-dlp only offers ≤160 → download returns False, recent log records error.  
- [x] Example 3: After sync, `/catalog/songs` returns DB-backed list even after restarting app (no pending queue).  
- [x] Example 4 (Edge Case): Sync removing tracks results in DB tables reflecting the trimmed set; catalog cache updates accordingly.  

## Test Cases (for TDD seed)
- [x] Requirement → Test Case(s):  
  - Req 1 → Functional test hitting `/config`.  
  - Req 2 → Unit test for download_audio using fake yt-dlp with limited formats.  
  - Req 3 → Integration test: seed DB with sync data, ensure catalog endpoints read from DB and respect versioning.  
  - Req 4 → Update sync_service test to assert queue length, not downloaded count.  

## Planning Addendum (for OOD / Implementation Strategy)
- [x] Components / Modules:  
  - `config.py`, `/config` routes.  
  - `downloader_yt.py`.  
  - `sync_service.py`, `storage.py`, catalog helpers in `__init__.py`.  
  - Database schema migrations and query helpers.  

- [x] Classes & Interfaces:  
  - Extend `DB` with helpers for tracks/artists/albums (bulk upsert, version marker).  
  - `SyncService` to call persistence helper after dedupe.  
  - Catalog refresh to query DB via new helper.  

- [x] Reuse / DRY considerations:  
  - Reuse normalization utilities (`normalize_text`).  
  - Centralize identity key for DB storage.  

- [x] MVP task breakdown:  
  1. Config & download fixes with tests.  
  2. Design/implement DB schema migrations and helpers.  
  3. Wire sync pipeline to update DB, adjust catalog refresh, add tests.  
  4. Update existing tests for new behavior.  

### Status
- [ ] Specification reviewed  
- [x] Tests derived from spec  
- [ ] Implementation complete  
- [ ] Verification complete  
