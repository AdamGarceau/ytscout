---
phase: 02-keyword-demand
plan: 01
subsystem: scout.py CLI
tags: [keyword-research, ssl, certifi, cli]
dependency-graph:
  requires: []
  provides: [scout-keywords-command, autocomplete-demand-layer, competition-scoring]
  affects: [cmd_niche, README.md]
tech-stack:
  added: []
  patterns:
    - "soft-optional certifi import for an explicit SSL context (default Python 3.13 framework cert store fails on this machine)"
    - "urlencode-only URL construction for untrusted user input"
    - "bounded fan-out (--expand, --check) instead of unbounded network calls"
key-files:
  created: []
  modified:
    - scout.py
    - README.md
decisions:
  - "Demand is a relative 0-100 score derived from autocomplete rank position and repeat-hit frequency across expansion queries, never labeled or stored as an absolute search volume."
  - "Competition is a 0-100 log-scaled score (higher = harder) from search_dump() ranking data: median ranking-channel subs, median views, and top-3 view concentration. Returned with every raw input alongside the score so it is never a bare unexplained number."
  - "autocomplete() caches a result whenever _fetch_json returns a real (non-None) response, even if the shape validation reduces it to an empty list; it does not cache on a true network failure, so a later retry isn't poisoned by a transient outage."
metrics:
  duration: "~35 minutes"
  completed: 2026-08-16
---

# Phase 2 Plan 1: scout keywords + retire the false paid-API claim Summary

