---
phase: 02-keyword-demand
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - scout.py
  - README.md
autonomous: true
requirements: [SC-1, SC-2, SC-3, SC-4]

must_haves:
  truths:
    - "`scout keywords \"<seed>\"` prints a ranked table of related keywords with a demand column and a competition column, using no API key and no paid service"
    - "Demand comes from YouTube autocomplete and is labelled relative, never presented as absolute search volume"
    - "Competition is computed from search_dump() ranking data (median views, median ranking-channel subs, top-3 view concentration) and is shown alongside its raw inputs"
    - "The command exits cleanly with a readable message when the network is unreachable, with no traceback"
    - "The command never calls ollama, so it works with the model server stopped"
    - "The false 'those need a paid API' claim is gone from cmd_niche and from README honest-limits, replaced by an accurate statement"
  artifacts:
    - path: "scout.py"
      provides: "_ssl_ctx, _fetch_json, autocomplete, keyword_demand, keyword_competition, cmd_keywords, keywords subparser"
      contains: "def cmd_keywords"
    - path: "README.md"
      provides: "scout keywords documentation and a corrected honest-limits bullet"
      contains: "scout keywords"
  key_links:
    - from: "cmd_keywords"
      to: "autocomplete"
      via: "demand expansion over suggestqueries.google.com"
      pattern: "suggestqueries\\.google\\.com"
    - from: "cmd_keywords"
      to: "search_dump"
      via: "bounded per-keyword competition read"
      pattern: "search_dump\\("
    - from: "main"
      to: "cmd_keywords"
      via: "argparse subparser set_defaults"
      pattern: "set_defaults\\(func=cmd_keywords\\)"
---

<objective>
Add `scout keywords "<seed>"` to `scout.py`: free, keyless keyword research returning a relative
demand signal from YouTube autocomplete and a computed competition signal from the ranking data
`search_dump()` already pulls. Then retire the now-false "those need a paid API" disclaimer in
`cmd_niche` and in the README honest-limits section.

Purpose: the Concept A video's synth-tested title claims "I Replaced a $40/Month App." ytscout's
own README currently says search volume and competition scores are what vidIQ sells and ytscout
skips, which makes that claim false. Doctrine is build-don't-cover: close the gap with real,
defensible numbers instead of softening the claim.

Output: three new helpers plus one new command in `scout.py`, a `keywords` subparser, corrected
disclaimer text, and an updated README.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/STATE.md
@scout.py
@README.md
</context>

<verified_findings>
Verified live before planning. Do NOT re-research these.

1. **The autocomplete endpoint works and is keyless.**
   `https://suggestqueries.google.com/complete/search?client=firefox&ds=yt&q=SEED` returns JSON
   shaped `[seed, [suggestion, ...], [], {...}]`. Seed "claude code" returned 10 suggestions
   ("claude code tutorial", "claude code vs cursor", "claude code skills", ...).

2. **Python's default cert store FAILS on this machine.** `urllib.request.urlopen` against that
   URL raises `ssl.SSLCertVerificationError: CERTIFICATE_VERIFY_FAILED: unable to get local issuer
   certificate`. `curl` to the same URL succeeds. `certifi` IS present at
   `/Library/Frameworks/Python.framework/Versions/3.13/lib/python3.13/site-packages/certifi/cacert.pem`
   but is NOT a declared dependency of this project. So: build an explicit
   `ssl.create_default_context(cafile=certifi.where())` when certifi imports, and fall back to a
   plain verified `ssl.create_default_context()` when it does not.
   **Never disable certificate verification. No check_hostname=False, no CERT_NONE.**

3. **`search_dump(query, n)` already returns per result:** `id`, `title`, `views`, `dur`,
   `channel`, `subs`. That is the whole raw material for the competition signal. It is cached 6h
   and costs roughly n seconds on a cold cache, so the number of `search_dump` calls this command
   makes must be bounded and default conservatively.

