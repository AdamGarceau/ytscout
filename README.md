# ytscout — free local vidIQ/TubeBuddy, your doctrine baked in

No subscription. No API keys. Your channel data never leaves this machine. Every number is
grounded in the consensus doctrine (`~/content-engine/strategy/youtube-consensus-doctrine.md`).

Data: yt-dlp (keyless). Optional brain: local gemma4:12b via ollama. Everything else: Python stdlib.

## Commands (type `scout <command>`)

**`scout outliers <handle> [--vs h1,h2] [--niche ai] [--scan 30] [--top 20] [--ai] [--html]`**
The crown jewel. Finds PROVEN video ideas by view-to-subscriber ratio across a channel and its
comparable-niche channels. 5x+ subs = strong outlier, 20x = gold. Shows estimated $ per video.
`--ai` uses gemma to port the top outlier into your two channels' niches.

**`scout weekly [--niche ai] [--top 25]`**  ← the automatable idea farm, ZERO AI
Scans your watchlist for new outliers since last run, flags what's NEW, saves a dated report to
`reports/weekly-YYYY-MM-DD.md`. This is the doctrine's weekly idea-farm ritual, automated.
Manage the list: `scout watch --add liamottley,MikeyNoCode --niche ai`

**`scout feed "<niche>" --my-title "..." [--my-thumb path.jpg] [--pos 3] [--open]`**
Renders YOUR proposed title + thumbnail among REAL niche videos in a YouTube-style grid, so you can
see if your packaging stops the scroll before you upload. The doctrine's pre-upload gate. Output:
`reports/feed.html`. Drop in `--my-thumb` with your real image to make it honest.

**`scout title "<proposed title>" [--ai]`**
Scores a title 0-100 against the data-study rules (6-7 words, <60 chars, no long-form emojis,
psychological frames). `--ai` generates 5 stronger variants.

**`scout niche "<search>" [--html]`**
Shows what ranks for a term, the view distribution, and whether the top is saturated (bend the
angle) or spread (room to enter).

**`scout keywords "<seed>" [--expand none|quick|full] [--top N] [--check N] [--n N] [--html]`**
Free, keyless keyword research. Demand is relative, built from how often and how early a phrase
surfaces across YouTube autocomplete expansions of your seed, never presented as a search volume.
Competition is computed from who actually ranks for each phrase: the median subscriber size of
ranking channels, their median views, and how concentrated the top-3 results are. LOW means small
channels are ranking, HIGH means big channels own the term. `--expand` controls how many
autocomplete requests run (none=1, quick=9, full=35). `--check N` bounds how many of the top
keywords get a real competition read, since each one costs about `--n` seconds on a cold cache;
the rest show n/a rather than guessing. Works with ollama stopped, degrades to one clear line if
the network is down.

**`scout audit <handle> [--niche ai] [--rpm 6.5]`**
Audits a channel's PUBLIC packaging, lengths (vs the doctrine's TimeZone dead-zones), consistency,
and estimated AdSense.

**`scout config --rpm 6.5 [--niche ai]`**
Save your REAL RPM from YouTube Studio (Analytics → Revenue → RPM) so revenue estimates use your
actual number instead of a niche guess. Also applied automatically: an 8min+ midroll bump (long
videos carry mid-roll ads and earn ~1.6x). Any command also takes `--rpm N` to override once.

**`scout mine [--setup] [--auth] [--days 28]`**  ← YOUR channel's PRIVATE metrics
The one thing no free tool can do without your permission: your real CTR-adjacent metrics, average
% viewed (retention), subscribers gained, and REAL revenue — straight from your channel's Analytics
API. One-time setup: `scout mine --setup` walks you through creating a free Google Cloud OAuth client
(~5 min), then `scout mine --auth` authorizes once in your browser, then just `scout mine`. The token
stays on this machine. Free APIs, no cost.

## Niches for --niche (sets the RPM for revenue estimates)
ai, tech, software, business, finance, marketing, education, tutorial, productivity, family,
homeschool, lifestyle, gaming, entertainment, vlog. Default RPM $4.

## Run the weekly farm automatically (optional — you enable it)
A launchd job is pre-written at `~/Library/LaunchAgents/com.adam.ytscout.weekly.plist` (Monday 7 AM).
It is NOT loaded. To turn it on:
    launchctl load ~/Library/LaunchAgents/com.adam.ytscout.weekly.plist
To turn it off:  `launchctl unload ...` the same path.

## Honest limits
- Views/subs/durations/dates are public data via yt-dlp. `scout keywords` computes a relative
  demand signal from YouTube autocomplete and a competition score from live ranking data, both
  keyless. Neither is an absolute search volume the way a paid tool like vidIQ reports one.
- Your own CTR/retention/impressions need OAuth to your channel's Analytics API — not built yet.
- Data is cached 6h in `.cache/` so repeat runs are instant.
