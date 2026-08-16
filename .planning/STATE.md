# STATE

project: ytscout
mode: forge speed-run (BUILD FOR SELF), shipped v1.0 2026-07-14
current_phase: 2 (Keyword demand + competition) — v1.1, COMPLETE
stopped_at: Phase 2 shipped as quick task 260816-crb. Phase 3 (dashboard) is next.

## Project Reference

See: .planning/PROJECT.md (updated 2026-08-16)

**Core value:** free, local, keyless vidIQ/TubeBuddy replacement with Adam's doctrine baked in
**Current focus:** Phase 2 — `scout keywords`, the gap that makes the video's title honest

## Current Position

Phase: 2 of 3 (Keyword demand + competition) — COMPLETE
Plan: quick task 260816-crb (executed 260816-crb-PLAN.md)
Status: Complete, ready for Phase 3
Last activity: 2026-08-16 — `scout keywords` shipped, false paid-API claim retired everywhere

## Completed

- **Phase 1 (v1.0, 2026-07-14):** ten commands shipped — outliers, weekly, feed, studio, watch,
  title, niche, audit, config, mine. `scout` installed on PATH at `/usr/local/bin/scout`.
  Built in the main thread with local tooling only because the monthly Claude spend cap was hit.
  Field-tested against Adam's real AI-channel niche; surfaced real competitors and a real 214K
  outlier.
- **Phase 2 (v1.1, 2026-08-16):** `scout keywords "<seed>"` shipped — free, keyless relative
  demand (YouTube autocomplete) + computed competition score (search_dump ranking data). The
  "those need a paid API" disclaimer is gone from `cmd_niche` and README. Makes the Concept A
  video's "I Replaced a $40/Month App" claim true. Summary:
  `.planning/quick/260816-crb-add-scout-keywords-command-with-free-dem/260816-crb-SUMMARY.md`

## Accumulated Context

### Decisions

- Phase 2: demand comes from YouTube autocomplete (keyless), competition is computed from the
  ranking data `search_dump()` already returns. Neither gets presented as absolute search volume.
- Phase 2: Python's default cert store fails on this machine's Python 3.13 framework install
  (`CERTIFICATE_VERIFY_FAILED`). `certifi` is installed and works. Any new outbound HTTPS in
  `scout.py` needs an explicit certifi SSL context. `curl` to the same endpoint succeeds, which
  is how this was isolated. Fixed in `_ssl_ctx()` (soft-optional `certifi` import, never disables
  verification).
- Phase 2 shipped: `keyword_demand()` scores autocomplete suggestions 0-100 by rank position +
  repeat-hit frequency across `--expand none|quick|full` (1/9/35 requests). `keyword_competition()`
  scores 0-100 (higher=harder) on log-scaled median ranking-channel subs (45%), median views (35%),
  and top-3 view concentration (20%), banded LOW/MED/HIGH. Competition reads are bounded by
  `--check` since each costs ~n seconds cold; unchecked rows render `n/a` rather than guessing.

### Blockers/Concerns

- Phase 2's downstream blocker is now clear: the Concept A video (ClickUp 86baz5e2t, urgent,
  starts the ship clock) can film — `scout keywords` returns real, defensible numbers with an
  honest legend, no API key, no traceback offline, no ollama dependency.
- Phase 3 (dashboard) is next and not a filming blocker.

## Session Continuity

Last session: 2026-08-16
Stopped at: Phase 2 (`scout keywords`) shipped and verified. Phase 3 (dashboard) not started.
Resume file: None