4. **Existing idiom to match:** `_cache_get`/`_cache_put` (line ~74), `human()` (line ~169),
   `table()` (line ~178), `cmd_niche` (line ~338), the argparse block (line ~1103). Imports at
   line 16 do NOT currently include `math`, `ssl`, or `urllib.parse`. All three are needed.
</verified_findings>

<constraints>
- **Python stdlib only.** The single permitted exception is a soft `try: import certifi` /
  `except ImportError:`. No new pip dependencies, no requirements file, no install-doc changes.
- **Zero paid APIs, zero API keys.**
- Everything stays in the single file `scout.py`, matching its existing idiom.
- The command must work with ollama stopped. It must not call `ollama()` at all.
- A network failure degrades with a clear one-line message, never a traceback.
- **Zero em-dashes in any user-facing string you add.** Use "n/a" for empty cells, not the
  em-dash the older code uses. Commas, periods, and parentheses only.
- Do NOT touch `.oauth/`.
- Output ends up on camera. The table must stay legible: short headers, aligned numbers.
</constraints>

<tasks>

<task type="auto">
  <name>Task 1: SSL-safe HTTP layer and the autocomplete demand signal</name>
  <files>scout.py</files>
  <action>
Extend the import line (line 16) with `math`, `ssl`, and `urllib.parse`.

Add a section after the yt-dlp data layer and before the ollama section, headed
`# ---------- autocomplete demand layer (keyless) ----------`.

Define `_ssl_ctx()`: builds and memoizes a module-level `_SSL_CTX`. Inside a
`try: import certifi / except ImportError:` return
`ssl.create_default_context(cafile=certifi.where())` on success and plain
`ssl.create_default_context()` on failure. Certificate verification stays ON in both branches per
finding 2.

Define `_fetch_json(url, timeout=6)`: builds a `urllib.request.Request` with a plain User-Agent
header, calls `urllib.request.urlopen(req, timeout=timeout, context=_ssl_ctx())`, reads bytes,
decodes UTF-8 with a latin-1 fallback (the endpoint may answer with an ISO-8859-1 charset), and
returns `json.loads(...)`. Wrap the entire body in a bare `except Exception: return None`. This
function NEVER raises, per the no-traceback constraint.

Define `autocomplete(q)`: returns an ordered list of suggestion strings for one query. Check
`_cache_get("ac_" + q)` first and return the cached list on a hit. On a miss, request
`https://suggestqueries.google.com/complete/search` with params built by
`urllib.parse.urlencode({"client": "firefox", "ds": "yt", "q": q})`. urlencode is mandatory: the
seed is user input and must never be interpolated raw into the query string. Validate the
response shape defensively before trusting it, since the payload is untrusted. Require a list of
length 2 or more whose element at index 1 is itself a list, and keep only members of that list
that are non-empty strings. Anything else returns an empty list. On success `_cache_put` the list
and `time.sleep(0.12)` before returning so a full expansion does not hammer the endpoint. A cache
hit does not sleep.

Define `EXPANSIONS`, the three expansion modes:
  - `"none"`: the bare seed only, 1 request.
  - `"quick"` (default): the bare seed plus 8 modifier prefixes and suffixes that surface question
    and comparison intent, for example `how to SEED`, `what is SEED`, `why SEED`, `best SEED`,
    `SEED vs`, `SEED for`, `SEED without`, `SEED tutorial`. 9 requests.
  - `"full"`: everything in quick plus `SEED a` through `SEED z`. 35 requests.

Define `keyword_demand(seed, mode="quick")`: runs `autocomplete()` across the expansion set and
scores every suggestion it sees. Rank position inside a single response is signal, so a suggestion
at 0-based rank r earns `1.0 / (1 + r)` points. Accumulate points per suggestion across all
expansions and separately count how many distinct expansions surfaced it (its hits). Raw score is
`points * (1 + 0.15 * (hits - 1))`, rewarding a phrase that keeps resurfacing. Normalize to a
0-100 integer against the top scorer. Return
`{"keywords": [(kw, demand, hits), ...] sorted by demand descending, "queries": int, "failures": int}`
where failures counts expansions that came back empty. If every expansion failed, return an empty
keyword list with `failures == queries` so the caller can print the network message.

