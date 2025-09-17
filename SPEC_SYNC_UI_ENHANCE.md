# Specification Document

## Title
[x] Feature/Module Name: Sync notifications, scheduler timing, catalog loading UX

## Overview
[x] Brief description of purpose and scope:  
> Provide actionable sync status feedback, ensure autosync cadence waits for completion, and improve catalog UI state handling.  

## Requirements
- [x] Functional Requirements:  
  - [x] Req 1: When a sync starts (manual or scheduled), add a recent-activity entry indicating the start time/trigger.  
  - [x] Req 2: Scheduler must schedule the next run only after the prior sync completes; `next_run_at` should reflect completion + interval.  
  - [x] Req 3: Catalog grid should display a loading indicator while data is fetching and avoid showing “No items found” until load completes; UI should handle populated stats vs. empty grid gracefully.  

- [x] Non-Functional Requirements:  
  - [x] Req 1: Logging must remain thread-safe and avoid duplicate entries for the same start event.  
  - [x] Req 2: UI changes must retain responsiveness and accessibility (aria-live status for loading).  

## Inputs
- [x] Define expected inputs:  
  - Sync start triggers (`sync_now`, scheduler loop).  
  - UI fetch promises for `/catalog/*`.  

## Outputs
- [x] Define expected outputs:  
  - Recent log entry “Sync starting…” with level INFO.  
  - Scheduler `next_run_at` timestamp reflecting interval after completion.  
  - Catalog section shows spinner during fetch, hides empty-state message until data known.  

## Behaviors / Flows
- [x] Primary flow:  
  1. Sync invoked → log “Sync starting” → process tracks → update queue/catalog as today.  
  2. Scheduler loop runs: run sync, update `next_run_at = now + interval`, wait for interval.  
  3. Catalog tab load: set loading state, fetch API, on success hide spinner/show results or “No items” message.  

- [x] Edge cases:  
  - [x] Case 1: Concurrent manual + scheduled sync — log message only when sync actually starts (after lock acquired).  
  - [x] Case 2: Catalog fetch fails — show error message instead of stuck spinner.  

## Examples (Acceptance Cases)
- [x] Example 1: User clicks “Sync Now” → recent log shows `[HH:MM:SS] INFO: Sync starting (manual)` before completion entry.  
- [x] Example 2: Scheduler set to 15 min; sync takes 2 min → next sync occurs 15 min after completion (17 min after prior start).  
- [x] Example 3: Catalog API slow → UI shows spinner with “Loading catalog…”; once loaded, data appears, otherwise “No items found” only after load completes and data empty.  

## Test Cases (for TDD seed)
- [x] Requirement → Test Case(s):  
  - Req 1 → Unit test ensuring `add_recent` called with “Sync starting” when `sync_spotify_tracks` acquires lock.  
  - Req 2 → Scheduler test mocking `run_once` duration, verifying `next_run_at` set to completion time + interval.  
  - Req 3 → Front-end integration (js) manual verification; add jest? Not available: ensure DOM updates via unit snippet or manual instructions.  

## Planning Addendum (for OOD / Implementation Strategy)
- [x] Components / Modules:  
  - `SyncService` for logging + scheduler adjustments.  
  - Front-end JS (`static/app.js`) & template for loading spinner.  

- [x] Classes & Interfaces:  
  - Extend scheduler loop with completion timestamp.  
  - Introduce JS state flags for catalog loading.  

- [x] Reuse / DRY considerations:  
  - Reuse `add_recent` helper; centralize message format.  

- [x] MVP task breakdown:  
  1. Add sync-start logging (manual & scheduler).  
  2. Adjust scheduler loop & `next_run_at`.  
  3. Update template + JS for spinner/no-data state.  
  4. Add/adjust tests for sync logging & scheduler.  

### Status
- [x] Specification reviewed  
- [x] Tests derived from spec  
- [x] Implementation complete  
- [x] Verification complete  
