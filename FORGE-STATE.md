# FORGE-STATE — ytscout

**Project:** ytscout — a free, local, keyless replacement for the parts of vidIQ and TubeBuddy that actually matter, for Adam's own YouTube use (Brooke+Adam channel + the AI build-with-me channel).

**Run mode:** SPEED-RUN (BUILD FOR SELF). Personal tool; validation compressed because the research is already done (the consensus doctrine IS the CEP).

**Hard constraint this run:** monthly Claude spend cap is HIT. Forge's GSD build waves and Claude synth panels would fail on subagents, so the build runs in the MAIN THREAD with local tooling only (yt-dlp keyless + gemma4:12b via ollama + Python stdlib). Zero paid APIs. This is the constraint Adam set explicitly.

**Current stage:** Stage 5 (SHIP). Installed on PATH; one optional user-enabled scheduler pending.

## Artifact checklist
- [x] validation/00-idea.md — idea + kill criteria (Stage 0)
- [x] validation/01-verdict.md — compressed honest verdict + gap note (Stage 1, speed-run)
- [x] .reggie/predictions.md — Reggie on the record (Stage 2 + Stage 4 callback, rule 8)
- [x] scout.py — the tool, 6 commands: outliers, weekly, feed, title, niche, audit
- [x] Stage 3 self-test: all commands run on real channels (amplifyviews, liamottley, niche search) — pass
- [x] Stage 4 field test: run against Adam's real AI-channel niche; surfaced real competitors + a real 214K outlier; feed rendered with 11 real thumbnails. Reggie's 2 fair limits logged.
- [x] Stage 5: `scout` on PATH (/usr/local/bin/scout); README written; launchd job pre-written but NOT loaded (Adam enables it; auto-mode correctly blocked auto-install of unrequested persistence)
- [ ] Optional next: `--mine` OAuth mode for the user's OWN CTR/retention (Reggie's field-test point); real per-video RPM instead of niche-flat estimate

**Verdict:** BUILD FOR SELF. Red ocean to sell; high value to Adam because it encodes HIS doctrine, not vidIQ's defaults. Gap note in 01-verdict.md.

**Real-human touchpoint:** Adam is the user + field test. Not all-synthetic.

**Six commands shipped:** outliers (crown jewel, view-to-sub + revenue), weekly (zero-AI automatable idea farm + dated report), feed (thumbsup.tv-style packaging preview with REAL niche thumbnails), title (data-study scorer), niche (saturation read), audit (public packaging + revenue + honest OAuth limit).

**Next action:** none blocking. Optional: enable the weekly launchd job; build `--mine` OAuth mode.