Demand is RELATIVE, derived from how often and how early a phrase surfaces across autocomplete
expansions. Never store, name, or print it as a search volume.
  </action>
  <verify>
    <automated>cd /Users/garceau/ytscout && python3 -m py_compile scout.py && python3 -c "import scout; d=scout.keyword_demand('claude code','none'); assert d['queries']==1, d; assert d['failures']==0, 'autocomplete failed, check the certifi SSL context'; assert len(d['keywords'])>=5, d; assert all(isinstance(k,str) and 0<=s<=100 for k,s,h in d['keywords']), d; print('OK', d['keywords'][:3])"</automated>
    <automated>cd /Users/garceau/ytscout && https_proxy=http://127.0.0.1:9 python3 -c "import scout; print(scout._fetch_json('https://suggestqueries.google.com/complete/search?q=x'))" 2>&1 | grep -qx None && echo "OK: network failure returns None with no traceback"</automated>
    <automated>cd /Users/garceau/ytscout && grep -v '^ *#' scout.py | grep -c -E 'CERT_NONE|check_hostname *= *False|_create_unverified' | grep -qx 0 && echo "OK: TLS verification never disabled"</automated>
  </verify>
  <done>`keyword_demand("claude code","none")` returns real ranked suggestions with 0-100 relative
scores and zero failures. `_fetch_json` returns None instead of raising when the network is
unreachable. Certificate verification is never disabled anywhere in the new code.</done>
</task>

<task type="auto">
  <name>Task 2: Competition scoring, cmd_keywords, and the CLI subparser</name>
  <files>scout.py</files>
  <action>
Add `keyword_competition(kw, n)` beside the demand helpers. It calls `search_dump(kw, n)`, keeps
only results with `dur > SHORT_MAX_SEC`, and returns None when `search_dump` reports an error or
yields no long-form results, so the caller renders "n/a" instead of crashing. Otherwise compute:
  - `med_views`: median views of what ranks
  - `med_subs`: median subscriber count of the ranking channels, treating a missing subs as 0
  - `top3_share`: the top three results' views divided by total views on the page
  - `small_share`: fraction of ranking channels under 100000 subs

Combine into a 0-100 score where HIGHER MEANS HARDER, on log scales so one megachannel cannot
saturate the number:
  - subs term = `min(1.0, math.log10(max(med_subs, 1)) / 6.0)` (1M subs saturates)
  - views term = `min(1.0, math.log10(max(med_views, 1)) / 7.0)` (10M views saturates)
  - concentration term = `top3_share`
  - `score = round(100 * (0.45*subs_term + 0.35*views_term + 0.20*concentration))`
Band it: under 35 is LOW, 35 to 65 is MED, above 65 is HIGH. Return a dict carrying the score, the
band, and every raw input, because a bare unexplained number is not acceptable output here.

Add `cmd_keywords(args)` after `cmd_niche`. It must NOT call `ollama()`.
  1. Print a bold `KEYWORD RESEARCH  "SEED"` header matching the visual language of `cmd_niche`.
  2. Run `keyword_demand(args.seed, args.expand)`. If the keyword list is empty, print one clear
     line (network unreachable or no suggestions returned, nothing to rank) and return. No
     traceback, no partial table.
  3. Take the top `args.top` keywords for the table. Run `keyword_competition` on only the first
     `args.check` of them in ranked order, because each call costs roughly `args.n` seconds on a
     cold cache. Rows past `--check` show "n/a" in the competition columns.
  4. Render with the existing `table()` and `human()` helpers. Columns:
     `Keyword | Demand | Hits | Comp | Band | MedViews | MedSubs`. Truncate the keyword to about
     44 chars so the table stays legible on camera.
  5. Print a legend under the table stating plainly what each number is. Demand is relative, built
     from how often and how early a phrase surfaces in YouTube autocomplete across N expansions,
     and it is not a search volume. Comp is computed from who actually ranks for the phrase,
     weighting the median subscriber size of ranking channels, their median views, and how
     concentrated views are in the top three. LOW means small channels are ranking. Also print the
     `--check` budget note so the "n/a" rows are self-explaining. Zero em-dashes in every one of
     these strings.
  6. If `args.html`, write `reports/keywords.html` mirroring the small self-contained style
     `cmd_niche` uses (same inline CSS shape, `html.escape` on every interpolated value) and print
     the path.

