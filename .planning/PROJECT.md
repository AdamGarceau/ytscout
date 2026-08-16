# PROJECT: ytscout

## Core value

A free, local, keyless replacement for the parts of vidIQ and TubeBuddy that actually move the
needle, with Adam's own consensus doctrine baked in instead of a vendor's defaults.

## Who it is for

Adam, for two channels: Brooke + Adam (family lifestyle / homeschool) and the Adam-fronted
AI build-with-me channel. Forge verdicted it **BUILD FOR SELF**, not BUILD FOR MARKET. The
keyword-tool space is a red ocean to sell into. The value here is that it encodes his doctrine.

## Hard constraints

1. **Zero paid APIs.** Data comes from yt-dlp (keyless). Optional brain is local gemma4:12b via
   ollama. Everything else is Python stdlib.
2. **Zero AI on any render path.** Reports and dashboards must regenerate unattended from a
   launchd job with no model call.
3. **It ends up on camera.** This tool is the subject of the AI channel's Concept A video, so
   output legibility is a product requirement, not polish.
4. **Honest output.** Where a number is a proxy rather than the real thing, the tool says so.
   The doctrine is build-don't-cover: close a gap rather than soften a claim about it.

## Key decisions

| Decision | Why |
|---|---|
| Single-file `scout.py`, stdlib only | Portable, readable on camera, nothing to install |
| yt-dlp instead of the YouTube Data API | No key, no quota, no billing surface |
| ollama optional, never required | Every command must work with the model server down |
| Real RPM from Studio overrides niche-tier guesses (`rpm.json`) | Adam's own number beats any table |
| `.oauth/` gitignored | Repo is expected to go public alongside the video |

## Doctrine source

`~/content-engine/strategy/youtube-consensus-doctrine.md`

## Status

Shipped 2026-07-14 as a Forge speed-run, built in the main thread because the monthly Claude
spend cap was hit. `scout` is on PATH at `/usr/local/bin/scout`. GSD planning was not used for
the v1.0 build; `.planning/` was backfilled 2026-08-16 so subsequent work runs under GSD.
