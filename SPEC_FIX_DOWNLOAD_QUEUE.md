# Specification Document

## Title
[x] Feature/Module Name: Restore download queue population on startup

## Overview
[x] Brief description of purpose and scope:  
> Ensure the background download worker sees pending items when a persisted queue exists.  
> Fix startup sequence so items saved in `status_snapshot` are loaded into the live queue used by the worker.  

## Requirements
- [x] Functional Requirements:  
  - [x] Req 1: On app start, previously persisted pending items must appear in `SyncService` live queue without manual sync.  
  - [x] Req 2: Worker heartbeat and queue API should reflect correct counts immediately after startup.  

- [x] Non-Functional Requirements (performance, scalability, etc.):  
  - [x] Req 1: Solution must avoid additional heavy DB loads beyond existing snapshot read.  
  - [x] Req 2: Maintain thread safety; no race conditions with worker startup.  

## Inputs
- [x] Define expected inputs:  
  - Field: Persisted status snapshot (`status_snapshot` setting)  
  - Type: JSON with queue pending/current/completed arrays  
  - Constraints: May contain stale `current` items needing cleanup  

## Outputs
- [x] Define expected outputs:  
  - Field: Live queue state inside `SyncService`  
  - Type: In-memory lists representing pending/current/completed  
  - Rules: Pending matches persisted pending (plus cleaned current), enabling downloads to start.  

## Behaviors / Flows
- [x] Primary flow:  
  1. Build app reads snapshot and registers persistence.  
  2. Clean up stale items, saving to snapshot.  
  3. SyncService reloads live queue from updated snapshot before worker starts.  

- [x] Edge cases:  
  - [x] Case 1: Snapshot missing or empty → live queue remains empty without errors.  
  - [x] Case 2: Snapshot contains `current` items → they must end up back in pending (handled by `cleanup_startup_state`).  

## Examples (Acceptance Cases)
- [x] Example 1: Snapshot with 100 pending items → worker log shows `Queue status - 100 pending` after startup.  
- [x] Example 2: Snapshot absent → worker log continues to show zero pending without crashes.  
- [x] Example 3 (Edge Case): Snapshot with `current` items → after cleanup and sync, those items counted in pending.  

## Test Cases (for TDD seed)
- [x] Requirement → Test Case(s):  
  - Req 1 → Integration test: simulate snapshot in settings, build service, assert live queue pending count equals snapshot.  
  - Req 2 → Unit test: calling new bootstrap method with snapshot updates live queue; unchanged when snapshot empty.  

## Planning Addendum (for OOD / Implementation Strategy)
- [x] Components / Modules:  
  - `SyncService` live queue loader  
  - `app.build_app` startup sequence  

- [x] Classes & Interfaces:  
  - Exposure of a public method to refresh live queue from status snapshot.  

- [x] Reuse / DRY considerations:  
  - Reuse existing `_load_persistent_into_live` logic; avoid duplicate parsing.  

- [x] MVP task breakdown:  
  1. Expose safe public wrapper invoking `_load_persistent_into_live` inside `SyncService`.  
  2. Call wrapper after persistence registration and cleanup in `build_app`.  
  3. Add regression test verifying bootstrap populates live queue when snapshot present.  

### Status
- [ ] Specification reviewed  
- [x] Tests derived from spec  
- [ ] Implementation complete  
- [ ] Verification complete  