Wire the subparser in `main()` directly after the existing `niche` parser:
    kw = sub.add_parser("keywords", help="free keyword demand + competition, no API key")
    kw.add_argument("seed")
    kw.add_argument("--expand", choices=["none","quick","full"], default="quick",
                    help="autocomplete expansion breadth (none=1 request, quick=9, full=35)")
    kw.add_argument("--top", type=int, default=20, help="keywords to show (default 20)")
    kw.add_argument("--check", type=int, default=5,
                    help="how many top keywords get a competition read, each costs about n seconds cold (default 5)")
    kw.add_argument("--n", type=int, default=12, help="search results per competition read (default 12)")
    kw.add_argument("--html", action="store_true")
    kw.set_defaults(func=cmd_keywords)
  </action>
  <verify>
    <automated>cd /Users/garceau/ytscout && python3 -m py_compile scout.py && python3 scout.py keywords "claude code" --expand none --check 0 --top 8 | tee /tmp/kw.out && grep -q "Demand" /tmp/kw.out && grep -q "Comp" /tmp/kw.out && grep -qi "not a search volume" /tmp/kw.out && grep -c "$(printf '—')" /tmp/kw.out | grep -qx 0 && echo "OK: table renders, legend honest, no em-dashes"</automated>
    <automated>cd /Users/garceau/ytscout && https_proxy=http://127.0.0.1:9 python3 scout.py keywords "offline test" --expand none --check 0 2>&1 | tee /tmp/kwoff.out; ! grep -q Traceback /tmp/kwoff.out && grep -qiE "network|unreachable|no suggestions" /tmp/kwoff.out && echo "OK: offline degrades with a clear message"</automated>
    <automated>cd /Users/garceau/ytscout && python3 -c "import scout; c=scout.keyword_competition('claude code tutorial', 8); assert c is None or (0<=c['score']<=100 and c['band'] in ('LOW','MED','HIGH') and 'med_views' in c and 'med_subs' in c and 'top3_share' in c), c; print('OK', c)"</automated>
  </verify>
  <done>`scout keywords "claude code" --expand none --check 0` prints a ranked, legible table with a
demand column, a competition column, and an honest legend. `--check 2` additionally fills real
Comp/Band/MedViews/MedSubs values from `search_dump`. The command runs with ollama stopped and
prints a clear message instead of a traceback when the network is down.</done>
</task>

<task type="auto">
  <name>Task 3: Retire the false paid-API claim in cmd_niche, the docstring, and the README</name>
  <files>scout.py, README.md</files>
  <action>
1. In `cmd_niche` (line ~360) replace the line that reads "Note: yt-dlp shows public views, not
   search volume/competition scores (those need a paid API). Views distribution is the free proxy."
   Do not merely delete it, replace it with an accurate statement: this view distribution is the
   saturation read for one term, and `scout keywords "SEED"` gives relative demand from YouTube
   autocomplete plus a computed competition score across related terms, with no API key. Zero
   em-dashes.

2. In the module docstring command list (lines 8-13) add the `keywords` usage line so the header
   matches the real CLI:
   `scout keywords "<seed>" [--expand none|quick|full] [--top N] [--check N] [--n N] [--html]`

3. In README.md add a `scout keywords` command block in the Commands section, positioned right
   after the `scout niche` block. Describe what the two signals actually are: demand is relative,
   from YouTube autocomplete expansion, not a search volume; competition is computed from who
   actually ranks (median subs of ranking channels, median views, top-3 concentration), LOW means
   small channels are ranking. Mention the `--check` cost note.

