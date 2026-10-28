# ytscout — free local vidIQ/TubeBuddy, your doctrine baked in

No subscription. No API keys. Your channel data never leaves this machine. Every number is
grounded in the consensus doctrine (`~/content-engine/strategy/youtube-consensus-doctrine.md`).

Data: yt-dlp (keyless). Optional brain: local gemma4:12b via ollama. Everything else: Python stdlib.

## Commands (type `scout <command>`)

**`scout outliers <handle> [--vs h1,h2] [--niche ai] [--scan 30] [--top 20] [--ai] [--html] [--shorts exclude|include|only] [--since-months 6] [--screen] [--drop-flagged]`**
The crown jewel. Finds PROVEN video ideas by view-to-subscriber ratio across a channel and its
comparable-niche channels. 5x+ subs = strong outlier, 20x = gold. Shows estimated $ per video.
`--ai` uses gemma to port the top outlier into your two channels' niches.

- `--shorts` (also on `weekly`, `niche`, `tiers`): Shorts are videos of 60s or less. `exclude` (the
  default) keeps the old long-form-only behavior, `include` mixes them in with a `Short` column,
  `only` studies Shorts alone. Every record is tagged `is_short`.
- `--since-months N` (also on `weekly` and `tiers`, default 6): only uploads from the last N months
  count, both for the ranking and for the channel median. `--since-months 0` turns it off. Videos
  with no upload date are kept.
