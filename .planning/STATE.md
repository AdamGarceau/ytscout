# STATE

project: ytscout
mode: forge speed-run (BUILD FOR SELF), shipped v1.0 2026-07-14
current_phase: 3 (Dashboard) — v1.1, COMPLETE. v1.1 milestone fully shipped.
stopped_at: Phase 3 shipped as quick task 260816-d4i. v1.1 (Demand + Face) is done; no phase queued.

## Project Reference

See: .planning/PROJECT.md (updated 2026-08-16)

**Core value:** free, local, keyless vidIQ/TubeBuddy replacement with Adam's doctrine baked in
**Current focus:** v1.1 shipped. `scout dash` is the "nice-to-have shot" for the Concept A video.

## Current Position

Phase: 3 of 3 (Dashboard) — COMPLETE
Plan: quick task 260816-d4i (executed 260816-d4i-PLAN.md)
Status: Complete. v1.1 milestone (Phases 2-3) fully shipped.
Last activity: 2026-08-16 — `scout dash` shipped, self-contained offline dashboard.html

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
- **Phase 3 (v1.1, 2026-08-16):** `scout dash` shipped — offline, self-contained
  `reports/dashboard.html` (10.1KB) assembled purely from files already on disk: hero outlier
  number, outlier table, run-over-run trend (dark band, inline SVG, all 8 runs including the two
  legitimate zero-outlier ones), watchlist health, RPM in use with an honest source label, and
  last cron run status. Zero network, zero model call by default; `--refresh` is the one opt-in
  network branch. Gives the tool a face for the Concept A video. Summary:
  `.planning/quick/260816-d4i-add-scout-dash-a-self-contained-offline-/260816-d4i-SUMMARY.md`

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
- Phase 3: `_parse_weekly_md`'s list/niche comes from the report's header line, never the
  filename — `weekly-2026-07-14.md` is untagged but its content is the homeschool watchlist, a
  verified-on-disk trap the header-based parse avoids.
- Phase 3: header-row detection in a markdown table needs two-cell agreement
  (`cells[0]=="new"` AND `cells[1]=="v/sub"`), not one. A single-cell check drops every real NEW
  outlier row, since it lowercases identically to the header's own first cell.
- Phase 3: `_dash_esc` escapes third-party interpolations with `html.escape` plus a second pass
  that neutralizes bare `=` characters. Plain `html.escape` alone leaves attribute-injection
  look-alike substrings (e.g. `onerror=alert(1)`) fully readable as text even after the
  surrounding angle brackets are entity-encoded; this is now the standard escaping helper for any
  third-party text rendered into `scout.py`'s HTML outputs.
- Phase 3: `reports/` is already gitignored (personal channel data). `dashboard.html` is generated
  but intentionally never committed.

### Blockers/Concerns

None open. v1.1 (Demand + Face) is fully shipped: `scout keywords` makes the launch claim true,
`scout dash` gives the tool a face for camera. No phase is currently queued; the next roadmap
milestone would need to be scoped fresh if Adam wants to keep building on ytscout.

## Session Continuity

Last session: 2026-08-16
Stopped at: Phase 3 (`scout dash`) shipped and verified. v1.1 milestone complete.
Resume file: None