Added `scout keywords "<seed>"` to `scout.py`: a free, keyless keyword-research command that pairs
a relative demand signal (from YouTube autocomplete) with a computed competition signal (from
`search_dump()`'s existing ranking data), then retired the now-false "those need a paid API"
disclaimer everywhere it appeared.

## What shipped

**Task 1 — SSL-safe HTTP layer + autocomplete demand signal** (`1713ce8`)
- `_ssl_ctx()`: memoized SSL context, prefers `certifi.where()` when certifi is importable
  (soft-optional, no new pip dependency), falls back to a plain verified `ssl.create_default_context()`.
  Certificate verification is never disabled in either branch.
- `_fetch_json(url, timeout=6)`: never raises — wraps the entire request/decode/parse in a bare
  `except Exception: return None`.
- `autocomplete(q)`: hits `suggestqueries.google.com/complete/search` with `urllib.parse.urlencode`
  (the seed is user input and is never string-interpolated into the URL), validates response shape
  defensively, caches 6h, rate-limits with a 0.12s sleep after each real network call.
- `keyword_demand(seed, mode)`: three expansion modes (`none`=1 request, `quick`=9, `full`=35).
  Scores every suggestion by rank position (`1/(1+r)`) accumulated across expansions, boosted 15%
  per repeat hit, normalized to 0-100 against the top scorer.

**Task 2 — Competition scoring, `cmd_keywords`, CLI subparser** (`04cbc3d`)
- `keyword_competition(kw, n)`: pulls `search_dump(kw, n)`, filters to long-form, computes median
  views, median ranking-channel subs, top-3 view concentration, and a small-channel share. Combines
  the first three into a 0-100 log-scaled score (subs 45%, views 35%, concentration 20%), banded
  LOW (<35) / MED (35-65) / HIGH (>65). Returns `None` (not a crash) when there's no long-form data.
- `cmd_keywords(args)`: prints a `Keyword | Demand | Hits | Comp | Band | MedViews | MedSubs` table
  (keyword truncated to 44 chars for camera legibility), bounds real competition reads to `--check`
  (rows past that show `n/a`), prints an honest legend explaining both signals, never calls `ollama()`,
  and degrades to one clear line with no traceback when autocomplete returns nothing.
- Wired the `keywords` subparser directly after `niche` with `--expand`, `--top`, `--check`, `--n`,
  `--html`.

**Task 3 — Retire the false disclaimer** (`6fb54aa`)
- `cmd_niche` no longer says search volume/competition "need a paid API." It now points at
  `scout keywords "<query>"` with an accurate description of what the two signals are.
- Module docstring command list gained the `scout keywords` usage line.
- README: new `scout keywords` block in the Commands section (right after `scout niche`), and the
  Honest limits section's first bullet rewritten to describe the real keyless signals instead of
  the false "needs a paid API" claim.

## Verification (all gates run for real, results below)

1. `python3 -m py_compile scout.py` — passes.
2. `keyword_demand("claude code", "none")` — `queries==1`, `failures==0`, 10 real suggestions
   returned with 0-100 scores. Confirmed the certifi SSL context fixes the verified
   `CERTIFICATE_VERIFY_FAILED` finding from planning.
3. `_fetch_json` under a broken `https_proxy` returns `None`, no traceback.
4. `grep CERT_NONE|check_hostname=False|_create_unverified` on non-comment lines — 0 matches.
5. `scout keywords "claude code" --expand none --check 0 --top 8` — table renders with `Demand`
   and `Comp` columns, legend contains "not a search volume" (case-insensitive), 0 em-dashes.
6. Offline (`https_proxy` pointed at a closed port): `scout keywords "offline test" --expand none
   --check 0` prints one clear line ("network may be unreachable... no suggestions... Nothing to
   rank"), no `Traceback`, exit code 0.
7. `keyword_competition("claude code tutorial", 8)` — real object: `{'score': 89, 'band': 'HIGH',
   'med_views': 209304.5, 'med_subs': 1279000.0, 'top3_share': 0.88, 'small_share': 0.0}`.
8. `scout keywords "claude code" --expand quick --check 3 --top 8` (live, with real competition
   reads) — real HIGH-band scores with real MedViews/MedSubs shown for the top 3, `n/a` for the rest.
9. `grep -R "those need a paid API" scout.py README.md` — no matches.
10. `scout niche "claude code" --n 5` — no "paid API" string, contains "scout keywords" pointing
    at the real command.
11. `python3 scout.py --help` — lists `keywords`.
12. Static check: no `ollama(` call reachable from `cmd_keywords`, `keyword_demand`,
    `keyword_competition`, or `autocomplete` source. (Did not stop the user's live ollama service
    to test this end-to-end since it's a shared resource other work may depend on; the static
    reachability check is conclusive for "never calls ollama.")
13. `.oauth/` untouched — confirmed via `git status --short` (only `scout.py` and `README.md`
    modified) and it remains in `.gitignore`.

All of Phase 2's success criteria (ROADMAP.md) are met:
- `scout keywords "<seed>"` prints a ranked table with demand and competition columns, no API key,
  no paid service.
- Demand comes from autocomplete and is explicitly labeled relative; competition is computed from
  `search_dump()` ranking data. Neither is called a search volume anywhere in the output.
- The false "those need a paid API" disclaimer is gone from both `scout.py` and `README.md`.
- Works with ollama stopped (never called); survives a network failure with no traceback.

## Deviations from Plan

None on the three planned tasks - executed as written.

**Out-of-scope, deferred (not fixed, per scope boundary):** `cmd_niche`'s existing "Saturated at
the top" line (pre-existing code, untouched by this plan) still contains one em-dash character
("—"). This predates the plan and is outside the files/lines this plan touched. The em-dash
constraint in this plan applied to new user-facing strings added by these three tasks, all of
which are verified em-dash-free (gate 5 above, 0 matches on `scout keywords` output). Flagging here
rather than fixing silently, since Phase 3 or a future cleanup pass should sweep it along with any
other pre-existing em-dashes in `scout.py`.

## Known Stubs

None. Both new signals (`keyword_demand`, `keyword_competition`) return real computed values from
live data sources (YouTube autocomplete, `search_dump()`), not hardcoded or mocked output.

## Threat Flags

None beyond what the plan's own threat model already covers. The three mitigations in the threat
register (urlencode-only URL build, certifi-backed TLS, defensive JSON shape validation) are all
implemented as specified — verified directly by gates 3, 4, and the live `autocomplete()` runs
above, which returned well-formed suggestion lists from real (untrusted) API responses.

## Self-Check: PASSED

- `scout.py` contains `def cmd_keywords` — FOUND (grep confirmed, function present and wired).
- `README.md` contains `scout keywords` — FOUND.
- Commit `1713ce8` — FOUND (`git log --oneline` above).
- Commit `04cbc3d` — FOUND.
- Commit `6fb54aa` — FOUND.