- `--screen` adds a `Flags` column that names why an outlier may be fake or not portable:
  `subs/1k N` (under 5 subscribers per 1k views, i.e. views 200x+ subs: bought views or Shorts-feed
  spill), `subs>>views` (the channel's typical video gets under 1% of its subs: bought or dead subs),
  `likes hidden`, `comments off`, `batch xN` (N uploads the same day), `faceless:<term>` (AI-voice or
  faceless pattern in the title/description, e.g. ElevenLabs, text to speech, Reddit stories).
  `--drop-flagged` removes flagged rows (and implies `--screen`). A flag is a reason to look, not a verdict.

```
scout outliers liamottley --vs MikeyNoCode --screen --since-months 3
scout outliers liamottley --shorts only --since-months 0
```

**`scout tiers [handles...] [--list ai] [--input channels.json] [--tiers 1K-10K,10K-50K,50K-250K] [--top 5] [--json]`**
The small-channel study. Buckets channels by subscriber count (lower bound inclusive, `--tiers`
takes any bands, K/M suffixes ok), then per tier reports median views (every video in the tier),
the median of the channels' medians, and the top-N outliers ranked by outlier multiple = video views
÷ that channel's median. Channels come from the handles you pass, else the active watchlist
(`--list` picks one), or `--input` a saved JSON file (a list of `{handle, name, subs, videos: [...]}`
or `{"channels": [...]}`) for a fully offline run. Takes `--shorts`, `--since-months`, `--screen`,
`--drop-flagged`, `--min-views`. `--json` prints the whole study as JSON.

```
scout tiers --list peers-ai --screen
scout tiers --input tests/fixtures/channels.json --tiers 1K-50K,50K-500K --json
```

**`scout weekly [--niche ai] [--top 25] [--shorts exclude] [--since-months 6]`**  ← the automatable idea farm, ZERO AI
Scans your watchlist for new outliers since last run, flags what's NEW, saves a dated report to
`reports/weekly-YYYY-MM-DD.md`. This is the doctrine's weekly idea-farm ritual, automated.
Manage the list: `scout watch --add liamottley,MikeyNoCode --niche ai`

**`scout peers [--list ai] [--min-subs 1000] [--max-subs 50000] [--n 10] [--cap 120] [--queries FILE]`**
Finds your PEERS: same-size channels in your lane with outsized returns. Searches the seed terms in
`peers-queries-<list>.txt` (edit it), keeps channels in the sub band (default 1K-50K; seeds in `peers-seeds-<list>.txt` always included) with 3+ long-forms in 90 days and
topical fit, ranks by median video/channel-median plus videos at 5x+ subs, and writes
`reports/peers-<list>-YYYY-MM-DD.md` with 5 remake-brief CANDIDATES (teardown first, not scripts; briefs
come from local gemma, title/stats only). Saves the top N to watchlist list `peers-<list>` (never touches
the others). Then farm them weekly: `scout weekly --list peers-ai`. Cached and rate-limit gentle; on a
429 just rerun the same command to resume.

**`scout feed "<niche>" --my-title "..." [--my-thumb path.jpg] [--pos 3] [--open] [--tv | --grid yt|tv|ig] [--input tiles.json]`**
Renders YOUR proposed title + thumbnail among REAL niche videos in a YouTube-style grid, so you can
see if your packaging stops the scroll before you upload. The doctrine's pre-upload gate. Output:
`reports/feed.html`. Drop in `--my-thumb` with your real image to make it honest.

- `--tv` (same as `--grid tv`) also writes `reports/feed-tv.html`: a YouTube TV home-screen mock,
  dark UI, large 16:9 tiles 5 across, left rail and chips, the first tile focused. Sized in viewport
  units so a full-screen browser window reads like a TV from the couch.
- `--grid ig` also writes `reports/feed-ig.html`: a 4:5 Instagram / Facebook profile grid, 3 across,
  for carousel covers. Tiles with `"carousel": true` get the stacked-squares icon.
- `--input tiles.json` builds from your own competitor tiles instead of a live search (no network).
  Format: a list of tiles, or `{"label", "profile": {handle, posts, followers, following, bio},
  "candidate": {tile}, "tiles": [...]}`. Tile keys: `title`, `channel`, `views` (number) or
  `views_str`, `age`, `dur` (seconds or "12:34"), `thumb` (an image URL, or a path relative to the
  JSON file, which is embedded), `carousel`. `--my-title` / `--my-thumb` override the candidate.

All three files are plain HTML/CSS with no scripts, fonts or other external assets; the only things
loaded are the images you pass in (local images are base64 embedded).

```
scout feed --input tests/fixtures/feed_tiles.json --tv --my-title "I fired my software stack"
scout feed --input covers.json --grid ig --my-thumb cover-v2.png --pos 0
```

**`scout social-audit <export.json> [--tz -5] [--topics 8] [--label NAME] [--out DIR] [--json]`**
Audits an Instagram or Facebook account from a JSON file you already have. No scraping, no
network, no model calls. Input is either a Meta "Download your information" JSON (Instagram
`posts_1.json` / `reels.json`, Facebook `your_posts_1.json`; Meta's mangled UTF-8 is repaired) or
a simple list (or `{"data": [...]}`) of `{id, caption, media_type, timestamp, like_count,
comments_count, views|plays, permalink}`. `media_type` takes the Graph API values (`REELS`,
`VIDEO`, `CAROUSEL_ALBUM`, `IMAGE`, `TEXT`); `timestamp` is unix seconds or ISO-8601.
Writes `reports/social-audit.json` and a self-contained `reports/social-audit.html` (no scripts)
with:

- **Format mix**: Reel / Carousel / Single image / Text, share of posts against share of views.
- **Topic mix**: captions clustered by shared keyword (greedy: the keyword shared by the most
  remaining posts becomes a topic, up to `--topics`), with per-topic median views and likes.
- **Outliers**: posts at 3x / 5x / 10x the account median plays (views), or likes when the export
  has no view counts. Meta's own exports usually carry no metrics, so those get format, topic and
  cadence only.
- **Cadence**: posts per week, median and longest gap, posts per month, and a weekday x hour heat
  table (`--tz` shifts it from UTC).

```
scout social-audit tests/fixtures/social_simple.json --label "synthetic baker" --tz -5
```

**`scout title "<proposed title>" [--ai]`**
Scores a title 0-100 against the data-study rules (6-7 words, <60 chars, no long-form emojis,
psychological frames). `--ai` generates 5 stronger variants.

**`scout niche "<search>" [--html] [--shorts exclude|include|only]`**
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

**`scout dash [--refresh] [--open]`**
Assembles one self-contained `reports/dashboard.html` from what is already on disk: the current
top outlier, a run-over-run trend across your saved weekly reports, watchlist health, the RPM
actually in use, and the last weekly-cron run status. Offline by default, zero model calls, and
under 150KB with no embedded thumbnails, so this is what the loaded launchd weekly job can
regenerate unattended. `--refresh` is the one opt-in network path: it runs a live weekly scan
first (needs network), then assembles. `--open` opens the file when done.

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
- `--screen` reads hidden likes / disabled comments from what yt-dlp reports, which can also be
  missing for other reasons; treat every flag as a prompt to open the video, not proof.

## Tests
`python3 -m pytest` runs the suite on synthetic fixtures in `tests/fixtures/` (no network, no
YouTube calls, `yt-dlp` not required).