4. In README.md Honest limits, rewrite the first bullet. It currently says search volume and
   competition scores need a paid API and ytscout uses view distribution as the free proxy. That
   claim is now false. Replace it with the truth: ytscout computes a relative demand signal from
   YouTube autocomplete and a competition score from live ranking data, both keyless, and neither
   is an absolute search volume the way a paid tool reports one. Zero em-dashes in the new text.
  </action>
  <verify>
    <automated>cd /Users/garceau/ytscout && ! grep -q "those need a paid API" scout.py && ! grep -q "those need a paid API" README.md && echo "OK: false claim gone from both files"</automated>
    <automated>cd /Users/garceau/ytscout && grep -q "scout keywords" README.md && grep -q "scout keywords" scout.py && python3 scout.py --help | grep -q keywords && echo "OK: keywords documented in README, docstring, and CLI help"</automated>
    <automated>cd /Users/garceau/ytscout && python3 scout.py niche "claude code" --n 5 | tee /tmp/niche.out && ! grep -q "paid API" /tmp/niche.out && grep -q "scout keywords" /tmp/niche.out && echo "OK: cmd_niche now points at the real command"</automated>
  </verify>
  <done>The string "those need a paid API" appears nowhere in `scout.py` or `README.md`. `cmd_niche`
prints an accurate note that points to `scout keywords`. README documents the new command and its
honest-limits bullet describes what the two signals actually are.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| user shell -> outbound URL | The seed string is user input that gets placed into a query string |
| suggestqueries.google.com -> scout.py | Untrusted JSON crosses into the parser and then into terminal and HTML output |
| scout.py -> reports/keywords.html | Third-party strings (suggestions, titles, channel names) get written into a local HTML file |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-02-01 | Tampering | `autocomplete()` URL build | mitigate | Build params with `urllib.parse.urlencode`, never string-interpolate the seed into the URL |
| T-02-02 | Spoofing | new outbound HTTPS | mitigate | Explicit `ssl.create_default_context(cafile=certifi.where())` with a verified default fallback. TLS verification is never disabled, verified by the Task 1 grep gate |
| T-02-03 | Tampering | JSON response parsing | mitigate | Validate the shape before use (list of length 2+, element 1 is a list, keep only non-empty strings). Anything else returns an empty list |
| T-02-04 | Denial of Service | expansion loop | mitigate | Expansion breadth is a bounded `--expand` choice (max 35 requests), competition reads bounded by `--check`, 0.12s sleep between uncached calls, 6s socket timeout |
| T-02-05 | Elevation of Privilege | `reports/keywords.html` | mitigate | `html.escape` on every interpolated third-party value, matching the `cmd_niche` HTML writer |
| T-02-06 | Information Disclosure | outbound query content | accept | Only the user's own search seed leaves the machine, which is the point of the feature. No channel data, no credentials, `.oauth/` untouched |
</threat_model>

<verification>
Phase 2 success criteria, checked end to end:
1. `scout keywords "claude code" --expand quick --check 3` prints a ranked table with a demand
   column and a competition column, with no API key and no paid service.
2. Demand comes from autocomplete and is labelled relative; competition is computed from
   `search_dump()` ranking data. Neither is called a search volume anywhere in the output.
3. `grep -R "those need a paid API" scout.py README.md` returns nothing, and `cmd_niche` prints an
   accurate replacement note.
4. With ollama stopped the command works normally, and with the network down it prints one clear
   line and exits 0 with no traceback.
5. `grep -c em-dash` on the full command output is 0.
</verification>

<success_criteria>
- `scout keywords` exists, is documented, and is discoverable in `scout.py --help`
- No new pip dependency was added; `certifi` is a soft optional import only
- `python3 -m py_compile scout.py` passes
- Every new user-facing string is em-dash free
- `.oauth/` untouched
</success_criteria>

<output>
Create `.planning/quick/260816-crb-add-scout-keywords-command-with-free-dem/260816-crb-SUMMARY.md` when done
</output>
