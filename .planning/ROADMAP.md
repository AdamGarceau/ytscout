# Roadmap: ytscout

## Overview

v1.0 shipped the doctrine-grounded core: find proven ideas, score packaging, read a niche, audit
a channel, and farm the whole thing weekly without a model call. v1.1 closes the one gap that
makes the tool's own launch claim false, and gives it a face.

## Milestones

- ✅ **v1.0 Core** - Phase 1 (shipped 2026-07-14)
- 🚧 **v1.1 Demand + Face** - Phases 2-3 (in progress)

## Phases

<details>
<summary>✅ v1.0 Core (Phase 1) - SHIPPED 2026-07-14</summary>

### Phase 1: Doctrine-grounded core
**Goal**: A keyless local tool that replaces the vidIQ/TubeBuddy functions Adam actually uses.
**Plans**: shipped without GSD plans (main-thread speed-run under the spend cap)

Shipped commands:
- [x] `outliers` — proven ideas by view-to-subscriber ratio, plus revenue estimate
- [x] `weekly` — zero-AI schedulable idea farm with a dated report
- [x] `feed` — thumbsup.tv-style packaging preview against real niche thumbnails
- [x] `studio` — visual GUI to test title + thumbnail against the live feed
- [x] `watch` — watchlist management, one per channel/niche
- [x] `title` — data-study title scorer
- [x] `niche` — saturation read on a search term
- [x] `audit` — public packaging, length zones, revenue
- [x] `config` — save real RPM from Studio
- [x] `mine` — the user's own private CTR/retention via OAuth

</details>

### 🚧 v1.1 Demand + Face (In Progress)

**Milestone goal:** make the launch claim true, then make the tool presentable on camera.

#### Phase 2: Keyword demand + competition — COMPLETE 2026-08-16
**Goal**: `scout keywords "<seed>"` returns real demand and competition numbers, so the claim
"I replaced a $40/month app" stops being false.
**Depends on**: Phase 1
**Success Criteria** (what must be TRUE):
  1. [x] `scout keywords "<seed>"` prints a ranked table of related keywords with a demand signal
     and a competition signal, using no API key and no paid service.
  2. [x] Demand is derived from YouTube autocomplete; competition is computed from the ranking data
     `search_dump()` already pulls. Neither is presented as an absolute search volume.
  3. [x] The now-false disclaimer in `cmd_niche` ("those need a paid API") is gone, replaced by an
     accurate statement of what the numbers are.
  4. [x] The command works with ollama stopped and survives a network failure without a traceback.
**Plans**: 1 plan (quick task)

Plans:
- [x] 02-01: `scout keywords` + retire the cmd_niche disclaimer — see
  `.planning/quick/260816-crb-add-scout-keywords-command-with-free-dem/260816-crb-SUMMARY.md`

#### Phase 3: Dashboard
**Goal**: `scout dash` writes one self-contained `reports/dashboard.html` good enough to put on
camera, regenerated daily by the already-loaded launchd job.
**Depends on**: Phase 2
**Success Criteria** (what must be TRUE):
  1. `scout dash` writes a single self-contained HTML file with no external assets.
  2. Nothing on the render path calls a model, so the launchd job produces it unattended.
  3. It reads as designed rather than default-generated (run `web-design-craft` first).
**Plans**: 1 plan (quick task)

Plans:
- [ ] 03-01: `scout dash`

## Progress

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1. Doctrine-grounded core | v1.0 | n/a | Complete | 2026-07-14 |
| 2. Keyword demand + competition | v1.1 | 1/1 | Complete | 2026-08-16 |
| 3. Dashboard | v1.1 | 0/1 | Not started | - |
