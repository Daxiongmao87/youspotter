# Specification Document

## Title
[x] Feature/Module Name: Catalog-driven download status and queue rebuild

## Overview
[x] Brief description of purpose and scope:  
> Make the persisted catalog the single source of truth for track metadata and download state.  
> Derive counters and queue contents from the catalog + filesystem, not from the transient status snapshot.  
> Track real file paths for downloaded items, detect missing files, and keep the download queue regenerated from catalog state.  

## Requirements
- [x] Functional Requirements:  
  - [x] Req 1: Catalog tables must store the resolved local file path (absolute) for each track when a download succeeds.  
  - [x] Req 2: Application startup and every sync must reconcile catalog entries with the filesystem: mark entries as `downloaded` if the stored file path exists, otherwise `missing`, and schedule retries for failed downloads.  
  - [x] Req 3: Headline counters (Missing/Downloading/Downloaded/Songs/Artists/Albums) must be derived from catalog queries (no separate status totals).  
  - [x] Req 4: Download queue should be rebuilt from catalog entries marked `missing` or with failed retries (respecting retry cooldowns).  
  - [x] Req 5: Failed downloads must record error context, increment retry timestamps, and eventually surface to the queue once cooldown expires.  

- [x] Non-Functional Requirements:  
  - [x] Req 1: Catalog reconciliation must complete within reasonable time for thousands of tracks (batch filesystem checks + caching).  
  - [x] Req 2: Design should support future filesystem event listeners but not depend on them (polling via sync acceptable).  

## Inputs
- [x] Define expected inputs:  
  - Catalog rows (track metadata, stored file path when known).  
  - Filesystem scan results (exists? size?).  
  - Download worker success/failure callbacks.  

## Outputs
- [x] Define expected outputs:  
  - Updated catalog rows with accurate `status`, `local_path`, `last_seen`, `last_error`, `retry_after`.  
  - Derived counters returned via `/status`.  
  - Queue list populated for pending downloads based on catalog gaps.  

## Behaviors / Flows
- [x] Primary flow:  
  1. Sync fetches Spotify tracks → upserts catalog metadata (no status assumptions).  
  2. Download worker succeeds → writes absolute file path + status `downloaded`, clears retry timers.  
  3. Reconciliation step (startup + post-sync) checks catalog rows: if `local_path` missing or file absent → mark `missing`, set retry schedule; if file present → ensure `downloaded`.  
  4. Queue builder selects catalog items with status `missing` (and not on cooldown) and enqueues them; queue state stored for UI.  

- [x] Edge cases:  
  - [x] Case 1: Track has no `local_path` yet (never downloaded) → treat as missing after sync.  
  - [x] Case 2: File renamed externally → reconciliation detects missing file, resets status, queues download.  
  - [x] Case 3: Download failure → store last error + next retry window, exclude until cooldown expires.  

## Examples (Acceptance Cases)
- [x] Example 1: On startup with populated catalog but no files, `/status` shows Missing = total tracks, Downloaded = 0, and queue equals catalog size.  
- [x] Example 2: After downloads succeed, `/status` shows Downloaded count matching catalog files, queue empties.  
- [x] Example 3: User deletes a local file → next sync marks track missing and requeues download.  
- [x] Example 4: Consecutive download failures escalate retry delay but eventually requeue once cooldown passes.  

## Test Cases (for TDD seed)
- [x] Requirement → Test Case(s):  
  - Req 1 → Unit test ensuring `replace_catalog` persists `local_path` and flags.  
  - Req 2 → Integration test simulating missing filesystem files causing status flip + queue rebuild.  
  - Req 3 → `/status` functional test verifying counts derived from catalog.  
  - Req 4 → Queue builder test verifying retry cooldown respected.  

## Planning Addendum (for OOD / Implementation Strategy)
- [x] Components / Modules:  
  - `storage.DB` schema updates (`tracks` table: `local_path`, `status`, `last_error`, `retry_after`).  
  - New reconciliation service or method invoked on startup/post-sync.  
  - Queue builder logic fed from catalog query.  
  - Status endpoint deriving counts via SQL.  

- [x] Classes & Interfaces:  
  - Extend `SyncService` to run reconciliation + queue rebuild.  
  - Download worker to accept success/failure callbacks writing catalog fields.  

- [x] Reuse / DRY considerations:  
  - Deduplicate normalization logic (use `identity_key`).  
  - Share retry schedule implementation (existing JSON schedule can migrate into DB columns).  

- [x] MVP task breakdown:  
  1. Schema migration & data backfill (tracks table).  
  2. Update download worker to store `local_path` and errors in catalog via DB helper.  
  3. Implement reconciliation + queue rebuild pipeline.  4. Adjust `/status`, queue endpoints, and tests.  
  5. Remove deprecated status snapshot reliance once replacement verified.  

### Status
- [x] Specification reviewed  
- [x] Tests derived from spec  
- [x] Implementation complete  
- [x] Verification complete  
