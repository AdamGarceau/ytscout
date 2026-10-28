#!/usr/bin/env python3
"""
ytscout — a free, local, keyless replacement for the parts of vidIQ and TubeBuddy
that actually move the needle, grounded in Adam's consensus doctrine.

Data: yt-dlp (no API key). Brain: local gemma4:12b via ollama (optional). Deps: stdlib only.

Commands:
  scout outliers <handle> [--vs h1,h2,...] [--min-views N] [--top N] [--html]
                 [--shorts exclude|include|only] [--since-months 6] [--screen] [--drop-flagged]
  scout tiers [handles...] [--list L] [--input channels.json] [--tiers 1K-10K,10K-50K,50K-250K] [--json]
  scout social-audit <export.json> [--tz -5] [--topics 8] [--json]
  scout feed "<niche>" | --input tiles.json  [--my-title T] [--my-thumb P] [--tv | --grid yt|tv|ig]
  scout title "<proposed title>" [--ai]
  scout niche "<search query>" [--n N] [--html]
  scout keywords "<seed>" [--expand none|quick|full] [--top N] [--check N] [--n N] [--html]
  scout dash [--refresh] [--open]
  scout audit <handle> [--html]
  scout peers [--list ai] [--min-subs 1000] [--max-subs 50000] [--n 10] [--queries FILE]

Doctrine source: ~/content-engine/strategy/youtube-consensus-doctrine.md
"""
import sys, os, json, re, time, glob, argparse, statistics, html, math, ssl, urllib.request, urllib.parse

CACHE_DIR = os.path.expanduser("~/ytscout/.cache")
REPORT_DIR = os.path.expanduser("~/ytscout/reports")
CACHE_TTL = 6 * 3600  # 6 hours
SHORT_MAX_SEC = 60    # treat <=60s as a Short for outlier/audit purposes
OLLAMA_URL = "http://localhost:11434/api/generate"

os.makedirs(CACHE_DIR, exist_ok=True)
os.makedirs(REPORT_DIR, exist_ok=True)
WATCHLIST = os.path.expanduser("~/ytscout/watchlist.json")

# RPM (creator's actual $ per 1000 views) by niche — from the consensus doctrine's
# cross-verified tiers (vidIQ 6-video agreement). AdSense only; the real money is owned products.
RPM_TIERS = {
    "gaming": 2.0, "entertainment": 2.0, "vlog": 2.0, "lifestyle": 2.5,
    "family": 3.0, "homeschool": 3.5, "education": 5.0, "tech": 5.5,
    "tutorial": 5.5, "productivity": 6.0, "ai": 7.0, "software": 8.0,
    "business": 10.0, "finance": 12.0, "marketing": 10.0,
}
DEFAULT_RPM = 4.0

MIDROLL_SEC = 480  # 8:00 — the doctrine's mid-roll ad threshold (a 9-min video out-earned an 8-min one by $750)
MIDROLL_MULT = 1.6  # long videos carry mid-rolls = more ad inventory

def real_rpm(niche, override=None):
    """Adam's own RPM (from Studio) beats any niche guess. Order: explicit override > saved config > niche tier > default."""
    if override is not None:
        return override
    cfg = os.path.expanduser("~/ytscout/rpm.json")
    if os.path.exists(cfg):
        try:
            saved = json.load(open(cfg))
            if niche and niche in saved:
                return saved[niche]
            if "default" in saved:
                return saved["default"]
        except Exception:
            pass
    return RPM_TIERS.get(niche, DEFAULT_RPM) if niche else DEFAULT_RPM

def est_rev(views, rpm, dur=0):
    eff = rpm * MIDROLL_MULT if dur and dur >= MIDROLL_SEC else rpm
    return (views / 1000.0) * eff

def money(n):
    if n is None:
        return "?"
    if n >= 1000:
        return f"${n/1000:.1f}k"
    return f"${n:.0f}"

# ---------- yt-dlp data layer (cached) ----------

def _cache_path(key):
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", key)
    return os.path.join(CACHE_DIR, safe + ".json")

def _cache_get(key):
    p = _cache_path(key)
    if os.path.exists(p) and (time.time() - os.path.getmtime(p)) < CACHE_TTL:
        try:
            return json.load(open(p))
        except Exception:
            return None
    return None

def _cache_put(key, data):
    try:
        json.dump(data, open(_cache_path(key), "w"))
    except Exception:
        pass

def _ydl(url, limit, tolerant=False):
    # Non-flat extraction is the only reliable free way to get view counts.
    # Bounded to `limit` recent items so it stays fast; results are cached hard.
    import yt_dlp
    opts = {"quiet": True, "no_warnings": True, "skip_download": True,
            "extract_flat": False, "playlist_items": f"1-{limit}"}
    if tolerant:
        opts["ignoreerrors"] = True   # skip members-only / age-gated videos instead of failing the channel
    with yt_dlp.YoutubeDL(opts) as ydl:
        return ydl.extract_info(url, download=False)

def channel_dump(handle, limit=30, tolerant=False):
    """Return {name, subs, videos:[{id,title,views,dur,date}]}. Cached 6h."""
    handle = handle.lstrip("@")
    key = f"chan2_{handle}_{limit}"  # chan2: records carry likes/comments/desc for --screen
    cached = _cache_get(key)
    if cached:
        return cached
    sys.stderr.write(f"  … fetching @{handle} ({limit} recent, ~{limit}s first time; cached after)\n"); sys.stderr.flush()
    try:
        info = _ydl(f"https://www.youtube.com/@{handle}/videos", limit, tolerant)
    except Exception as e:
        return {"error": str(e), "name": handle, "subs": None, "videos": []}
    vids = []
    for e in (info.get("entries") or []):
        if not e:
            continue
        vids.append({
            "id": e.get("id"),
            "title": e.get("title") or "",
            "views": e.get("view_count") or 0,
            "dur": e.get("duration") or 0,
            "date": e.get("upload_date"),  # reliable in non-flat mode (YYYYMMDD)
            # for the fake-outlier screen: None = hidden likes / comments off
            "likes": e.get("like_count"),
            "comments": e.get("comment_count"),
            "desc": (e.get("description") or "")[:600],
        })
    out = {
        "name": info.get("channel") or info.get("uploader") or handle,
        "subs": info.get("channel_follower_count"),
        "videos": vids,
    }
    _cache_put(key, out)
    return out

def search_dump(query, n=20):
    key = f"search2_{query}_{n}"
    cached = _cache_get(key)
    if cached:
        return cached
    sys.stderr.write(f"  … searching \"{query}\" ({n} results, ~{n}s first time; cached after)\n"); sys.stderr.flush()
    try:
        info = _ydl(f"ytsearch{n}:{query}", n)
    except Exception as e:
        return {"error": str(e), "results": []}
    res = []
    for e in (info.get("entries") or []):
        if not e:
            continue
        res.append({
            "id": e.get("id"),
            "title": e.get("title") or "",
            "views": e.get("view_count") or 0,
            "dur": e.get("duration") or 0,
            "channel": e.get("channel") or e.get("uploader") or "?",
            "subs": e.get("channel_follower_count"),
            "handle": (e.get("uploader_id") or "").lstrip("@"),
            "channel_id": e.get("channel_id"),
        })
    out = {"results": res}
    _cache_put(key, out)
    return out

# ---------- autocomplete demand layer (keyless) ----------

_SSL_CTX = None

def _ssl_ctx():
    """Memoized SSL context. Prefers certifi's cert bundle (this box's default Python cert
    store fails on outbound HTTPS); falls back to a plain verified default context if certifi
    isn't installed. Certificate verification is never disabled in either branch."""
    global _SSL_CTX
    if _SSL_CTX is None:
        try:
            import certifi
            _SSL_CTX = ssl.create_default_context(cafile=certifi.where())
        except ImportError:
            _SSL_CTX = ssl.create_default_context()
    return _SSL_CTX

def _fetch_json(url, timeout=6):
    """GET url, return parsed JSON or None. Never raises."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (ytscout)"})
        with urllib.request.urlopen(req, timeout=timeout, context=_ssl_ctx()) as r:
            raw = r.read()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("latin-1")
        return json.loads(text)
    except Exception:
        return None

def autocomplete(q):
    """Ordered list of YouTube autocomplete suggestion strings for one query. Cached 6h."""
    cache_key = "ac_" + q
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached
    qs = urllib.parse.urlencode({"client": "firefox", "ds": "yt", "q": q})
    data = _fetch_json(f"https://suggestqueries.google.com/complete/search?{qs}")
    ok = isinstance(data, list) and len(data) >= 2 and isinstance(data[1], list)
    out = [s for s in data[1] if isinstance(s, str) and s] if ok else []
    if data is not None:
        # a real response came back (even if empty after validation) — safe to cache
        _cache_put(cache_key, out)
    time.sleep(0.12)
    return out

def _expansion_queries(seed, mode):
    quick = [seed, f"how to {seed}", f"what is {seed}", f"why {seed}", f"best {seed}",
             f"{seed} vs", f"{seed} for", f"{seed} without", f"{seed} tutorial"]
    if mode == "full":
        return quick + [f"{seed} {c}" for c in "abcdefghijklmnopqrstuvwxyz"]
    if mode == "none":
        return [seed]
    return quick

EXPANSIONS = {"none": 1, "quick": 9, "full": 35}  # requests each mode makes

def keyword_demand(seed, mode="quick"):
    """Relative demand signal built from how often and how early a suggestion surfaces across
    autocomplete expansions of the seed. Returns
    {"keywords": [(kw, demand 0-100, hits), ...] sorted desc, "queries": int, "failures": int}."""
    queries = _expansion_queries(seed, mode)
    points, hits, failures = {}, {}, 0
    for q in queries:
        sugg = autocomplete(q)
        if not sugg:
            failures += 1
            continue
        for r, kw in enumerate(sugg):
            points[kw] = points.get(kw, 0.0) + 1.0 / (1 + r)
            hits[kw] = hits.get(kw, 0) + 1
    if not points:
        return {"keywords": [], "queries": len(queries), "failures": failures}
    raw = {kw: pts * (1 + 0.15 * (hits[kw] - 1)) for kw, pts in points.items()}
    top = max(raw.values()) or 1.0
    scored = sorted(
        ((kw, round(100 * v / top), hits[kw]) for kw, v in raw.items()),
        key=lambda x: x[1], reverse=True,
    )
    return {"keywords": scored, "queries": len(queries), "failures": failures}

def keyword_competition(kw, n):
    """Computed competition score (0-100, HIGHER = HARDER) from who actually ranks for kw,
    on log scales so one megachannel cannot saturate the number. Returns None when search_dump
    errors or has no long-form results, so the caller renders "n/a" instead of crashing."""
    d = search_dump(kw, n)
    if d.get("error"):
        return None
    res = [r for r in d["results"] if r["dur"] > SHORT_MAX_SEC]
    if not res:
        return None
    views = [r["views"] for r in res]
    subs = [r.get("subs") or 0 for r in res]
    med_views = statistics.median(views)
    med_subs = statistics.median(subs)
    views_desc = sorted(views, reverse=True)
    total = sum(views_desc) or 1
    top3_share = sum(views_desc[:3]) / total
    small_share = sum(1 for s in subs if s < 100000) / len(subs)
    subs_term = min(1.0, math.log10(max(med_subs, 1)) / 6.0)   # 1M subs saturates
    views_term = min(1.0, math.log10(max(med_views, 1)) / 7.0)  # 10M views saturates
    score = round(100 * (0.45 * subs_term + 0.35 * views_term + 0.20 * top3_share))
    score = max(0, min(100, score))
    band = "LOW" if score < 35 else ("HIGH" if score > 65 else "MED")
    return {"score": score, "band": band, "med_views": med_views, "med_subs": med_subs,
            "top3_share": top3_share, "small_share": small_share}

def cmd_keywords(args):
    seed = args.seed
    print(f"\n\033[1mKEYWORD RESEARCH\033[0m  \"{seed}\"\n")
    d = keyword_demand(seed, args.expand)
    if not d["keywords"]:
        print("  ! No keyword data. The network may be unreachable, or autocomplete returned no "
              "suggestions for this seed. Nothing to rank.\n")
        return
    top_kws = d["keywords"][:args.top]
    check_n = max(0, min(args.check, len(top_kws)))
    rows = []
    for i, (kw, demand, hits) in enumerate(top_kws):
        comp = keyword_competition(kw, args.n) if i < check_n else None
        if comp:
            comp_s, band_s = str(comp["score"]), comp["band"]
            mv, ms = human(comp["med_views"]), human(comp["med_subs"])
        else:
            comp_s = band_s = mv = ms = "n/a"
        rows.append([kw[:44], str(demand), str(hits), comp_s, band_s, mv, ms])
    print(table(rows, ["Keyword", "Demand", "Hits", "Comp", "Band", "MedViews", "MedSubs"]))
    q = d['queries']
    print(f"\n  Demand is relative, built from how often and how early a phrase surfaces in YouTube")
    print(f"  autocomplete across {q} {'expansion' if q == 1 else 'expansions'} ({args.expand} mode). "
          f"It is not a search volume.")
    if check_n:
        print(f"  Comp is computed from who actually ranks for the phrase: median subscriber size of")
        print(f"  ranking channels, their median views, and how concentrated views are in the top 3.")
        print(f"  LOW means small channels are ranking, HIGH means big channels own the term.")
        print(f"  The top {check_n} {'keyword' if check_n == 1 else 'keywords'} got a competition read "
              f"(--check {args.check}, about")
        print(f"  {args.n}s each on a cold cache). Rows past that show n/a.\n")
    else:
        print(f"  Competition was not read this run (--check 0). Raise --check to score how hard")
        print(f"  the top keywords are to rank for.\n")
    if args.html:
        _write_keywords_html(seed, rows, d, args)

def _write_keywords_html(seed, rows, d, args):
    path = os.path.join(REPORT_DIR, "keywords.html")
    trs = "".join(
        "<tr>" + "".join(f"<td>{html.escape(str(c))}</td>" for c in r) + "</tr>"
        for r in rows)
    doc = f"""<!doctype html><meta charset=utf-8><title>keywords: {html.escape(seed)}</title>
<style>body{{font:15px/1.5 -apple-system,system-ui,sans-serif;max-width:900px;margin:2rem auto;padding:0 1rem}}
h1{{font-size:1.4rem}}table{{border-collapse:collapse;width:100%}}td,th{{padding:.4rem .6rem;border-bottom:1px solid #ddd;text-align:left}}
th{{font-size:.8rem;text-transform:uppercase;color:#666}}</style>
<h1>Keyword research: {html.escape(seed)}</h1>
<p>Demand is relative, from {d['queries']} YouTube autocomplete expansions ({html.escape(args.expand)} mode),
not a search volume. Comp is computed from who actually ranks (median subs, median views, top 3
concentration). LOW means small channels are ranking, HIGH means big channels own the term.</p>
<table><tr><th>Keyword</th><th>Demand</th><th>Hits</th><th>Comp</th><th>Band</th><th>MedViews</th><th>MedSubs</th></tr>{trs}</table>"""
    open(path, "w").write(doc)
    print(f"  → HTML report: {path}")

# ---------- ollama (optional brain) ----------

def ollama(prompt, num_ctx=8192):
    body = json.dumps({"model": "gemma4:12b", "prompt": prompt, "stream": False,
                       "think": False, "options": {"num_ctx": num_ctx, "temperature": 0.4}}).encode()
    req = urllib.request.Request(OLLAMA_URL, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read())["response"].strip()
    except Exception as e:
        return f"[ollama unavailable: {e}]"

# ---------- formatting helpers ----------

def human(n):
    if n is None:
        return "?"
    n = int(n)
    for unit, div in (("M", 1_000_000), ("K", 1_000)):
        if n >= div:
            return f"{n/div:.1f}{unit}"
    return str(n)

def table(rows, headers):
    cols = list(zip(*([headers] + rows))) if rows else [[h] for h in headers]
    widths = [max(len(str(c)) for c in col) for col in cols]
    line = lambda r: "  ".join(str(c).ljust(w) for c, w in zip(r, widths))
    out = [line(headers), "  ".join("-" * w for w in widths)]
    out += [line(r) for r in rows]
    return "\n".join(out)

EMOJI_RE = re.compile(
    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F000-\U0001F0FF\U00002190-\U000021FF\U00002B00-\U00002BFF]")

# ---------- shared filters: Shorts mode, recency, fake-outlier screen ----------

SHORTS_MODES = ("exclude", "include", "only")
DAYS_PER_MONTH = 30.44
DEFAULT_SINCE_MONTHS = 6  # outlier commands only look at the last 6 months unless told otherwise

def _now():
    return time.time()  # one seam so tests can pin "today"

def tag_shorts(vids):
    """Sets is_short on every record. Unknown duration (0) counts as a Short, same as the old
    `dur > SHORT_MAX_SEC` long-form filter, so exclude mode keeps exactly what it always kept."""
    for v in vids:
        v["is_short"] = (v.get("dur") or 0) <= SHORT_MAX_SEC
    return vids

def apply_shorts(vids, mode="exclude"):
    """exclude = long-form only (the historical default), include = everything, only = Shorts only."""
    tag_shorts(vids)
    if mode == "include":
        return list(vids)
    if mode == "only":
        return [v for v in vids if v["is_short"]]
    return [v for v in vids if not v["is_short"]]

def video_age_days(v, now=None):
    try:
        return ((now if now is not None else _now()) - time.mktime(time.strptime(v["date"], "%Y%m%d"))) / 86400
    except Exception:
        return None

def apply_since(vids, months, now=None):
    """Keeps videos uploaded in the last `months` months. 0/None turns the filter off.
    Undated videos are kept: there is nothing to judge them on."""
    if not months:
        return list(vids)
    out = []
    for v in vids:
        age = video_age_days(v, now)
        if age is None or age <= months * DAYS_PER_MONTH:
            out.append(v)
    return out

# Fake-outlier screen thresholds. Subs per 1k views: a legit 20x-subs "gold" outlier sits at 50.
SCREEN_SPK_LOW = 5.0        # under 5 subs per 1k views = views 200x+ subs (bought views, Shorts-feed spill)
SCREEN_SPK_HIGH = 100000.0  # channel median over 100k = typical video under 1% of subs (bought/dead subs)
SCREEN_BATCH_MIN = 3        # this many uploads on one day = batch-dumped content
FACELESS_RE = re.compile(
    r"\b(ai[- ]?voice(?:d|over)?|ai[- ]generated|ai narrat\w*|narrated by ai|voiced by ai|made with ai|"
    r"text[- ]to[- ]speech|tts|elevenlabs|invideo|pictory|synthesia|faceless|"
    r"reddit stor(?:y|ies)|aita|no copyright (?:music|footage)|stock footage)\b", re.I)

def screen_video(v, channel_videos, subs):
    """Reasons this outlier may be fake or not portable, as short tags. Empty list = clean.
    `channel_videos` is the channel's full recent list (for the batch-upload count)."""
    reasons = []
    views = v.get("views") or 0
    if subs and views:
        spk = subs * 1000 / views
        if spk < SCREEN_SPK_LOW:
            reasons.append(f"subs/1k {spk:.1f}")
    ch_views = [x.get("views") or 0 for x in channel_videos if x.get("views")]
    if subs and ch_views and subs * 1000 / statistics.median(ch_views) > SCREEN_SPK_HIGH:
        reasons.append("subs>>views")
    # key present with None = yt-dlp saw the field and it was hidden; key absent = unknown
    if "likes" in v and v["likes"] is None:
        reasons.append("likes hidden")
    if "comments" in v and v["comments"] is None:
        reasons.append("comments off")
    if v.get("date"):
        same_day = sum(1 for x in channel_videos if x.get("date") == v["date"])
        if same_day >= SCREEN_BATCH_MIN:
            reasons.append(f"batch x{same_day}")
    m = FACELESS_RE.search(f"{v.get('title') or ''}\n{v.get('desc') or ''}")
    if m:
        reasons.append(f"faceless:{m.group(0).lower()}")
    return reasons

SCREEN_LEGEND = ("Flags: subs/1k = subscribers per 1k views under 5 (views 200x+ subs: bought views or Shorts spill); "
                 "subs>>views = channel's typical video under 1% of subs (bought/dead subs, median is suspect); "
                 "likes hidden; comments off; batch xN = N uploads the same day; faceless:<term> = AI-voice/faceless "
                 "pattern in title/description. A flag is a reason to look, not a verdict.")

def _add_shared_filters(parser, since_default=DEFAULT_SINCE_MONTHS, screen=False):
    parser.add_argument("--shorts", choices=SHORTS_MODES, default="exclude",
                        help="Shorts (<=60s): exclude (default, long-form only), include, or only")
    parser.add_argument("--since-months", type=float, default=since_default,
                        help=f"only videos uploaded in the last N months, 0 = no limit (default {since_default})")
    if screen:
        parser.add_argument("--screen", action="store_true",
                            help="flag suspicious outliers (fake views/subs, hidden likes, batch uploads, AI-voice/faceless)")
        parser.add_argument("--drop-flagged", action="store_true", help="drop flagged rows (implies --screen)")

# ---------- Command: outliers (the crown jewel) ----------

def cmd_outliers(args):
    handles = [args.handle] + (args.vs.split(",") if args.vs else [])
    handles = [h.strip().lstrip("@") for h in handles if h.strip()]
    print(f"\n\033[1mOUTLIER FINDER\033[0m  (view-to-subscriber ratio = the #1 idea-validation signal, 6 corpora agree)\n")
    shorts = getattr(args, "shorts", "exclude")
    since = getattr(args, "since_months", DEFAULT_SINCE_MONTHS)
    drop = getattr(args, "drop_flagged", False)
    screen = getattr(args, "screen", False) or drop
    kind = {"exclude": "long-form videos", "include": "videos", "only": "Shorts"}[shorts]
    all_rows = []
    html_rows = []
    for h in handles:
        ch = channel_dump(h, limit=args.scan)
        if ch.get("error"):
            print(f"  ! {h}: {ch['error']}")
            continue
        subs = ch.get("subs") or 0
        vids = [v for v in apply_since(apply_shorts(ch["videos"], shorts), since) if v["views"] >= args.min_views]
        if not vids:
            window = f" in the last {since:g} months" if since else ""
            print(f"  ! {h}: no {kind} above {args.min_views} views{window}")
            continue
        med = statistics.median([v["views"] for v in vids]) or 1
        for v in vids:
            v["ch"] = ch["name"]
            v["subs"] = subs
            # two multipliers the doctrine names:
            v["vsr"] = round(v["views"] / subs, 2) if subs else None   # view-to-subscriber (AmplifyViews)
            v["osc"] = round(v["views"] / med, 2)                       # outlier score vs channel median (vidIQ/One10)
            if screen:
                v["flags"] = screen_video(v, ch["videos"], subs)
        all_rows.extend(vids)
    dropped = 0
    if drop:
        dropped = sum(1 for v in all_rows if v["flags"])
        all_rows = [v for v in all_rows if not v["flags"]]
    if not all_rows:
        print("  No data. Check the handles (use the exact @handle)." if not dropped
              else f"  All {dropped} rows were flagged and dropped (--drop-flagged).")
        return
    # rank: prefer view-to-sub where available, else outlier score
    rpm = real_rpm(args.niche, getattr(args, "rpm", None))
    ranked = sorted(all_rows, key=lambda v: (v["vsr"] or 0, v["osc"]), reverse=True)[:args.top]
    rows = []
    for v in ranked:
        vsr = f"{v['vsr']}x" if v["vsr"] is not None else "—"
        v["rev"] = est_rev(v["views"], rpm, v["dur"])
        row = [vsr, f"{v['osc']}x", human(v["views"]), money(v["rev"]),
               human(v["subs"]), v["ch"][:15], v["title"][:52]]
        if shorts == "include":
            row.insert(0, "S" if v["is_short"] else "")
        if screen:
            row.append(", ".join(v["flags"]) or "ok")
        rows.append(row)
        html_rows.append(v)
    headers = ["V/Sub", "vsMed", "Views", "Est$", "Subs", "Channel", "Title"]
    if shorts == "include":
        headers.insert(0, "Short")
    if screen:
        headers.append("Flags")
    print(table(rows, headers))
    print(f"\n  V/Sub = views ÷ subscribers (5x+ strong, 20x gold — AmplifyViews).  vsMed = views ÷ channel median (3x+ = vidIQ outlier).")
    if since:
        print(f"  Window: uploads in the last {since:g} months (--since-months 0 for all). Shorts: {shorts}.")
    if screen:
        print(f"  {SCREEN_LEGEND}")
        if dropped:
            print(f"  Dropped {dropped} flagged {'row' if dropped == 1 else 'rows'} (--drop-flagged).")
    print(f"  Est$ = est. AdSense at ${rpm:.0f} RPM ({args.niche or 'default'} niche) — the FLOOR. Owned products earn far more (doctrine).")
    print(f"  These titles are PROVEN ideas. Port the concept into your niche (Niche Comparison Theory).\n")

    if args.ai and ranked:
        top = ranked[0]
        print("\033[1m  Porting the #1 outlier into your niche (gemma4:12b):\033[0m")
        prompt = (f"This YouTube video is an outlier: \"{top['title']}\" got {top['views']} views on a "
                  f"channel with {top['subs']} subscribers. Adam runs two channels: a family/homeschool "
                  f"channel (Brooke+Adam) and an AI 'build software with Claude' channel. Give 3 video title "
                  f"ideas that port this proven concept into EACH of his two niches. Plain text, no emojis, "
                  f"6-8 words per title, keep the psychological hook that made the original work.")
        print("  " + ollama(prompt).replace("\n", "\n  ") + "\n")

    if args.html:
        write_outlier_html(handles, html_rows, screen)

def write_outlier_html(handles, vids, screen=False):
    path = os.path.join(REPORT_DIR, "outliers.html")
    flag_td = lambda v: f"<td>{html.escape(', '.join(v.get('flags') or []) or 'ok')}</td>" if screen else ""
    rows = "".join(
        f"<tr><td>{v['vsr'] or '—'}x</td><td>{v['osc']}x</td><td>{human(v['views'])}</td>"
        f"<td>{human(v['subs'])}</td><td>{html.escape(v['ch'])}</td>"
        f"<td><a href='https://youtu.be/{v['id']}'>{html.escape(v['title'])}</a></td>{flag_td(v)}</tr>"
        for v in vids)
    flag_th = "<th>Flags</th>" if screen else ""
    doc = f"""<!doctype html><meta charset=utf-8><title>ytscout outliers</title>
<style>body{{font:15px/1.5 -apple-system,system-ui,sans-serif;max-width:1000px;margin:2rem auto;padding:0 1rem}}
h1{{font-size:1.4rem}}table{{border-collapse:collapse;width:100%}}td,th{{padding:.4rem .6rem;border-bottom:1px solid #ddd;text-align:left}}
th{{font-size:.8rem;text-transform:uppercase;color:#666}}a{{color:#0645ad;text-decoration:none}}</style>
<h1>Outlier finder</h1><p>Channels: {html.escape(', '.join(handles))}. V/Sub = views ÷ subscribers (5x+ strong, 20x gold). vsMed = views ÷ channel median (3x+ = outlier).</p>
<table><tr><th>V/Sub</th><th>vs Median</th><th>Views</th><th>Subs</th><th>Channel</th><th>Title</th>{flag_th}</tr>{rows}</table>"""
    open(path, "w").write(doc)
    print(f"  → HTML report: {path}")

# ---------- Command: title analyzer ----------

FRAMES = {
    "witness": r"\b(caught|on camera|footage|watch|i saw|exposed|watched)\b",
    "transformation": r"\b(turn(ed|ing|s)? .* into|from .* to |transform|became|replaced|makes? .* (into|from))\b",
    "access": r"\b(inside|behind the scenes|secret|how .* actually|the truth about|the real reason|only job)\b",
    "insider": r"\b(nobody|no one|what .* won'?t tell|they don'?t want|hidden|what .* isn'?t telling)\b",
    "credibility": r"\b(after \d+ years|\d+ years of|i (built|made|grew|spent|studied|tried|used))\b",
    "forbidden": r"\b(banned|illegal|not allowed|forbidden|shouldn'?t|can'?t)\b",
    "negative": r"\b(mistake|wrong|stop|never|worst|kill(s|ed|ing)?|ruin|fail|dead|broke|don'?t|bad|hate|avoid|destroy|dumb|boring)\b",
    "question": r"\?",
    "number-outcome": r"\$?\d[\d,\.]*\s*(k|m|subs|subscribers|days|hours|dollars|/mo|per|month)",
}

def cmd_title(args):
    t = args.text.strip()
    words = t.split()
    chars = len(t)
    emojis = EMOJI_RE.findall(t)
    has_number = bool(re.search(r"\d", t))
    frames = [name for name, pat in FRAMES.items() if re.search(pat, t, re.I)]

    score = 100
    notes = []
    # word count (doctrine: 6-7 words ideal, from the 9M-video study)
    wc = len(words)
    if 5 <= wc <= 8:
        notes.append(("ok", f"{wc} words — in the 6-7 word sweet spot (9M-video study)"))
    elif wc < 5:
        score -= 10; notes.append(("warn", f"{wc} words — a bit short; 6-7 is the data-backed sweet spot"))
    else:
        score -= 15; notes.append(("warn", f"{wc} words — long; 16+ words is the worst performer, trim toward 6-7"))
    # char count (<60 ideal, <30 bonus, >70 truncates on mobile)
    if chars <= 30:
        notes.append(("ok", f"{chars} chars — under 30, the 2026 data study's top view bucket"))
    elif chars <= 60:
        notes.append(("ok", f"{chars} chars — under 60, clean on mobile"))
    elif chars <= 70:
        score -= 8; notes.append(("warn", f"{chars} chars — trim under 60 so mobile doesn't cut it"))
    else:
        score -= 18; notes.append(("bad", f"{chars} chars — will truncate on mobile; cut under 60"))
    # emojis on long-form (data study: -11% views)
    if emojis:
        score -= 12; notes.append(("bad", f"emoji(s) {''.join(emojis)} — drop for long-form (-11% views in the 128M-video study; fine on Shorts)"))
    else:
        notes.append(("ok", "no emojis — correct for long-form reach"))
    # numbers (data study: no-number titles got 11% more views on long-form; but number-outcome frames still win)
    if has_number and "number-outcome" not in frames:
        score -= 5; notes.append(("warn", "has a number that isn't a payoff — the 4M-title study found bare numbers underperform; make it an outcome ($10k, 1000 subs) or cut it"))
    # frames (doctrine: stack 3-4 psychological frames; top titles stack)
    if len(frames) >= 3:
        notes.append(("ok", f"stacks {len(frames)} frames ({', '.join(frames)}) — top titles stack 3-4"))
    elif len(frames) >= 1:
        score -= 6; notes.append(("warn", f"only {len(frames)} frame ({', '.join(frames)}) — stack more (witness, transformation, access, insider, credibility, forbidden, negative-emotion)"))
    else:
        score -= 18; notes.append(("bad", "no psychological frame detected — the title states, it doesn't hook. Add a frame."))
    score = max(0, min(100, score))

    color = "\033[32m" if score >= 80 else "\033[33m" if score >= 60 else "\033[31m"
    print(f"\n\033[1mTITLE ANALYZER\033[0m")
    print(f'  "{t}"')
    print(f"  {color}Score: {score}/100\033[0m\n")
    ic = {"ok": "\033[32m✓\033[0m", "warn": "\033[33m~\033[0m", "bad": "\033[31m✗\033[0m"}
    for kind, msg in notes:
        print(f"  {ic[kind]} {msg}")
    if args.ai:
        print("\n\033[1m  5 stronger variants (gemma4:12b, doctrine-grounded):\033[0m")
        prompt = (f'Rewrite this YouTube title 5 ways, each STRONGER: "{t}". Rules from real data studies: '
                  f'6-7 words, under 60 characters, NO emojis, stack psychological frames (witness/transformation/'
                  f'access/insider/credibility/forbidden/negative-emotion), curiosity over information, specific '
                  f'outcomes not bare numbers. Output 5 titles only, numbered, no commentary.')
        print("  " + ollama(prompt).replace("\n", "\n  ") + "\n")
    print()

# ---------- Command: niche research ----------

def cmd_niche(args):
    print(f"\n\033[1mNICHE / KEYWORD RESEARCH\033[0m  \"{args.query}\"\n")
    d = search_dump(args.query, args.n)
    if d.get("error"):
        print("  ! " + d["error"]); return
    res = apply_shorts(d["results"], getattr(args, "shorts", "exclude"))
    if not res:
        print("  No results for this Shorts mode." if getattr(args, "shorts", "exclude") != "exclude"
              else "  No long-form results."); return
    views = sorted([r["views"] for r in res], reverse=True)
    total = sum(views) or 1
    top3_share = sum(views[:3]) / total
    med = statistics.median(views)
    rows = []
    for r in sorted(res, key=lambda x: x["views"], reverse=True)[:15]:
        mult = round(r["views"] / med, 1) if med else 0
        rows.append([human(r["views"]), f"{mult}x", r["channel"][:20], r["title"][:56]])
    print(table(rows, ["Views", "vsMed", "Channel", "Title"]))
    print(f"\n  Median views on page: {human(med)}   |   Top-3 own {top3_share*100:.0f}% of the views")
    if top3_share > 0.7:
        print("  \033[33mSaturated at the top\033[0m — a few big channels dominate. Bend the angle (Niche Comparison Theory) rather than compete head-on.")
    else:
        print("  \033[32mViews are spread\033[0m — room for a well-packaged newcomer. Model the highest vsMed title.")
    print("  Note: this view distribution is the saturation read for one term. Run scout keywords")
    print(f"  \"{args.query}\" for relative demand from YouTube autocomplete plus a computed competition")
    print("  score across related terms, no API key needed.\n")
    if args.html:
        path = os.path.join(REPORT_DIR, "niche.html")
        rows_h = "".join(f"<tr><td>{human(r['views'])}</td><td>{html.escape(r['channel'])}</td>"
                         f"<td><a href='https://youtu.be/{r['id']}'>{html.escape(r['title'])}</a></td></tr>"
                         for r in sorted(res, key=lambda x: x['views'], reverse=True)[:15])
        open(path, "w").write(f"<!doctype html><meta charset=utf-8><title>niche: {html.escape(args.query)}</title>"
            f"<style>body{{font:15px/1.5 system-ui;max-width:900px;margin:2rem auto}}td{{padding:.3rem .6rem;border-bottom:1px solid #ddd}}a{{color:#0645ad}}</style>"
            f"<h1>Niche: {html.escape(args.query)}</h1><table>{rows_h}</table>")
        print(f"  → HTML report: {path}\n")

# ---------- Command: channel audit ----------

# doctrine length zones (Nate Black TimeZone), seconds
def zone(dur):
    m = dur / 60
    if m < 4: return "meme(0-4m)"
    if m < 6: return "moment(4-6m)*dead"
    if m < 8: return "rare(6-8m)"
    if m < 12: return "standard(8-12m)"
    if m < 16: return "stretch(12-16m)*dead"
    if m < 20: return "odd(16-20m)*dead"
    if m < 30: return "highvalue(20-30m)"
    return "extra(30m+)"

def cmd_audit(args):
    ch = channel_dump(args.handle)
    if ch.get("error"):
        print("  ! " + ch["error"]); return
    subs = ch.get("subs") or 0
    longs = [v for v in ch["videos"] if v["dur"] > SHORT_MAX_SEC]
    shorts = [v for v in ch["videos"] if v["dur"] <= SHORT_MAX_SEC]
    print(f"\n\033[1mCHANNEL AUDIT\033[0m  {ch['name']}  ({human(subs)} subs, {len(ch['videos'])} recent videos)\n")
    if not longs:
        print("  No long-form videos found."); return
    views = [v["views"] for v in longs]
    med = statistics.median(views)
    best = max(longs, key=lambda v: v["views"])
    titlelens = [len(v["title"]) for v in longs]
    long_titles = [v for v in longs if len(v["title"]) > 60]
    zones = {}
    for v in longs:
        zones[zone(v["dur"])] = zones.get(zone(v["dur"]), 0) + 1
    shorts_ratio = len(shorts) / max(1, len(ch["videos"]))

    print(f"  Median long-form views: {human(med)}")
    print(f"  Best recent: {human(best['views'])} — \"{best['title'][:60]}\"")
    print(f"  Best-to-median ratio: {best['views']/med:.1f}x  " +
          ("(healthy outlier)" if best['views']/med >= 3 else "(no breakout recently — model other niches)"))
    print(f"  Shorts / long-form mix: {shorts_ratio*100:.0f}% Shorts  " +
          ("(near the 30/70 doctrine target)" if 0.2 <= shorts_ratio <= 0.4 else "(doctrine target is ~30% Shorts / 70% long)"))
    # revenue estimate
    rpm = real_rpm(args.niche, getattr(args, "rpm", None))
    recent_views = sum(v["views"] for v in longs)
    # rough monthly: if we can date them, use last-30-day views; else annualize the median as a floor
    dated = [v for v in longs if v.get("date")]
    per_video_rev = est_rev(med, rpm, med and 500)  # assume typical long-form gets midroll
    print(f"\n  \033[1mMoney (est. AdSense at ${rpm:.0f} RPM, {args.niche or 'default'} niche):\033[0m")
    print(f"  Typical video (~{human(med)} views): {money(per_video_rev)} in ad revenue")
    print(f"  Best recent (~{human(best['views'])} views): {money(est_rev(best['views'], rpm, best['dur']))}")
    print(f"  These {len(longs)} recent long-forms: ~{money(est_rev(recent_views, rpm, 500))} total AdSense")
    print(f"  \033[2mAdSense is the FLOOR. Doctrine: 1,000 superfans × $100/yr = $100k — owned products (guides, community, Nudge) beat ad revenue at every size.\033[0m")
    print()
    print("  \033[1mFlags (per consensus doctrine):\033[0m")
    if long_titles:
        print(f"  \033[33m~\033[0m {len(long_titles)}/{len(longs)} titles over 60 chars — will truncate on mobile. e.g. \"{long_titles[0]['title'][:70]}...\"")
    else:
        print("  \033[32m✓\033[0m titles are within 60 chars")
    dead = sum(zones.get(z, 0) for z in zones if "*dead" in z)
    if dead:
        print(f"  \033[33m~\033[0m {dead} videos land in length dead-zones (4-6m, 12-16m, 16-20m). Aim 8-12m or 20-30m (Nate Black TimeZone).")
    else:
        print("  \033[32m✓\033[0m video lengths avoid the dead zones")
    cons = statistics.pstdev(views) / med if med else 0
    if cons > 1.5:
        print(f"  \033[33m~\033[0m view counts are erratic (spread {cons:.1f}x median) — packaging or niche coherence is inconsistent")
    else:
        print(f"  \033[32m✓\033[0m view counts are relatively consistent")
    print(f"\n  Length distribution: " + ", ".join(f"{z}:{n}" for z, n in sorted(zones.items(), key=lambda x:-x[1])))
    print("\n  \033[2mHonest limit: CTR, retention, and impressions need OAuth to YOUR OWN channel's Analytics API.")
    print("  ytscout audits any channel's PUBLIC data (views, titles, lengths, cadence). Private metrics = a future --mine mode.\033[0m\n")

# ---------- Command: feed (see your title+thumbnail among REAL niche videos) ----------

def _yt_views(n):
    if n is None or n == 0:
        return "NEW"
    for u, d in (("M", 1_000_000), ("K", 1_000)):
        if n >= d:
            return f"{n/d:.1f}{u} views"
    return f"{n} views"

def _b64_img(path):
    import base64, mimetypes
    try:
        mt = mimetypes.guess_type(path)[0] or "image/jpeg"
        return f"data:{mt};base64," + base64.b64encode(open(path, "rb").read()).decode()
    except Exception:
        return None

def _fmt_dur(d):
    """Seconds -> '12:34' / '1:02:03'. Strings pass through ('12:34'), anything else -> ''."""
    if isinstance(d, (int, float)) and d > 0:
        d = int(d)
        h, m, s = d // 3600, d % 3600 // 60, d % 60
        return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
    return d if isinstance(d, str) else ""

_SAFE_SRC_RE = re.compile(r"^(https?://|data:image/)", re.I)

def _feed_src(thumb, base_dir="."):
    """Image source for a tile. http(s) and data:image pass through; a local path is embedded
    as base64 so the HTML stays self-contained; anything else (javascript:, a missing file)
    returns None and renders as a placeholder."""
    if not thumb or not isinstance(thumb, str):
        return None
    if _SAFE_SRC_RE.match(thumb):
        return thumb
    p = thumb if os.path.isabs(thumb) else os.path.join(base_dir, thumb)
    return _b64_img(p) if os.path.isfile(p) else None

def _feed_card(t, base_dir=".", mine=False):
    views = t.get("views")
    return {"title": str(t.get("title") or ""), "channel": str(t.get("channel") or ""),
            "views_str": str(t.get("views_str") or (_yt_views(views) if isinstance(views, (int, float)) else "")),
            "age": str(t.get("age") or ""), "dur": _fmt_dur(t.get("dur")),
            "thumb": _feed_src(t.get("thumb"), base_dir), "carousel": bool(t.get("carousel")), "mine": mine}

def load_feed_json(path):
    """Competitor tiles from JSON: a bare list of tiles, or
    {"label", "profile": {...ig header...}, "candidate": {tile}, "tiles": [tile, ...]}.
    Tile keys: title, channel, views (int) or views_str, age, dur (seconds or "12:34"),
    thumb (URL, or a path relative to the JSON file), carousel (ig grid icon).
    Returns (cards, candidate_or_None, label, profile)."""
    data = json.load(open(path, encoding="utf-8"))
    base = os.path.dirname(os.path.abspath(path))
    meta = data if isinstance(data, dict) else {"tiles": data}
    cards = [_feed_card(t, base) for t in (meta.get("tiles") or []) if isinstance(t, dict)]
    cand = meta.get("candidate")
    cand = _feed_card(cand, base, mine=True) if isinstance(cand, dict) else None
    return cards, cand, meta.get("label"), meta.get("profile") or {}

def _feed_sub(c):
    return " · ".join(html.escape(x) for x in (c["channel"], c["views_str"], c.get("age") or "") if x)

def _feed_yt_html(cards, label):
    def card_html(c):
        cls = "card mine" if c.get("mine") else "card"
        if c["thumb"]:
            thumb = f"<img class=thumb src='{html.escape(c['thumb'], quote=True)}' alt=''>"
        else:
            thumb = f"<div class='thumb ph'>{html.escape(c['title'][:40])}</div>"
        badge = "<span class=badge>YOU</span>" if c.get("mine") else ""
        return (f"<div class='{cls}'>{thumb}{badge}"
                f"<div class=meta><div class=title>{html.escape(c['title'])}</div>"
                f"<div class=sub>{_feed_sub(c)}</div></div></div>")

    grid = "".join(card_html(c) for c in cards)
    return f"""<!doctype html><meta charset=utf-8><title>ytscout feed — {html.escape(label)}</title>
<meta name=viewport content="width=device-width,initial-scale=1">
<style>
:root{{--bg:#0f0f0f;--fg:#f1f1f1;--sub:#aaa}}
@media(prefers-color-scheme:light){{:root{{--bg:#fff;--fg:#0f0f0f;--sub:#606060}}}}
body{{margin:0;background:var(--bg);color:var(--fg);font:14px/1.4 Roboto,-apple-system,system-ui,sans-serif}}
header{{padding:14px 20px;font-size:15px;color:var(--sub);border-bottom:1px solid #8883}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:16px 12px;padding:20px}}
.card{{cursor:pointer;position:relative}}
.thumb{{width:100%;aspect-ratio:16/9;object-fit:cover;border-radius:12px;display:block;background:#333}}
.thumb.ph{{display:flex;align-items:center;justify-content:center;text-align:center;padding:8px;color:#ddd;
  background:linear-gradient(135deg,#3a3a3a,#555);font-weight:600;box-sizing:border-box}}
.meta{{padding:10px 2px}}
.title{{font-weight:600;font-size:15px;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}}
.sub{{color:var(--sub);font-size:13px;margin-top:3px}}
.mine .thumb{{outline:3px solid #3ea6ff;outline-offset:2px}}
.badge{{position:absolute;top:8px;left:8px;background:#3ea6ff;color:#001;font-weight:700;
  font-size:11px;padding:2px 7px;border-radius:4px;letter-spacing:.5px}}
</style>
<header>Test feed · niche: <b>{html.escape(label)}</b> · your card is outlined in blue. Does your packaging stop the scroll?</header>
<div class=grid>{grid}</div>"""

# TV home: sized in vw so a laptop window reads like a 1080p TV at couch distance.
_FEED_TV_CSS = """
:root{--bg:#0f0f0f;--fg:#f1f1f1;--sub:#aaa;--chip:#272727;--blue:#3ea6ff}
*{box-sizing:border-box}
html,body{margin:0;background:var(--bg);color:var(--fg);font-family:Roboto,-apple-system,system-ui,sans-serif;overflow-x:hidden}
.tv{display:grid;grid-template-columns:7vw 1fr;min-height:100vh}
.rail{display:flex;flex-direction:column;align-items:center;gap:2.4vw;padding-top:2.4vw;color:var(--sub);font-size:.8vw}
.logo{width:2.6vw;height:1.85vw;background:#f00;border-radius:.5vw;position:relative;margin-bottom:1vw}
.logo::after{content:"";position:absolute;left:1.05vw;top:.55vw;border-left:.75vw solid #fff;border-top:.38vw solid transparent;border-bottom:.38vw solid transparent}
.nav{display:flex;flex-direction:column;align-items:center;gap:.45vw}
.nav i{width:1.9vw;height:1.9vw;border-radius:50%;border:.17vw solid currentColor;display:block}
.nav.on{color:var(--fg)}.nav.on i{background:var(--fg)}
.main{padding:2.4vw 3vw 4vw 1vw}
.chips{display:flex;gap:.9vw;margin-bottom:2.2vw}
.chip{background:var(--chip);border-radius:.6vw;padding:.6vw 1.2vw;font-size:1.1vw;font-weight:500;white-space:nowrap}
.chip.on{background:var(--fg);color:var(--bg)}
.grid{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:2.6vw 1.5vw}
.tw{position:relative;aspect-ratio:16/9;border-radius:.8vw;overflow:hidden;background:#222}
.tw img,.tw .ph{width:100%;height:100%;object-fit:cover}
.tw img{display:block}
.ph{display:flex;align-items:center;justify-content:center;text-align:center;padding:1vw;
  background:linear-gradient(135deg,#3a3a3a,#555);font-weight:700;font-size:1.15vw;color:#ddd}
.dur{position:absolute;right:.5vw;bottom:.5vw;background:rgba(0,0,0,.8);font-size:.9vw;font-weight:600;padding:.1vw .45vw;border-radius:.3vw}
.t{font-size:1.3vw;font-weight:500;line-height:1.3;margin-top:1vw;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.s{font-size:1.02vw;color:var(--sub);margin-top:.4vw;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.focus{transform:scale(1.05);transform-origin:center top}
.focus .tw{outline:.32vw solid #fff;outline-offset:.28vw}
.mine .tw{box-shadow:0 0 0 .32vw var(--blue)}
.badge{position:absolute;top:.5vw;left:.5vw;background:var(--blue);color:#001;font-weight:700;font-size:.85vw;padding:.1vw .5vw;border-radius:.3vw}
.foot{color:#666;font-size:.9vw;margin-top:3vw}
"""

def _feed_tv_html(cards, label):
    def tile(c, focus):
        cls = "tile" + (" mine" if c.get("mine") else "") + (" focus" if focus else "")
        img = (f"<img src='{html.escape(c['thumb'], quote=True)}' alt=''>" if c["thumb"]
               else f"<div class=ph>{html.escape(c['title'][:60])}</div>")
        dur = f"<span class=dur>{html.escape(c['dur'])}</span>" if c.get("dur") else ""
        badge = "<span class=badge>YOU</span>" if c.get("mine") else ""
        return (f"<div class='{cls}'><div class=tw>{img}{dur}{badge}</div>"
                f"<div class=t>{html.escape(c['title'])}</div><div class=s>{_feed_sub(c)}</div></div>")
    tiles = "".join(tile(c, i == 0) for i, c in enumerate(cards))
    nav = "".join(f"<div class='nav{' on' if n == 'Home' else ''}'><i></i>{n}</div>"
                  for n in ("Search", "Home", "Shorts", "Subscriptions", "Library"))
    chips = "".join(f"<span class='chip{' on' if i == 0 else ''}'>{html.escape(n)}</span>"
                    for i, n in enumerate(["All", label, "Podcasts", "Live", "Recently uploaded", "New to you"]))
    return f"""<!doctype html><meta charset=utf-8><title>ytscout TV feed — {html.escape(label)}</title>
<meta name=viewport content="width=device-width,initial-scale=1">
<style>{_FEED_TV_CSS}</style>
<div class=tv><nav class=rail><div class=logo></div>{nav}</nav>
<main class=main><div class=chips>{chips}</div><div class=grid>{tiles}</div>
<div class=foot>ytscout TV home mock · niche: {html.escape(label)} · your tile is ringed in blue. Judge it from across the room.</div></main></div>"""

_FEED_IG_CSS = """
:root{--bg:#000;--fg:#f5f5f5;--sub:#a8a8a8;--line:#262626;--cell:#1a1a1a;--blue:#0095f6}
@media(prefers-color-scheme:light){:root{--bg:#fff;--fg:#000;--sub:#737373;--line:#dbdbdb;--cell:#efefef}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.4 -apple-system,system-ui,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:935px;margin:0 auto;padding:30px 16px 40px}
.prof{display:flex;gap:7%;align-items:center;padding:0 5% 40px;border-bottom:1px solid var(--line)}
.av{width:150px;height:150px;border-radius:50%;flex:0 0 auto;padding:4px;
  background:conic-gradient(#feda75,#fa7e1e,#d62976,#962fbf,#4f5bd5,#feda75)}
.av i{display:block;width:100%;height:100%;border-radius:50%;background:#444;border:4px solid var(--bg)}
.handle{font-size:20px}
.stats{display:flex;gap:36px;margin:18px 0;font-size:16px}
.bio{white-space:pre-line}
.tabs{display:flex;justify-content:center;gap:60px;font-size:12px;font-weight:600;letter-spacing:1px;color:var(--sub)}
.tabs span{padding:16px 0}.tabs .on{color:var(--fg);border-top:1px solid var(--fg);margin-top:-1px}
.grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:4px}
.cell{position:relative;aspect-ratio:4/5;background:var(--cell);overflow:hidden}
.cell img,.cell .ph{width:100%;height:100%;object-fit:cover}
.cell img{display:block}
.ph{display:flex;align-items:center;justify-content:center;text-align:center;padding:28px;font-weight:700;font-size:15px;
  color:#ddd;background:linear-gradient(160deg,#3a3a3a,#5a5a5a)}
.multi{position:absolute;top:12px;right:14px;width:15px;height:15px;border:2px solid #fff;border-radius:3px;
  filter:drop-shadow(0 0 2px rgba(0,0,0,.6))}
.multi::after{content:"";position:absolute;top:-6px;right:-6px;width:15px;height:15px;border-top:2px solid #fff;border-right:2px solid #fff;border-radius:0 3px 0 0}
.mine{outline:3px solid var(--blue);outline-offset:-3px}
.badge{position:absolute;top:8px;left:8px;background:var(--blue);color:#fff;font-weight:700;font-size:11px;padding:2px 7px;border-radius:4px}
.foot{color:var(--sub);font-size:12px;margin-top:16px}
@media(max-width:735px){.av{width:77px;height:77px}.prof{padding:0 0 24px}.stats{gap:18px;font-size:14px}.grid{gap:2px}}
"""

def _feed_ig_html(cards, label, profile=None):
    p = profile or {}
    def cell(c):
        img = (f"<img src='{html.escape(c['thumb'], quote=True)}' alt=''>" if c["thumb"]
               else f"<div class=ph>{html.escape(c['title'][:80])}</div>")
        multi = "<span class=multi></span>" if c.get("carousel") else ""
        badge = "<span class=badge>YOU</span>" if c.get("mine") else ""
        return f"<div class='cell{' mine' if c.get('mine') else ''}' title='{html.escape(c['title'], quote=True)}'>{img}{multi}{badge}</div>"
    cells = "".join(cell(c) for c in cards)
    handle = html.escape(str(p.get("handle") or "yourhandle"))
    stat = lambda k, d: html.escape(str(p.get(k, d)))
    return f"""<!doctype html><meta charset=utf-8><title>ytscout grid — {html.escape(label)}</title>
<meta name=viewport content="width=device-width,initial-scale=1">
<style>{_FEED_IG_CSS}</style>
<div class=wrap>
<header class=prof><div class=av><i></i></div><div>
<div class=handle>{handle}</div>
<div class=stats><span><b>{stat('posts', len(cards))}</b> posts</span><span><b>{stat('followers', '1,204')}</b> followers</span><span><b>{stat('following', '318')}</b> following</span></div>
<div class=bio>{html.escape(str(p.get("bio") or label))}</div></div></header>
<div class=tabs><span class=on>POSTS</span><span>REELS</span><span>TAGGED</span></div>
<div class=grid>{cells}</div>
<div class=foot>ytscout 4:5 grid mock (Instagram / Facebook) · {html.escape(label)} · your cover is outlined in blue. Does it hold its own at thumbnail size?</div>
</div>"""

FEED_GRIDS = ("yt", "tv", "ig")

def cmd_feed(args):
    grid = "tv" if getattr(args, "tv", False) else (getattr(args, "grid", None) or "yt")
    cand, profile = None, {}
    if getattr(args, "input", None):
        try:
            cards, cand, label, profile = load_feed_json(args.input)
        except (OSError, ValueError) as e:
            print(f"  ! could not read {args.input}: {e}"); return
        label = args.query or label or os.path.basename(args.input)
        source = f"{len(cards)} tiles from {args.input}"
    else:
        if not args.query:
            print("  ! give a niche/search query, or --input tiles.json"); return
        d = search_dump(args.query, args.n)
        if d.get("error"):
            print("  ! " + d["error"]); return
        vids = [v for v in d["results"] if v["dur"] > SHORT_MAX_SEC][:args.n]
        cards = [{"title": v["title"], "channel": v["channel"], "views_str": _yt_views(v["views"]), "age": "",
                  "dur": _fmt_dur(v["dur"]), "thumb": f"https://i.ytimg.com/vi/{v['id']}/hqdefault.jpg",
                  "carousel": False, "mine": False} for v in vids]
        label = args.query
        source = f"{len(vids)} real '{args.query}' videos"
    if not cards:
        print("  No results."); return

    # Adam's card: CLI flags beat the JSON candidate
    my = cand or _feed_card({}, mine=True)
    my["title"] = args.my_title or my["title"] or "[your proposed title here]"
    my["channel"] = my["channel"] or "Your Channel"
    my["views_str"] = my["views_str"] or "NEW"
    if args.my_thumb:
        my["thumb"] = _b64_img(args.my_thumb)  # data URI or None -> placeholder
    pos = max(0, min(len(cards), args.pos))
    cards.insert(pos, my)

    paths = [os.path.join(REPORT_DIR, "feed.html")]
    open(paths[0], "w", encoding="utf-8").write(_feed_yt_html(cards, label))
    if grid == "tv":
        paths.append(os.path.join(REPORT_DIR, "feed-tv.html"))
        open(paths[-1], "w", encoding="utf-8").write(_feed_tv_html(cards, label))
    elif grid == "ig":
        paths.append(os.path.join(REPORT_DIR, "feed-ig.html"))
        open(paths[-1], "w", encoding="utf-8").write(_feed_ig_html(cards, label, profile))
    print(f"\n\033[1mTEST FEED\033[0m built with {source} + your card at position {pos+1}.")
    for p in paths:
        print(f"  → {p}")
    print(f"  Open it and ask: does YOUR thumbnail/title pull the eye, or blend in? (thumbsup.tv-style preview, doctrine's pre-upload gate)\n")
    if args.open:
        os.system(f"open '{paths[-1]}' 2>/dev/null")

# ---------- Command: studio (visual GUI: title+thumb vs live YouTube + audience panel) ----------

# The 5-persona ICP panel WITH human flaws — the channel's own doctrine (a panel that
# flatters is useless). Ported from the content-engine synth_titles.py so studio is self-contained.
STUDIO_PANEL = """You are simulating 5 real YouTube viewers scrolling their feed. They are NOT eager or polite —
they are skeptical, distracted, and have seen a thousand thumbnails today. Each has flaws:

1) NEVER-STARTED NORA: 34, marketing job, wants to build an app but is intimidated. Burned by 3 coding
   courses she never finished. Skeptical of "no code" hype — thinks it's usually a lie. Tired tonight.
2) INDIE HACKER IKE: 27, already vibe-codes with Cursor. Allergic to clickbait and "I can't code" framing
   (thinks it's fake-humble bait). Will click only if it promises something he doesn't already know.
3) CREATOR CARLA: 41, YouTuber/marketer, time-poor, half-watching while doing dishes. Clicks practical
   "I built X" proof, ignores mindset fluff. Cynical about "gurus."
4) CURIOUS CARL: 52, uses ChatGPT casually, curious about building but worried it's a scam or too hard.
   Low trust. Needs to feel it's honest and for a normal person.
5) SCROLLER SAM: 19, doom-scrolling, 1.5-second attention, seen everything. Only a real hook or a number
   stops him. Everything reads as "content" to him.

For the item below, each persona gives an honest click-likelihood 1-10 (1=scroll past, 10=must click)
and a one-line reason IN CHARACTER (include their skepticism). Return ONLY valid JSON:
{{"nora":{{"s":N,"why":"..."}},"ike":{{"s":N,"why":"..."}},"carla":{{"s":N,"why":"..."}},"carl":{{"s":N,"why":"..."}},"sam":{{"s":N,"why":"..."}}}}

ITEM ({kind}): {item}
"""
_PERSONAS = ("nora", "ike", "carla", "carl", "sam")
_PERSONA_NAMES = {"nora": "Never-started Nora", "ike": "Indie-hacker Ike", "carla": "Creator Carla",
                  "carl": "Curious Carl", "sam": "Scroller Sam"}

def _panel_score(kind, item):
    """One gemma call scoring a title/thumbnail across the 5 flawed personas. Local, free."""
    body = json.dumps({"model": "gemma4:12b", "prompt": STUDIO_PANEL.format(kind=kind, item=item),
        "stream": False, "think": False, "format": "json",
        "options": {"num_ctx": 4096, "temperature": 0.6}}).encode()
    req = urllib.request.Request(OLLAMA_URL, data=body, headers={"Content-Type": "application/json"})
    try:
        raw = json.loads(urllib.request.urlopen(req, timeout=120).read())["response"]
        d = json.loads(raw)
        scores = [d[p]["s"] for p in _PERSONAS if p in d and isinstance(d[p].get("s"), (int, float))]
        if not scores:
            return {"error": "panel returned no scores"}
        return {"mean": round(statistics.mean(scores), 1), "low": min(scores), "panel": d}
    except urllib.error.URLError:
        return {"error": "ollama not reachable — is it running? (the YouTube preview works without it)"}
    except Exception as e:
        return {"error": str(e)}

def _studio_niche_default():
    try:
        data = load_watchlist()
        active = _active_list(data)
        return (active or {}).get("niche") or "ai"
    except Exception:
        return "ai"

def _studio_preview(data):
    """Zero-AI: real niche videos + your card. Same engine as `scout feed`, no model call."""
    niche = (data.get("niche") or "ai").strip() or "ai"
    n = max(4, min(20, int(data.get("n", 11))))
    d = search_dump(niche, n)
    if d.get("error"):
        return {"error": d["error"], "cards": []}
    vids = [v for v in d["results"] if v["dur"] > SHORT_MAX_SEC][:n]
    cards = [{"title": v["title"], "channel": v["channel"], "views": _yt_views(v["views"]),
              "thumb": f"https://i.ytimg.com/vi/{v['id']}/hqdefault.jpg", "mine": False} for v in vids]
    return {"cards": cards, "niche": niche}

def _studio_panel(data):
    """Runs each title (and optional thumbnail description) through the flawed ICP panel."""
    titles = [t.strip() for t in (data.get("titles") or []) if t and t.strip()]
    thumb_desc = (data.get("thumb_desc") or "").strip()
    results, errors = [], []
    for t in titles:
        r = _panel_score("video title", t)
        if "error" in r:
            errors.append({"txt": t, "error": r["error"]})
        else:
            r["txt"] = t; r["kind"] = "title"; results.append(r)
    if thumb_desc:
        r = _panel_score("thumbnail concept", thumb_desc)
        if "error" in r:
            errors.append({"txt": thumb_desc, "error": r["error"]})
        else:
            r["txt"] = thumb_desc; r["kind"] = "thumbnail"; results.append(r)
    results.sort(key=lambda x: x["mean"], reverse=True)
    return {"results": results, "errors": errors, "persona_names": _PERSONA_NAMES}

STUDIO_HTML = r"""<!doctype html><html><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>ytscout studio — packaging test</title>
<style>
:root{--bg:#0f0f0f;--panel:#1c1c1c;--fg:#f1f1f1;--sub:#aaa;--line:#333;--blue:#3ea6ff;--good:#2ecc71;--warn:#e0a800}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.45 Roboto,-apple-system,system-ui,sans-serif}
header{padding:12px 18px;border-bottom:1px solid var(--line);display:flex;align-items:center;gap:12px}
header b{font-size:16px}header .tag{color:var(--sub);font-size:13px}
.wrap{display:grid;grid-template-columns:340px 1fr;gap:0;height:calc(100vh - 49px)}
.side{border-right:1px solid var(--line);padding:16px;overflow:auto;background:var(--panel)}
.main{overflow:auto;padding:0}
label{display:block;font-size:12px;text-transform:uppercase;letter-spacing:.5px;color:var(--sub);margin:14px 0 6px}
input[type=text],textarea{width:100%;background:#0f0f0f;border:1px solid var(--line);color:var(--fg);
  border-radius:8px;padding:9px 10px;font:14px Roboto,sans-serif;resize:vertical}
textarea{min-height:96px}
.hint{color:var(--sub);font-size:12px;margin-top:4px}
button{cursor:pointer;border:0;border-radius:8px;padding:10px 12px;font-weight:600;font-size:14px;width:100%;margin-top:10px}
.b-primary{background:var(--blue);color:#001}
.b-ghost{background:#2a2a2a;color:var(--fg)}
.thumbdrop{display:block;margin-top:6px;border:1px dashed var(--line);border-radius:8px;padding:14px 10px;text-align:center;color:var(--sub);font-size:13px;cursor:pointer;text-transform:none;letter-spacing:normal}
.thumbdrop:hover{border-color:var(--blue);color:var(--fg)}
.thumbdrop.dragover{border-color:var(--blue);background:#3ea6ff22}
.thumbdrop img{max-width:100%;border-radius:6px;display:block;margin:6px auto 0}
.titlelist{margin-top:6px}
.titlerow{display:flex;align-items:center;gap:8px;margin:6px 0}
.titlerow input{flex:1}
.titlerow .pick{width:26px;height:26px;border-radius:50%;border:2px solid var(--line);flex:0 0 auto;cursor:pointer;background:transparent}
.titlerow.sel .pick{border-color:var(--blue);background:var(--blue)}
.titlerow .del{width:26px;flex:0 0 auto;background:#2a2a2a;border-radius:6px;padding:4px 0}
/* feed grid — YouTube authentic */
.feedhdr{padding:12px 20px;color:var(--sub);font-size:14px;border-bottom:1px solid var(--line)}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:16px 12px;padding:20px}
.card{position:relative}
.thumb{width:100%;aspect-ratio:16/9;object-fit:cover;border-radius:12px;display:block;background:#333}
.thumb.ph{display:flex;align-items:center;justify-content:center;text-align:center;padding:8px;color:#ddd;
  background:linear-gradient(135deg,#3a3a3a,#555);font-weight:600}
.meta{padding:10px 2px}
.ctitle{font-weight:600;font-size:15px;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.csub{color:var(--sub);font-size:13px;margin-top:3px}
.mine .thumb{outline:3px solid var(--blue);outline-offset:2px}
.badge{position:absolute;top:8px;left:8px;background:var(--blue);color:#001;font-weight:700;font-size:11px;padding:2px 7px;border-radius:4px;letter-spacing:.5px}
/* audience panel */
.panelwrap{border-top:1px solid var(--line);padding:16px 20px}
.panelwrap h3{margin:0 0 4px;font-size:15px}
.panelwrap .note{color:var(--sub);font-size:12px;margin-bottom:12px}
.scorerow{display:flex;align-items:center;gap:12px;padding:10px 0;border-bottom:1px solid #262626}
.scorenum{font-size:22px;font-weight:800;width:52px;text-align:center;border-radius:8px;padding:6px 0;flex:0 0 auto}
.scoretxt{flex:1}.scoretxt .t{font-weight:600}.scoretxt .why{color:var(--sub);font-size:12px;margin-top:3px}
.kind{font-size:11px;color:var(--sub);text-transform:uppercase;letter-spacing:.5px}
.muted{color:var(--sub)}.err{color:#ff6b6b;font-size:13px}
.spin{display:inline-block;width:14px;height:14px;border:2px solid var(--line);border-top-color:var(--blue);border-radius:50%;animation:s .7s linear infinite;vertical-align:-2px}
@keyframes s{to{transform:rotate(360deg)}}
</style></head><body>
<header><b>ytscout studio</b><span class=tag>packaging test · your title + thumbnail vs the real feed, then the audience</span></header>
<div class=wrap>
  <div class=side>
    <label>Niche feed to test against</label>
    <input id=niche type=text value="__NICHE__">
    <div class=hint>The real videos your card competes with in the scroll.</div>

    <label>Your title options</label>
    <div class=titlelist id=titles></div>
    <button class=b-ghost id=addtitle>+ add another title</button>

    <label>Your thumbnail</label>
    <label class=thumbdrop id=thumbdrop for=thumbfile><span id=thumbtext>click to upload an image (or drag one in)</span><img id=thumbprev style=display:none></label>
    <input id=thumbfile type=file accept="image/*" style=display:none>
    <label>Thumbnail idea (for the audience panel, optional)</label>
    <textarea id=thumbdesc placeholder="e.g. split screen: 'vidIQ $19/mo' with a red X vs a terminal at '$0', my face closed-mouth"></textarea>

    <button class=b-primary id=preview>Preview in YouTube ▸</button>
    <button class=b-ghost id=testpanel>Test with audience (local AI)</button>
    <div class=hint id=status></div>
  </div>
  <div class=main>
    <div class=feedhdr id=feedhdr>Type titles, upload a thumbnail, then hit <b>Preview in YouTube</b>. Your card is outlined in blue.</div>
    <div class=grid id=grid></div>
    <div class=panelwrap id=panelwrap style=display:none>
      <h3>Audience panel</h3>
      <div class=note>5 skeptical viewers with human flaws score click-likelihood 1–10. Read the ranking, not the absolute number — this panel is harsh by design. The real test is A/B on your channel.</div>
      <div id=scores></div>
    </div>
  </div>
</div>
<script>
let realCards=[], myThumb=null, selIdx=0;
const $=s=>document.querySelector(s), $$=s=>[...document.querySelectorAll(s)];
const seed=["",""];

function renderTitleRows(){
  const box=$('#titles'); box.innerHTML='';
  seed.forEach((t,i)=>{
    const row=document.createElement('div'); row.className='titlerow'+(i===selIdx?' sel':'');
    row.innerHTML=`<button class=pick title="show this one on the preview card"></button>
      <input type=text value="${t.replace(/"/g,'&quot;')}" placeholder="title option ${i+1}">
      <button class=del title=remove>✕</button>`;
    row.querySelector('.pick').onclick=()=>{selIdx=i; renderTitleRows(); drawGrid();};
    row.querySelector('input').oninput=e=>{seed[i]=e.target.value; if(i===selIdx) drawGrid();};
    row.querySelector('.del').onclick=()=>{if(seed.length>1){seed.splice(i,1); if(selIdx>=seed.length)selIdx=0; renderTitleRows(); drawGrid();}};
    box.appendChild(row);
  });
}
$('#addtitle').onclick=()=>{seed.push(''); renderTitleRows();};

function loadThumb(f){ if(!f)return;
  const r=new FileReader();
  r.onload=()=>{myThumb=r.result; const p=$('#thumbprev'); p.src=myThumb; p.style.display='block';
    $('#thumbtext').textContent='thumbnail loaded — click to replace'; drawGrid();};
  r.readAsDataURL(f);
}
$('#thumbfile').onchange=e=>loadThumb(e.target.files[0]);
const _dd=$('#thumbdrop');
['dragover','dragenter'].forEach(ev=>_dd.addEventListener(ev,e=>{e.preventDefault();_dd.classList.add('dragover');}));
['dragleave','drop'].forEach(ev=>_dd.addEventListener(ev,e=>{e.preventDefault();_dd.classList.remove('dragover');}));
_dd.addEventListener('drop',e=>{const f=e.dataTransfer.files[0]; if(f&&f.type.startsWith('image/')) loadThumb(f);});

function card(c){
  const cls='card'+(c.mine?' mine':'');
  const thumb=c.thumb?`<img class=thumb src="${c.thumb}">`:`<div class="thumb ph">${(c.title||'').slice(0,40)}</div>`;
  const badge=c.mine?'<span class=badge>YOU</span>':'';
  return `<div class="${cls}">${thumb}${badge}<div class=meta><div class=ctitle>${esc(c.title)}</div><div class=csub>${esc(c.channel)} · ${c.views}</div></div></div>`;
}
function esc(s){const d=document.createElement('div'); d.textContent=s||''; return d.innerHTML;}

function drawGrid(){
  if(!realCards.length)return;
  const mine={title:seed[selIdx]||'[your proposed title here]',channel:'Your Channel',views:'NEW',thumb:myThumb,mine:true};
  const pos=Math.min(3, realCards.length);
  const all=[...realCards.slice(0,pos), mine, ...realCards.slice(pos)];
  $('#grid').innerHTML=all.map(card).join('');
  $('#feedhdr').innerHTML=`Real <b>${esc($('#niche').value)}</b> feed · your card is outlined in blue. Does your packaging stop the scroll?`;
}

async function preview(){
  status('fetching the real feed…',true);
  try{
    const r=await fetch('/api/preview',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({niche:$('#niche').value, n:11})});
    const d=await r.json();
    if(d.error){status('⚠ '+d.error);return;}
    realCards=d.cards; drawGrid(); status('');
  }catch(e){status('⚠ '+e);}
}
async function testpanel(){
  const titles=seed.map(s=>s.trim()).filter(Boolean);
  const thumb_desc=$('#thumbdesc').value.trim();
  if(!titles.length && !thumb_desc){status('add at least one title or a thumbnail idea first');return;}
  $('#panelwrap').style.display='block';
  $('#scores').innerHTML='<div class=muted><span class=spin></span> the panel is scoring… (local AI, ~10s each)</div>';
  status('running the audience panel…',true);
  try{
    const r=await fetch('/api/panel',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({titles, thumb_desc})});
    const d=await r.json(); renderScores(d); status('');
  }catch(e){$('#scores').innerHTML='<div class=err>⚠ '+e+'</div>'; status('');}
}
function color(n){return n>=6?'var(--good)':n>=4?'var(--warn)':'#c0392b';}
function renderScores(d){
  let h='';
  (d.results||[]).forEach(r=>{
    const names=d.persona_names||{};
    const worst=Object.entries(r.panel).filter(([k,v])=>v&&typeof v.s==='number').sort((a,b)=>a[1].s-b[1].s)[0];
    const worstline=worst?`${names[worst[0]]||worst[0]} (${worst[1].s}): "${esc(worst[1].why)}"`:'';
    h+=`<div class=scorerow>
      <div class=scorenum style="background:${color(r.mean)}22;color:${color(r.mean)}">${r.mean}</div>
      <div class=scoretxt><div class=kind>${r.kind}</div><div class=t>${esc(r.txt)}</div>
        <div class=why>harshest: ${worstline} · low ${r.low}</div></div></div>`;
  });
  (d.errors||[]).forEach(e=>{h+=`<div class=scorerow><div class=err>⚠ ${esc(e.txt)} — ${esc(e.error)}</div></div>`;});
  $('#scores').innerHTML=h||'<div class=muted>no scores returned</div>';
}
function status(t,busy){$('#status').innerHTML=(busy?'<span class=spin></span> ':'')+esc(t);}

$('#preview').onclick=preview;
$('#testpanel').onclick=testpanel;
renderTitleRows();
</script></body></html>"""

def cmd_studio(args):
    from http.server import BaseHTTPRequestHandler, HTTPServer
    import threading, webbrowser
    niche_default = args.niche or _studio_niche_default()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass
        def _send(self, code, ctype, body):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def do_GET(self):
            if self.path in ("/", "/index.html"):
                self._send(200, "text/html; charset=utf-8",
                           STUDIO_HTML.replace("__NICHE__", html.escape(niche_default)).encode())
            else:
                self._send(404, "text/plain", b"not found")
        def do_POST(self):
            try:
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length) or b"{}")
            except Exception:
                self._send(400, "application/json", b'{"error":"bad request"}'); return
            if self.path == "/api/preview":
                out = _studio_preview(payload)
            elif self.path == "/api/panel":
                out = _studio_panel(payload)
            else:
                self._send(404, "text/plain", b"not found"); return
            self._send(200, "application/json", json.dumps(out).encode())

    port = args.port
    try:
        srv = HTTPServer(("127.0.0.1", port), Handler)
    except OSError as e:
        print(f"  ! port {port} busy ({e}). Try: scout studio --port {port+1}"); return
    url = f"http://127.0.0.1:{port}/"
    print(f"\n  \033[1mytscout studio\033[0m → {url}")
    print(f"  Niche: {niche_default}. Preview is zero-AI; the audience panel uses local gemma.")
    print(f"  Ctrl-C to stop.\n")
    if not args.no_open:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n  studio stopped.")
        srv.server_close()

# ---------- Command: weekly (the automatable idea-farm ritual, zero AI) ----------

def load_watchlist():
    """Schema: {"lists": {name: {"handles":[...], "niche": str}}, "active": name}.
    Migrates the old flat {"handles","niche"} shape on read."""
    data = {"lists": {}, "active": None}
    if os.path.exists(WATCHLIST):
        try:
            raw = json.load(open(WATCHLIST))
            if "lists" in raw:
                data = raw
            elif raw.get("handles"):  # migrate old flat shape
                nm = raw.get("niche") or "default"
                data = {"lists": {nm: {"handles": raw["handles"], "niche": raw.get("niche")}}, "active": nm}
        except Exception:
            pass
    return data

def _active_list(data, name=None):
    name = name or data.get("active")
    return name, data["lists"].get(name, {"handles": [], "niche": None})

def cmd_watch(args):
    data = load_watchlist()
    name = args.list or data.get("active") or (args.niche if args.niche else "default")
    lst = data["lists"].setdefault(name, {"handles": [], "niche": args.niche or name})
    if args.niche:
        lst["niche"] = args.niche
    if args.add:
        for h in args.add.split(","):
            h = h.strip().lstrip("@")
            if h and h not in lst["handles"]:
                lst["handles"].append(h)
    if args.remove:
        lst["handles"] = [h for h in lst["handles"] if h.lower() != args.remove.strip().lstrip("@").lower()]
    if args.activate or not data.get("active"):
        data["active"] = name
    json.dump(data, open(WATCHLIST, "w"), indent=2)
    print(f"\n  Watchlists ({WATCHLIST}):")
    for nm, l in data["lists"].items():
        star = " \033[32m(active)\033[0m" if nm == data.get("active") else ""
        print(f"\n  \033[1m{nm}\033[0m — niche {l.get('niche') or '?'}{star}")
        for h in l["handles"]:
            print(f"   • @{h}")
        if not l["handles"]:
            print("   (empty)")
    print(f"\n  Weekly runs the ACTIVE list. Switch with: scout watch --list <name> --activate\n")

def cmd_weekly(args):
    data = load_watchlist()
    name, lst = _active_list(data, getattr(args, "list", None))
    handles = lst.get("handles", [])
    niche = args.niche or lst.get("niche")
    rpm = real_rpm(niche, getattr(args, "rpm", None))
    if not handles:
        print("\n  Watchlist is empty. Add channels first:\n    scout watch --add handle1,handle2 --niche ai\n")
        return
    print(f"\n\033[1mWEEKLY IDEA FARM\033[0m  {len(handles)} channels, {niche or 'default'} niche (${rpm:.0f} RPM)\n")
    seen_path = os.path.join(CACHE_DIR, "weekly_seen.json")
    seen = set(json.load(open(seen_path))) if os.path.exists(seen_path) else set()
    finds = []
    for h in handles:
        ch = channel_dump(h, limit=args.scan)
        if ch.get("error"):
            print(f"  ! {h}: {ch['error']}"); continue
        subs = ch.get("subs") or 0
        vids = apply_since(apply_shorts(ch["videos"], getattr(args, "shorts", "exclude")),
                           getattr(args, "since_months", DEFAULT_SINCE_MONTHS))
        vids = [v for v in vids if v["views"] >= args.min_views]
        if not vids:
            continue
        med = statistics.median([v["views"] for v in vids]) or 1
        for v in vids:
            v["ch"] = ch["name"]; v["subs"] = subs
            v["vsr"] = round(v["views"]/subs, 2) if subs else None
            v["osc"] = round(v["views"]/med, 2)
            v["rev"] = est_rev(v["views"], rpm, v["dur"])
            v["new"] = v["id"] not in seen
        finds.extend(vids)
    # keep only real outliers (vsr>=2 OR osc>=3) and rank
    hot = [v for v in finds if (v["vsr"] or 0) >= 2 or v["osc"] >= 3]
    hot.sort(key=lambda v: (v["new"], v["vsr"] or 0, v["osc"]), reverse=True)
    hot = hot[:args.top]
    rows = []
    for v in hot:
        flag = "\033[32mNEW\033[0m" if v["new"] else "   "
        vsr = f"{v['vsr']}x" if v["vsr"] is not None else "—"
        rows.append([flag, vsr, f"{v['osc']}x", human(v["views"]), money(v["rev"]), v["ch"][:14], v["title"][:48]])
    print(table([[c for c in r] for r in rows], ["", "V/Sub", "vsMed", "Views", "Est$", "Channel", "Title"]))
    newcount = sum(1 for v in hot if v["new"])
    print(f"\n  {newcount} NEW outliers since last run, {len(hot)-newcount} standing. These are proven ideas to port into your niche this week.")
    print(f"  Est$ = AdSense floor at ${rpm:.0f} RPM. The play is the CONCEPT, monetized by owned products.\n")
    # persist seen + write dated report
    json.dump(sorted(set(list(seen) + [v["id"] for v in finds])), open(seen_path, "w"))
    _write_weekly_report(handles, niche, rpm, hot, name)

def _write_weekly_report(handles, niche, rpm, hot, listname=None):
    stamp = time.strftime("%Y-%m-%d")  # real OS date
    tag = f"-{listname}" if listname else ""
    path = os.path.join(REPORT_DIR, f"weekly{tag}-{stamp}.md")
    lines = [f"# Weekly idea farm — {stamp}", "",
             f"Channels: {', '.join('@'+h for h in handles)}  |  niche: {niche or 'default'} (${rpm:.0f} RPM)", "",
             "| New | V/Sub | vsMed | Views | Est$ | Channel | Title | Link |",
             "|---|---|---|---|---|---|---|---|"]
    for v in hot:
        vsr = f"{v['vsr']}x" if v["vsr"] is not None else "—"
        lines.append(f"| {'NEW' if v['new'] else ''} | {vsr} | {v['osc']}x | {human(v['views'])} | "
                     f"{money(v['rev'])} | {v['ch']} | {v['title']} | https://youtu.be/{v['id']} |")
    lines += ["", "Port each concept into your niche (Niche Comparison Theory). Est$ is the AdSense floor; owned products are the business."]
    open(path, "w").write("\n".join(lines))
    print(f"  → Report saved: {path}")

# ---------- Command: peers (discover same-size channels with outsized returns) ----------

PEERS_QUERIES_DEFAULT = os.path.expanduser("~/ytscout/peers-queries-{list}.txt")
PEERS_STOP = set("a an and the for to of in on with my your i is it how what do does vs no or at by from this that are be can".split())
PEERS_ANCHORS = {"claude", "ai", "gpt", "chatgpt", "ollama", "llm", "local", "codex", "cursor", "gemini", "agent", "agents", "vibe", "coding", "code", "resolve", "davinci", "software", "saas", "anthropic", "automation"}
PEERS_EXCLUDE_HANDLES = {"adamgarceau", "adamgarceau-e2f"}
PEERS_EXCLUDE_IDS = {"UCvRzOAuSxArqvN0yR3W6dLw", "UCDsc53iXVoZgA5A99cyWNqA"}

def _peers_tokens(text):
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in PEERS_STOP and len(w) > 2}

def _peers_load_queries(path):
    qs = []
    for ln in open(path):
        ln = ln.strip()
        if ln and not ln.startswith("#"):
            qs.append(ln)
    return qs

# Topic buckets for clustering outliers (first-match-wins is NOT used: a title can sit in several).
# Editable. Regex on lowercased title.
PEERS_TOPICS = [
    ("DaVinci Resolve + AI", r"davinci|resolve"),
    ("Local AI / Ollama / running models on your own machine", r"local ai|local llm|ollama|run.{0,12}locally|quantiz|private ai"),
    ("Hardware showdowns (Mac vs GPU for local AI)", r"rtx|\bm[345] (max|ultra|pro)|4090|5090|vram|mac (mini|studio)|macbook|\bgpu\b|laptop"),
    ("Claude plan, cost and usage limits", r"(claude|ai|gpt|codex|cursor).{0,40}(subscription|plan\b|cost|pricing|limit|expensive|cheap)|(subscription|max plan|usage limit|rate limit).{0,40}(claude|ai\b)|cancel"),
    ("AI tool comparisons (X vs Y, which one)", r"\bvs\.?\b|versus|compar|better than|which (ai|one|is)|switch|tested every"),
    ("Build a real app/tool with Claude Code, no coding", r"built|build(ing)?\b.*(app|tool|saas|site|website|product)|shipped|no cod|without cod|vibe cod|non[- ]?cod|from scratch|in (one|a) day|full (system|setup|walkthrough)"),
    ("Claude Code for business / ops / marketing automation", r"small business|my business|marketing team|automat|agency|invoice|quickbooks|bookkeep|\bcrm\b|my (team|company)"),
    ("Claude Code setup, tips, skills, agents", r"claude code|skills?\b|subagent|\bmcp\b|hooks?\b|agent|claude\.md|prompt|\bcli\b"),
    ("AI industry news / model releases", r"gpt-?\d|gemini|openai|anthropic|nerf|release|new model|opus|sonnet|announce|leak|ultracode|muse"),
    ("Websites / WordPress / hosting", r"wordpress|website|web ?site|hosting|landing page|\bseo\b|domain"),
]

# What Adam's non-coder small-business viewer would want from each topic (VIEWER-LANGUAGE-BANK §1-2).
# One sentence each, written by hand. Never pivot to developers/engineering.
PEERS_ANGLES = {
    "DaVinci Resolve + AI": "Adam is not a video-editing channel, so only use this as demand proof; if it ever runs, show one real owner task Claude took off a working editor's plate, start to finish.",
    "Local AI / Ollama / running models on your own machine": "Show a small-business owner keeping their customer data private by running a local model on a Mac they already own, with the real cost and the real limits on screen.",
    "Claude plan, cost and usage limits": "Answer the bill question owners actually type (\"is the Max plan worth it\", \"I hit my limit\") with Adam's own real usage numbers from building a real tool.",
    "Hardware showdowns (Mac vs GPU for local AI)": "Run a real owner job (an estimate or invoice batch) on the Mac Adam already owns and show a non-coder what hardware they actually need, which is probably none.",
    "AI tool comparisons (X vs Y, which one)": "Run Adam's test-lab version: same real small-business job given to each tool, results shown side by side, so a non-coder can pick one.",
    "Build a real app/tool with Claude Code, no coding": "Build one named paid-software replacement (check printing, mileage, inventory) start to finish for a non-coder owner, including putting it online, which the viewer comments say demos skip.",
    "Claude Code for business / ops / marketing automation": "Pick one specific job in a real small business (invoicing, estimates, a vending route) and show Claude doing it for a non-technical owner, with what it got wrong.",
    "Claude Code setup, tips, skills, agents": "Translate the setup into plain owner language (\"it forgets between sessions, here is the fix\") and prove it on a real build, not a toy demo.",
    "AI industry news / model releases": "Skip news; test the new model on one real small-business task and report whether a non-coder should care.",
    "Websites / WordPress / hosting": "Show a non-coder owner replacing a paid site or plugin with something Claude built and hosted, with the monthly cost before and after.",
}
PEERS_DEFAULT_ANGLE = "Keep the promise, change the proof: Adam builds it for a real small-business job in front of a non-coder owner and shows what went wrong."
PEERS_BANNED = re.compile(r"developer|backend|back-end|engineer|refactor|devops|software team|senior dev|production-grade|codebase", re.I)

def _peers_topics(title):
    t = title.lower()
    return [name for name, rx in PEERS_TOPICS if re.search(rx, t)]

def _peers_age(v, now):
    try:
        return (now - time.mktime(time.strptime(v["date"], "%Y%m%d"))) / 86400
    except Exception:
        return 9999

def _peers_score(ch, handle, seed_tokens, now, need_active=True):
    """Peer record or None. Typical = MEDIAN views of the channel's long-forms (not a mean).
    Active = 3+ long-forms in the last 90 days (waived for seeds)."""
    subs = ch.get("subs") or 0
    longs = [v for v in ch.get("videos", []) if v["dur"] > SHORT_MAX_SEC and v.get("date")]
    if not longs:
        return None
    med = statistics.median([v["views"] for v in longs]) or 1
    rec = [v for v in longs if _peers_age(v, now) <= 90]
    if need_active and len(rec) < 3:
        return None
    if not rec:
        return {"handle": handle, "name": ch.get("name") or handle, "subs": subs, "up90": 0, "med": med, "m1": 0.0,
                "n5": 0, "fit": 0.0, "score": 0.0, "best": None, "outliers60": [], "videos": longs}
    ratios = [v["views"] / med for v in rec]
    n5 = sum(1 for v in rec if subs and v["views"] >= 5 * subs)
    fit_hits = sum(1 for v in rec if len(_peers_tokens(v["title"]) & seed_tokens) >= 2 and _peers_tokens(v["title"]) & PEERS_ANCHORS)
    fit = fit_hits / len(rec)
    best = max(rec, key=lambda v: v["views"] / med)
    m1 = statistics.median(ratios)
    score = (m1 + 0.5 * n5) * (0.5 + fit)
    return {"handle": handle, "name": ch.get("name") or handle, "subs": subs, "up90": len(rec),
            "med": med, "m1": round(m1, 2), "n5": n5, "fit": round(fit, 2), "score": round(score, 2),
            "best": {"id": best["id"], "title": best["title"], "views": best["views"],
                     "osc": round(best["views"] / med, 1), "age": int(_peers_age(best, now)),
                     "vps": round(best["views"] / subs, 1) if subs else None, "dur": best["dur"]},
            "outliers60": [dict(id=v["id"], title=v["title"], views=v["views"], osc=round(v["views"] / med, 1),
                                age=int(_peers_age(v, now)), dur=v["dur"]) for v in rec
                           if _peers_age(v, now) <= 60 and v["views"] / med >= 5],
            "videos": longs}

def _peers_clusters(peers, now, mult=3.0, days=183):
    """Outliers (>= mult x the channel's median, long-form, last ~6 months) grouped by topic bucket."""
    topics = {}
    untagged = []
    for p in peers:
        for v in p.get("videos", []):
            if _peers_age(v, now) > days:
                continue
            osc = v["views"] / (p["med"] or 1)
            if osc < mult:
                continue
            row = {"handle": p["handle"], "subs": p["subs"], "title": v["title"], "id": v["id"], "osc": round(osc, 1),
                   "views": v["views"], "age": int(_peers_age(v, now))}
            tps = _peers_topics(v["title"])
            if not tps:
                untagged.append(row)
            for t in tps:
                topics.setdefault(t, []).append(row)
    multi = {t: r for t, r in topics.items() if len({x["handle"] for x in r}) >= 2}
    singles = [(t, r) for t, r in topics.items() if t not in multi for r in r]
    return multi, singles, untagged

def _peers_brief(p, v, topic):
    prompt = (f"A small YouTube channel ('{p['name']}', {human(p['subs'])} subs) posted '{v['title']}' "
              f"({human(v['views'])} views, {v['osc']}x its channel median, {v['age']} days ago). "
              f"In 2 or 3 plain sentences (max 70 words) say what this video most likely is and why it likely popped (title, thumbnail, topic). "
              f"You have not watched it: mark guesses as guesses. Do NOT suggest how to remake it. No markdown, no em dashes.")
    out = ollama(prompt).replace("—", ",").strip()
    if out.startswith("[ollama unavailable") or PEERS_BANNED.search(out):
        out = f"Likely a '{v['title']}' style video that ran {v['osc']}x this channel's median; the title promise and topic are the probable drivers (guess, not watched)."
    if out and out[-1] not in ".!?" and "." in out:
        out = out[:out.rindex(".") + 1]
    return out

def cmd_peers(args):
    listname = args.list
    qpath = args.queries or PEERS_QUERIES_DEFAULT.format(list=listname)
    if not os.path.exists(qpath):
        print(f"\n  No queries file: {qpath}\n"); return
    queries = _peers_load_queries(qpath)
    seed_tokens = set().union(*[_peers_tokens(q) for q in queries]) - {"app", "build", "built", "make", "own", "tested", "using"}
    spath = os.path.expanduser(f"~/ytscout/peers-seeds-{listname}.txt")
    seeds = _peers_load_queries(spath) if os.path.exists(spath) else []
    seeds_l = {h.lstrip("@").lower() for h in seeds}
    data = load_watchlist()
    known = set()
    for nm, l in data["lists"].items():
        if nm != f"peers-{listname}":
            known |= {h.lower() for h in l["handles"]}   # giants/other lists never count as peers
    print(f"\n\033[1mPEERS\033[0m  {len(queries)} queries, {len(seeds)} seeds, band {args.min_subs}-{args.max_subs} subs, cap {args.cap} candidates\n")
    cands = {}   # handle -> {subs, hits}
    for q in queries:
        sd = search_dump(q, args.per_query)
        if sd.get("error"):
            print(f"  ! {q}: {sd['error'][:80]}")
            if "429" in sd["error"]:
                print("  429 from YouTube: stopping discovery; rerun the same command to resume from cache."); break
            continue
        time.sleep(args.sleep)
        for r in sd["results"]:
            h, subs = r.get("handle"), r.get("subs")
            if not h or h.lower() in PEERS_EXCLUDE_HANDLES or r.get("channel_id") in PEERS_EXCLUDE_IDS or h.lower() in known:
                continue
            if h.lower() in seeds_l or subs is None or not (args.min_subs <= subs <= args.max_subs):
                continue
            c = cands.setdefault(h, {"subs": subs, "hits": 0, "views": 0})
            c["hits"] += 1; c["views"] = max(c["views"], r["views"])
    ranked = sorted(cands.items(), key=lambda kv: (-kv[1]["hits"], -kv[1]["views"]))[:args.cap]
    work = [(h, c, False) for h, c in ranked] + [(h.lstrip("@"), {"subs": 0, "hits": 0}, True) for h in seeds]
    print(f"\n  {len(cands)} channels in band; scanning top {len(ranked)} + {len(seeds)} seeds\n")
    now = time.time()
    from concurrent.futures import ThreadPoolExecutor
    def _fetch(w, limit=None):
        ch = channel_dump(w[0], limit=limit or args.scan)
        if ch.get("error") and re.search(r"members-only|Join this channel|age|Sign in", ch["error"]):
            ch = channel_dump(w[0], limit=limit or args.scan, tolerant=True)
        time.sleep(args.sleep)
        return w, ch
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        fetched = list(ex.map(_fetch, work))
    peers = []
    for (h, c, is_seed), ch in fetched:
        if ch.get("error"):
            print(f"  ! @{h}: {ch['error'][:70]}")
            continue
        subs = ch.get("subs") or c["subs"]
        if not is_seed and not (args.min_subs <= subs <= args.max_subs):
            continue
        ch["subs"] = subs
        p = _peers_score(ch, h, seed_tokens, now, need_active=not is_seed)
        if p and (is_seed or p["fit"] > 0):
            p["hits"] = c["hits"]; p["source"] = "seed" if is_seed else "search"; peers.append(p)
    peers.sort(key=lambda p: p["score"], reverse=True)
    top_search = [p for p in peers if p["source"] != "seed"][:args.n]
    seed_peers = [p for p in peers if p["source"] == "seed"]
    top = sorted(top_search + seed_peers, key=lambda p: p["score"], reverse=True)
    # deeper pull (30 videos) on finalists so the 6-month topic clustering has real coverage
    pool_handles = {p["handle"] for p in top}
    deep_in = [(p["handle"], {"subs": p["subs"], "hits": 0}, p["source"] == "seed") for p in top]
    if args.scan < 30:
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            deep = list(ex.map(lambda w: _fetch(w, 30), deep_in))
        for (h, c, is_seed), ch in deep:
            if ch.get("error"):
                continue
            ch["subs"] = ch.get("subs") or c["subs"]
            q = _peers_score(ch, h, seed_tokens, now, need_active=False)
            if q:
                for p in top:
                    if p["handle"] == h:
                        p["videos"] = q["videos"]; p["med"] = q["med"]
    rows = [[f"@{p['handle'][:20]}", p["source"], human(p["subs"]), human(int(p["med"])), p["up90"], f"{p['m1']}x", p["n5"],
             f"{p['best']['osc']}x" if p["best"] else "-", f"{int(p['fit']*100)}%", p["score"]] for p in top]
    print(table(rows, ["Channel", "Src", "Subs", "Typical", "Up/90d", "MedRatio", "N@5xSubs", "BestOutlier", "Fit", "Score"]))
    multi, singles, untagged = _peers_clusters(top, now)
    pool = sorted([(p, v) for p in top for v in p["outliers60"]], key=lambda pv: pv[1]["osc"], reverse=True)[:5]
    briefs = []
    for p, v in pool:
        tps = _peers_topics(v["title"])
        topic = tps[0] if tps else None
        briefs.append((p, v, topic, _peers_brief(p, v, topic)))
    stamp = time.strftime("%Y-%m-%d")
    path = os.path.join(REPORT_DIR, f"peers-{listname}-{stamp}.md")
    L = [f"# Peers ({listname}) — {stamp}", "",
         f"{len(queries)} seed queries, sub band {args.min_subs:,}-{args.max_subs:,} (seeds exempt), {len(ranked)} search candidates scanned + {len(seeds)} seeds, "
         f"{len(top_search)} search peers kept (3+ long-forms in 90d, topical fit > 0) + {len(seed_peers)} seeds.", "",
         "Typical = the channel's MEDIAN long-form views (not a mean). Score = (median of last-90d views / Typical + 0.5 x videos at 5x+ subs) x (0.5 + fit). Fit = share of 90d titles sharing 2+ seed terms and one AI term. Views are lifetime.", "",
         "| Channel | Src | Subs | Typical | Up/90d | MedRatio | N@5xSubs | Best outlier | Fit | Score |", "|---|---|---|---|---|---|---|---|---|---|"]
    for p in top:
        b = p["best"]
        bs = f"[{b['title'][:50]}](https://youtu.be/{b['id']}) {human(b['views'])} ({b['osc']}x)" if b else "none in 90d"
        L.append(f"| [@{p['handle']}](https://youtube.com/@{p['handle']}) | {p['source']} | {human(p['subs'])} | {human(int(p['med']))} | {p['up90']} | {p['m1']}x | {p['n5']} | {bs} | {int(p['fit']*100)}% | {p['score']} |")
    L += ["", "## Topics hitting on 2+ channels", "",
          f"Outliers = long-form at 3x+ the channel's median, last 6 months, across the {len(top)} peers above (30 recent videos each; a very frequent uploader may not reach back a full 6 months). "
          "Topic buckets are keyword rules (`PEERS_TOPICS` in scout.py), so a title can sit in more than one and some are misfiled; read the titles. A topic on 2+ channels is the safest remake signal.", ""]
    if not multi:
        L.append("_No topic had a 3x+ outlier on two or more channels._")
    for t, rows_ in sorted(multi.items(), key=lambda kv: -len({x['handle'] for x in kv[1]})):
        chs = len({x["handle"] for x in rows_})
        L += [f"### {t} ({chs} channels, {len(rows_)} videos)"]
        for r in sorted(rows_, key=lambda r: -r["osc"]):
            L.append(f"- @{r['handle']} ({human(r['subs'])} subs): {r['osc']}x, {human(r['views'])} views, {r['age']}d, [{r['title'][:80]}](https://youtu.be/{r['id']})")
        L.append("")
    L += ["### One-off outliers (single channel, not a topic signal)", ""]
    seen_ids = {r["id"] for rs in multi.values() for r in rs}
    one = {}
    for t, r in singles:
        if r["id"] not in seen_ids:
            one[r["id"]] = (r, t)
    for r in untagged:
        if r["id"] not in seen_ids:
            one.setdefault(r["id"], (r, "uncategorised"))
    if not one:
        L.append("_None._")
    for r, t in sorted(one.values(), key=lambda x: -x[0]["osc"]):
        L.append(f"- @{r['handle']} ({human(r['subs'])} subs): {r['osc']}x, {human(r['views'])} views, {r['age']}d, [{r['title'][:80]}](https://youtu.be/{r['id']}) · {t}")
    L += ["", "## Remake brief CANDIDATES (for teardown, not scripts)", "",
          "Each is 5x+ its channel's median within 60 days. Per feedback_remake_full_teardown, none is scriptable until a full teardown (transcript, beat map, most-replayed, comments). Per feedback_niche_bend, an in-niche outlier means the topic is TAKEN: run the empty-cell check before filming. "
          "'What it is / why it popped' is local gemma from title and stats only (video not watched, guesses are guesses). 'Adam's angle' is hand-written per topic for his viewer: non-coder small-business owners.", ""]
    if not briefs:
        L.append("_No peer video cleared 5x its channel's median in the last 60 days._")
    for i, (p, v, topic, b) in enumerate(briefs, 1):
        on_multi = " (topic also hit on 2+ channels)" if topic in multi else ""
        L += [f"### {i}. {v['title']}", f"@{p['handle']} · {human(p['subs'])} subs · {human(v['views'])} views · {v['osc']}x median · {v['age']}d old · https://youtu.be/{v['id']} · topic: {topic or 'uncategorised'}{on_multi}", "",
              b, "", f"**Adam's angle:** {PEERS_ANGLES.get(topic, PEERS_DEFAULT_ANGLE)}", ""]
    open(path, "w").write("\n".join(L))
    print(f"\n  → Report saved: {path}")
    if args.save and top:
        data = load_watchlist()
        data["lists"][f"peers-{listname}"] = {"handles": [p["handle"] for p in top], "niche": listname}
        json.dump(data, open(WATCHLIST, "w"), indent=2)
        print(f"  → Saved {len(top)} handles to watchlist list 'peers-{listname}' (run: scout weekly --list peers-{listname})\n")

# ---------- Command: tiers (3-tier small-channel study) ----------

DEFAULT_TIERS = "1K-10K,10K-50K,50K-250K"

def _parse_count(s):
    """'10K' -> 10000, '2.5M' -> 2500000, '1000' -> 1000."""
    s = s.strip().upper().replace(",", "").replace("_", "")
    mult = {"K": 1_000, "M": 1_000_000}.get(s[-1:], 1)
    return int(float(s[:-1] if mult > 1 else s) * mult)

def parse_tiers(spec):
    """'1K-10K,10K-50K' -> [(1000, 10000), (10000, 50000)]. Lower bound inclusive, upper exclusive."""
    tiers = []
    for part in spec.split(","):
        if not part.strip():
            continue
        lo, hi = part.split("-", 1)
        lo, hi = _parse_count(lo), _parse_count(hi)
        if hi <= lo:
            raise ValueError(f"tier {part.strip()!r}: upper bound must be above lower bound")
        tiers.append((lo, hi))
    return tiers

def _short_count(n):
    for unit, div in (("M", 1_000_000), ("K", 1_000)):
        if n >= div:
            return f"{n/div:g}{unit}"
    return str(n)

def tiers_study(channels, tiers, top=5, shorts="exclude", since_months=DEFAULT_SINCE_MONTHS,
                min_views=0, screen=False, drop_flagged=False, now=None):
    """Buckets channels by subscriber count and finds each tier's outliers.
    channels: [{"handle", "name", "subs", "videos": [...]}] (channel_dump shape plus a handle).
    Outlier multiple = video views / that channel's median views (over the same filtered set).
    Returns {"tiers": [...], "unbucketed": [...], "params": {...}}; plain data, JSON-safe."""
    screen = screen or drop_flagged
    out_tiers = []
    placed = set()
    for lo, hi in tiers:
        members, all_views, ch_meds, cand = [], [], [], []
        dropped = 0
        for c in channels:
            subs = c.get("subs")
            if subs is None or not (lo <= subs < hi):
                continue
            placed.add(id(c))
            vids = apply_since(apply_shorts([dict(v) for v in c.get("videos") or []], shorts), since_months, now)
            vids = [v for v in vids if (v.get("views") or 0) >= min_views]
            if not vids:
                continue
            med = statistics.median([v["views"] for v in vids]) or 1
            name = c.get("name") or c.get("handle") or "?"
            members.append(name)
            ch_meds.append(med)
            for v in vids:
                all_views.append(v["views"])
                row = {"channel": name, "handle": c.get("handle"), "subs": subs, "id": v.get("id"),
                       "title": v.get("title") or "", "views": v["views"], "date": v.get("date"),
                       "is_short": v["is_short"], "channel_median": med, "mult": round(v["views"] / med, 2)}
                if screen:
                    row["flags"] = screen_video(v, c.get("videos") or [], subs)
                    if drop_flagged and row["flags"]:
                        dropped += 1
                        continue
                cand.append(row)
        cand.sort(key=lambda r: (r["mult"], r["views"]), reverse=True)
        out_tiers.append({
            "tier": f"{_short_count(lo)}-{_short_count(hi)}", "min_subs": lo, "max_subs": hi,
            "channels": len(members), "channel_names": members, "videos": len(all_views),
            "median_views": statistics.median(all_views) if all_views else None,
            "median_channel_median": statistics.median(ch_meds) if ch_meds else None,
            "dropped_flagged": dropped, "top": cand[:top],
        })
    unbucketed = [{"channel": c.get("name") or c.get("handle") or "?", "subs": c.get("subs")}
                  for c in channels if id(c) not in placed]
    return {"tiers": out_tiers, "unbucketed": unbucketed,
            "params": {"shorts": shorts, "since_months": since_months, "min_views": min_views,
                       "top": top, "screen": screen, "drop_flagged": drop_flagged}}

def load_channels_json(path):
    """Offline channel data: a list of channels, or {"channels": [...]}, in channel_dump shape."""
    data = json.load(open(path, encoding="utf-8"))
    chans = data.get("channels", []) if isinstance(data, dict) else data
    return [c for c in chans if isinstance(c, dict)]

def cmd_tiers(args):
    try:
        tiers = parse_tiers(args.tiers)
    except ValueError as e:
        print(f"  ! --tiers: {e}"); return
    if args.input:
        try:
            channels = load_channels_json(args.input)
        except (OSError, ValueError) as e:
            print(f"  ! could not read {args.input}: {e}"); return
    else:
        handles = [h.strip().lstrip("@") for h in args.handles if h.strip()]
        if args.list or not handles:
            name, lst = _active_list(load_watchlist(), args.list)
            handles += [h for h in lst.get("handles", []) if h not in handles]
        if not handles:
            print("\n  No channels. Pass handles, --list <watchlist>, or --input channels.json\n"); return
        channels = []
        for h in handles:
            ch = channel_dump(h, limit=args.scan)
            if ch.get("error"):
                sys.stderr.write(f"  ! {h}: {ch['error'][:80]}\n"); continue
            channels.append(dict(ch, handle=h))
    res = tiers_study(channels, tiers, top=args.top, shorts=args.shorts, since_months=args.since_months,
                      min_views=args.min_views, screen=args.screen, drop_flagged=args.drop_flagged)
    if args.json:
        print(json.dumps(res, indent=2))
        return
    print(f"\n\033[1mTIER STUDY\033[0m  {len(channels)} channels, {len(tiers)} tiers by subscriber count\n")
    summary = []
    for t in res["tiers"]:
        best = t["top"][0]["mult"] if t["top"] else None
        hm = lambda n: human(n) if n is not None else "-"
        summary.append([t["tier"], t["channels"], t["videos"], hm(t["median_views"]),
                        hm(t["median_channel_median"]), f"{best}x" if best is not None else "-"])
    print(table(summary, ["Tier", "Channels", "Videos", "MedViews", "MedChanMed", "TopMult"]))
    for t in res["tiers"]:
        print(f"\n  \033[1m{t['tier']} subs\033[0m  top {len(t['top'])} outliers")
        if not t["top"]:
            print("  (no eligible videos in this tier)")
            continue
        rows = []
        for r in t["top"]:
            row = [f"{r['mult']}x", human(r["views"]), human(r["subs"]), r["channel"][:16], r["title"][:52]]
            if args.screen or args.drop_flagged:
                row.append(", ".join(r["flags"]) or "ok")
            rows.append(row)
        headers = ["Mult", "Views", "Subs", "Channel", "Title"] + (["Flags"] if args.screen or args.drop_flagged else [])
        print("  " + table(rows, headers).replace("\n", "\n  "))
        if t["dropped_flagged"]:
            print(f"  dropped {t['dropped_flagged']} flagged (--drop-flagged)")
    if res["unbucketed"]:
        print(f"\n  Outside every tier: " + ", ".join(f"{u['channel']} ({human(u['subs'])})" for u in res["unbucketed"]))
    window = f"last {args.since_months:g} months" if args.since_months else "all uploads"
    print(f"\n  Mult = video views ÷ that channel's median ({window}, Shorts: {args.shorts}). MedViews = median of every")
    print(f"  video in the tier; MedChanMed = median of the channels' medians. Tiers are lower-bound inclusive.")
    if args.screen or args.drop_flagged:
        print(f"  {SCREEN_LEGEND}")
    print()

# ---------- Command: social-audit (Instagram / Facebook export, offline, zero AI) ----------
# Reads a Meta "Download your information" JSON or a simple list of post dicts. No scraping,
# no network, no model calls. Topics are keyword clusters, not LLM labels.

SA_FORMATS = ["Reel", "Carousel", "Single image", "Text"]
SA_TIERS = (10, 5, 3)
SA_DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
SA_STOP = set("""a about after again all also am an and any are as at be because been before being
but by can could did do does doing done don't for from get got had has have here how i i'm if in into
is it it's its just like me more most my new no not now of off on one only or our out over really so
some than that that's the their them then there these they this those to too up us very was we were
what when where which who why will with would you your you're yours ours via amp""".split())

def _sa_fix(s):
    """Meta exports write UTF-8 bytes as latin-1 escapes (\\u00e2\\u0080\\u0099); undo that."""
    if not isinstance(s, str):
        return ""
    try:
        return s.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return s

def _sa_num(*vals):
    for v in vals:
        if isinstance(v, bool):
            continue
        if isinstance(v, (int, float)):
            return v
        if isinstance(v, str) and v.strip():
            try:
                return _parse_count(v)
            except (ValueError, TypeError):
                continue
    return None

def _sa_ts(v):
    """Unix seconds (int/str) or ISO-8601 ('2026-05-01T12:00:00+0000') -> unix seconds, else None."""
    import datetime as dt
    if isinstance(v, bool) or v in (None, ""):
        return None
    if isinstance(v, (int, float)):
        return float(v / 1000 if v > 1e11 else v)
    s = str(v).strip()
    if re.fullmatch(r"\d+(\.\d+)?", s):
        return _sa_ts(float(s))
    s = re.sub(r"Z$", "+00:00", s)
    s = re.sub(r"([+-]\d\d)(\d\d)$", r"\1:\2", s)
    try:
        d = dt.datetime.fromisoformat(s)
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=dt.timezone.utc)
    return d.timestamp()

_SA_VIDEO_EXT = (".mp4", ".mov", ".m4v", ".webm")

def _sa_format_from_type(mt, product=None):
    mt, product = str(mt or "").upper(), str(product or "").upper()
    if "CAROUSEL" in mt or "ALBUM" in mt:
        return "Carousel"
    if "REEL" in mt or "REEL" in product or "VIDEO" in mt:
        return "Reel"
    if mt in ("IMAGE", "PHOTO", "SINGLE", "SINGLE_IMAGE", "SINGLE IMAGE"):
        return "Single image"
    if mt in ("TEXT", "STATUS", "LINK"):
        return "Text"
    return None

def _sa_simple(d):
    caption = d.get("caption") or d.get("message") or d.get("text") or d.get("title") or ""
    if isinstance(caption, dict):
        caption = caption.get("text") or ""
    fmt = _sa_format_from_type(d.get("media_type") or d.get("type") or d.get("format"),
                               d.get("media_product_type"))
    if fmt is None:
        fmt = "Text" if not (d.get("media_url") or d.get("children")) else "Single image"
    return {
        "id": str(d.get("id") or d.get("shortcode") or ""),
        "caption": str(caption),
        "format": fmt,
        "ts": _sa_ts(d.get("timestamp") or d.get("taken_at") or d.get("created_time")
                     or d.get("creation_timestamp")),
        "views": _sa_num(d.get("views"), d.get("plays"), d.get("video_views"), d.get("play_count"),
                         d.get("view_count"), d.get("ig_reels_aggregated_all_plays_count")),
        "likes": _sa_num(d.get("like_count"), d.get("likes"), d.get("reactions")),
        "comments": _sa_num(d.get("comments_count"), d.get("comments"), d.get("comment_count")),
        "permalink": str(d.get("permalink") or d.get("permalink_url") or d.get("url") or ""),
    }

def _sa_meta_media(post):
    """Media list from an IG posts_N.json entry or an FB your_posts entry."""
    media = list(post.get("media") or [])
    for att in post.get("attachments") or []:
        for item in (att or {}).get("data") or []:
            if isinstance(item, dict) and isinstance(item.get("media"), dict):
                media.append(item["media"])
    return [m for m in media if isinstance(m, dict)]

def _sa_meta(post, reel=False):
    media = _sa_meta_media(post)
    caption = post.get("title") or ""
    for item in post.get("data") or []:
        if isinstance(item, dict) and item.get("post"):
            caption = item["post"]
    if not caption and media:
        caption = media[0].get("title") or media[0].get("description") or ""
    is_video = any(str(m.get("uri", "")).lower().endswith(_SA_VIDEO_EXT) for m in media)
    if reel or (is_video and len(media) == 1):
        fmt = "Reel"
    elif len(media) > 1:
        fmt = "Carousel"
    elif media:
        fmt = "Single image"
    else:
        fmt = "Text"
    ts = post.get("creation_timestamp") or post.get("timestamp") or (media[0].get("creation_timestamp") if media else None)
    stats = {}
    for m in media[:1]:
        stats.update(m.get("media_metadata", {}).get("insights") or {})
    stats.update(post.get("insights") or {})
    simple = _sa_simple(dict(stats, **{k: v for k, v in post.items() if k in (
        "id", "views", "plays", "like_count", "likes", "comments_count", "comments", "permalink")}))
    return dict(simple, caption=_sa_fix(caption), format=fmt, ts=_sa_ts(ts))

def load_social_export(path):
    """Returns (posts, source) where source is 'simple' or 'meta'. Posts carry
    id, caption, format, ts, views, likes, comments, permalink."""
    data = json.load(open(path, encoding="utf-8"))
    posts, source = [], "simple"
    if isinstance(data, dict):
        if "ig_reels_media" in data:
            return [_sa_meta(p, reel=True) for p in data["ig_reels_media"] if isinstance(p, dict)], "meta"
        for key in ("data", "posts", "media", "items"):
            if isinstance(data.get(key), list):
                data = data[key]; break
        else:
            data = []
    for d in data if isinstance(data, list) else []:
        if not isinstance(d, dict):
            continue
        if any(k in d for k in ("media_type", "caption", "like_count", "permalink", "plays", "views")):
            posts.append(_sa_simple(d))
        elif any(k in d for k in ("media", "attachments", "creation_timestamp")) or (
                "timestamp" in d and isinstance(d.get("data"), list)):
            posts.append(_sa_meta(d)); source = "meta"
        else:
            posts.append(_sa_simple(d))
    return posts, source

def _sa_tokens(caption):
    words = re.findall(r"#?[a-z0-9][a-z0-9']+", (caption or "").lower())
    out = set()
    for w in words:
        w = w.lstrip("#").strip("'")
        if len(w) < 3 or w in SA_STOP or w.isdigit():
            continue
        if len(w) > 4 and w.endswith("s") and not w.endswith("ss"):
            w = w[:-1]
        out.add(w)
    return out

def _sa_topics(posts, max_topics=8, min_posts=2):
    """Greedy keyword clustering: repeatedly take the keyword shared by the most still-unassigned
    posts (ties alphabetical), assign those posts to it. Leftovers go to 'other'."""
    toks = [_sa_tokens(p["caption"]) for p in posts]
    left = set(range(len(posts)))
    topics = []
    while left and len(topics) < max_topics:
        counts = {}
        for i in left:
            for w in toks[i]:
                counts[w] = counts.get(w, 0) + 1
        if not counts:
            break
        word, n = min(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        if n < min_posts:
            break
        members = sorted(i for i in left if word in toks[i])
        # name the cluster by its two most common words, keyword first
        co = {}
        for i in members:
            for w in toks[i] - {word}:
                co[w] = co.get(w, 0) + 1
        second = min(co.items(), key=lambda kv: (-kv[1], kv[0])) if co else None
        label = word + (f" / {second[0]}" if second and second[1] >= max(2, len(members) / 2) else "")
        topics.append((word, label, members))
        left -= set(members)
    if left:
        topics.append(("other", "other", sorted(left)))
    return topics

def _sa_median(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None

def social_audit(posts, tz_offset=0.0, max_topics=8, source="simple"):
    """The whole audit as a JSON-able dict. Pure: no I/O."""
    n = len(posts)
    has_views = any(p["views"] is not None for p in posts)
    has_likes = any(p["likes"] is not None for p in posts)
    total_views = sum(p["views"] or 0 for p in posts)
    share = lambda a, b: round(a / b, 4) if b else None

    fmt = []
    for f in SA_FORMATS:
        ps = [p for p in posts if p["format"] == f]
        v = sum(p["views"] or 0 for p in ps)
        fmt.append({"format": f, "posts": len(ps), "share_posts": share(len(ps), n),
                    "views": v if has_views else None,
                    "share_views": share(v, total_views) if has_views else None,
                    "median_views": _sa_median(p["views"] for p in ps),
                    "median_likes": _sa_median(p["likes"] for p in ps)})

    topics, topic_of = [], {}
    for word, label, idx in _sa_topics(posts, max_topics=max_topics):
        ps = [posts[i] for i in idx]
        topic_of.update((i, label) for i in idx)
        topics.append({"topic": label, "keyword": word, "posts": len(ps), "share_posts": share(len(ps), n),
                       "median_views": _sa_median(p["views"] for p in ps),
                       "median_likes": _sa_median(p["likes"] for p in ps),
                       "examples": [p["caption"][:80] for p in ps[:3]]})

    metric = "views" if has_views else ("likes" if has_likes else None)
    med = _sa_median(p[metric] for p in posts) if metric else None
    outliers = []
    if metric and med:
        for i, p in enumerate(posts):
            val = p[metric]
            if val is None:
                continue
            mult = val / med
            tier = next((t for t in SA_TIERS if mult >= t), None)
            if tier:
                outliers.append({"id": p["id"], "caption": p["caption"][:140], "format": p["format"],
                                 "topic": topic_of.get(i), metric: val, "mult": round(mult, 2),
                                 "tier": f"{tier}x", "permalink": p["permalink"],
                                 "date": _sa_date(p["ts"], tz_offset)})
        outliers.sort(key=lambda o: -o["mult"])
    tier_counts = {f"{t}x": sum(1 for o in outliers if o["tier"] == f"{t}x") for t in SA_TIERS}

    return {"source": source, "posts": n, "has_views": has_views, "has_likes": has_likes,
            "formats": fmt, "topics": topics,
            "outliers": {"metric": metric, "median": med, "tiers": tier_counts, "posts": outliers},
            "cadence": _sa_cadence(posts, tz_offset), "tz_offset": tz_offset}

def _sa_local(ts, tz_offset):
    import datetime as dt
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc) + dt.timedelta(hours=tz_offset)

def _sa_date(ts, tz_offset):
    return _sa_local(ts, tz_offset).strftime("%Y-%m-%d") if ts is not None else None

def _sa_cadence(posts, tz_offset):
    timed = sorted((p for p in posts if p["ts"] is not None), key=lambda p: p["ts"])
    heat = [[0] * 24 for _ in range(7)]
    day_views = [[] for _ in range(7)]
    months = {}
    for p in timed:
        d = _sa_local(p["ts"], tz_offset)
        heat[d.weekday()][d.hour] += 1
        day_views[d.weekday()].append(p["views"])
        months[d.strftime("%Y-%m")] = months.get(d.strftime("%Y-%m"), 0) + 1
    gaps = [(b["ts"] - a["ts"]) / 86400 for a, b in zip(timed, timed[1:])]
    span = (timed[-1]["ts"] - timed[0]["ts"]) / 86400 if len(timed) > 1 else 0
    by_day = [{"day": SA_DAYS[i], "posts": sum(heat[i]), "median_views": _sa_median(day_views[i])}
              for i in range(7)]
    hours = [sum(heat[d][h] for d in range(7)) for h in range(24)]
    busiest = max(range(24), key=lambda h: (hours[h], -h)) if timed else None
    return {"timed_posts": len(timed), "untimed_posts": len(posts) - len(timed),
            "first": _sa_date(timed[0]["ts"], tz_offset) if timed else None,
            "last": _sa_date(timed[-1]["ts"], tz_offset) if timed else None,
            "span_days": round(span, 1),
            "posts_per_week": round(len(timed) / (span / 7), 2) if span >= 1 else None,
            "median_gap_days": round(statistics.median(gaps), 2) if gaps else None,
            "longest_gap_days": round(max(gaps), 1) if gaps else None,
            "per_month": [{"month": m, "posts": c} for m, c in sorted(months.items())],
            "by_day": by_day, "busiest_hour": busiest, "heat": heat}

def _sa_pct(x):
    return "n/a" if x is None else f"{x * 100:.0f}%"

def _sa_h(x):
    return "n/a" if x is None else human(x)

_SA_CSS = """
.sa-sec { margin-bottom:56px; }
.bar { height:8px; background:var(--hairline); border-radius:2px; min-width:80px; }
.bar i { display:block; height:8px; background:var(--ink); border-radius:2px; }
.bar.v i { background:var(--ember); }
table.heat { border-collapse:collapse; font-family:var(--font-data); font-size:11px; }
table.heat th { color:var(--muted); font-weight:500; padding:2px 3px; text-align:center; }
table.heat td { width:22px; height:22px; text-align:center; border:1px solid var(--ground); }
.tier { font-family:var(--font-data); font-weight:700; }
.tier.t10 { color:var(--ember); }
.stats { display:flex; flex-wrap:wrap; gap:40px; margin-top:18px; }
.stats div { font-family:var(--font-data); font-size:13px; color:var(--muted); }
.stats b { display:block; font-family:var(--font-display); font-size:28px; color:var(--ink); letter-spacing:-0.02em; }
.scroll { overflow-x:auto; }
"""

def _sa_bar(x, cls=""):
    w = 0 if not x else max(1, round(x * 100))
    return f"<div class='bar {cls}'><i style='width:{w}%'></i></div>"

def _write_social_audit_html(res, label, path):
    e = _dash_esc
    num = lambda x: f"<td class=num>{e(x)}</td>"
    rows = lambda rs: "".join(f"<tr{' class=alt' if i % 2 else ''}>{r}</tr>" for i, r in enumerate(rs))
    fmt_rows = rows(
        f"<td>{e(f['format'])}</td>{num(f['posts'])}{num(_sa_pct(f['share_posts']))}"
        f"<td>{_sa_bar(f['share_posts'])}</td>{num(_sa_pct(f['share_views']))}"
        f"<td>{_sa_bar(f['share_views'], 'v')}</td>{num(_sa_h(f['median_views']))}{num(_sa_h(f['median_likes']))}"
        for f in res["formats"])
    top_rows = rows(
        f"<td>{e(t['topic'])}</td>{num(t['posts'])}{num(_sa_pct(t['share_posts']))}"
        f"{num(_sa_h(t['median_views']))}{num(_sa_h(t['median_likes']))}<td>{e(' | '.join(t['examples']))}</td>"
        for t in res["topics"])
    o = res["outliers"]
    m = o["metric"]
    def cap(x):
        c = e(x["caption"] or "(no caption)")
        return f"<a href='{e(x['permalink'])}'>{c}</a>" if x["permalink"].startswith("https://") else c
    out_rows = rows(
        f"<td><span class='tier t{x['tier'][:-1]}'>{e(x['tier'])}</span></td>{num(f"{x['mult']:.1f}x")}"
        f"{num(_sa_h(x[m]))}<td>{e(x['format'])}</td><td>{e(x['topic'] or '')}</td><td>{e(x['date'] or '')}</td><td>{cap(x)}</td>"
        for x in o["posts"]) or "<tr><td class=empty colspan=7>No post reached 3x the account median.</td></tr>"
    c = res["cadence"]
    peak = max([max(r) for r in c["heat"]] + [1])
    heat = "<tr><th></th>" + "".join(f"<th>{h}</th>" for h in range(24)) + "<th>Σ</th><th>med</th></tr>"
    for d, r in enumerate(c["heat"]):
        cells = "".join(
            f"<td style='background:rgba(217,84,30,{v / peak * 0.9 + 0.05 if v else 0:.2f})' title='{SA_DAYS[d]} {h}:00, {v} posts'>{v or ''}</td>"
            for h, v in enumerate(r))
        bd = c["by_day"][d]
        heat += f"<tr><th>{SA_DAYS[d]}</th>{cells}<th>{bd['posts']}</th><th>{e(_sa_h(bd['median_views']))}</th></tr>"
    month_rows = rows(f"<td>{e(x['month'])}</td>{num(x['posts'])}" for x in c["per_month"])
    tz = f"UTC{res['tz_offset']:+g}" if res["tz_offset"] else "UTC"
    metric_note = {"views": "plays/views", "likes": "likes (no view counts in this export)"}.get(m, "no metrics in this export")
    stat = lambda k, v: f"<div><b>{e(v)}</b>{e(k)}</div>"
    hero = o["posts"][0]["mult"] if o["posts"] else 0
    doc = f"""<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>ytscout social audit</title><style>{_DASH_CSS}{_SA_CSS}</style>
<div class=wrap>
<div class=page-head><p class=eyebrow>ytscout · social audit · {e(res['source'])} export</p>
<h1>Social audit: {e(label)}</h1>
<p>{res['posts']} posts read from a local export. Outliers are measured on {e(metric_note)}. Topics are keyword clusters from captions, no AI. Times in {e(tz)}.</p></div>
<div class=hero><p class=label>Top post vs account median</p><p class=hero-num>{hero:.1f}x</p>
<p class=hero-sub>{o['tiers']['10x']} posts at 10x+, {o['tiers']['5x']} at 5-10x, {o['tiers']['3x']} at 3-5x. Account median {e(_sa_h(o['median']))} {e(m or '')}.</p></div>
<div class=sa-sec><h2>Format mix</h2><p>Share of posts (ink) against share of views (ember). A format whose ember bar outruns its ink bar is earning more than its slot.</p>
<div class=scroll><table class=outliers><tr><th>Format</th><th class=num>Posts</th><th class=num>Share</th><th></th><th class=num>Views share</th><th></th><th class=num>Med views</th><th class=num>Med likes</th></tr>{fmt_rows}</table></div></div>
<div class=sa-sec><h2>Topic mix</h2><p>Each post sits in one cluster: the keyword shared by the most remaining captions.</p>
<div class=scroll><table class=outliers><tr><th>Topic</th><th class=num>Posts</th><th class=num>Share</th><th class=num>Med views</th><th class=num>Med likes</th><th>Examples</th></tr>{top_rows}</table></div></div>
<div class=sa-sec><h2>Outliers</h2><p>Posts at 3x, 5x and 10x the account median {e(m or '')}.</p>
<div class=scroll><table class=outliers><tr><th>Tier</th><th class=num>vs Med</th><th class=num>{e((m or '').title())}</th><th>Format</th><th>Topic</th><th>Date</th><th>Caption</th></tr>{out_rows}</table></div></div>
<div class=sa-sec><h2>Posting cadence</h2>
<div class=stats>{stat('posts per week', c['posts_per_week'] if c['posts_per_week'] is not None else 'n/a')}{stat('median gap, days', c['median_gap_days'] if c['median_gap_days'] is not None else 'n/a')}{stat('longest gap, days', c['longest_gap_days'] if c['longest_gap_days'] is not None else 'n/a')}{stat('busiest hour', f"{c['busiest_hour']}:00" if c['busiest_hour'] is not None else 'n/a')}</div>
<p style="margin-top:18px">{e(c['first'] or '')} to {e(c['last'] or '')}{f", {c['untimed_posts']} posts without a timestamp" if c['untimed_posts'] else ''}.</p>
<h2 style="margin-top:40px">Day / hour</h2><p>Posts per weekday and hour ({e(tz)}); last columns are the day total and the day's median views.</p>
<div class=scroll><table class=heat>{heat}</table></div>
<h2 style="margin-top:40px">Per month</h2><table class=outliers style="max-width:320px"><tr><th>Month</th><th class=num>Posts</th></tr>{month_rows}</table></div>
<div class=page-foot><p>Built offline from your own export. No scraping, no network, no model calls. A multiple is a reason to study the post, not a verdict.</p></div>
</div>"""
    open(path, "w", encoding="utf-8").write(doc)
    return path

def cmd_social_audit(args):
    try:
        posts, source = load_social_export(args.export)
    except (OSError, ValueError) as ex:
        print(f"  ! could not read {args.export}: {ex}"); return
    if not posts:
        print(f"  ! no posts found in {args.export}"); return
    res = social_audit(posts, tz_offset=args.tz, max_topics=args.topics, source=source)
    label = args.label or os.path.splitext(os.path.basename(args.export))[0]
    out = args.out or REPORT_DIR
    os.makedirs(out, exist_ok=True)
    jpath = os.path.join(out, "social-audit.json")
    json.dump(dict(res, label=label), open(jpath, "w", encoding="utf-8"), indent=2)
    hpath = _write_social_audit_html(res, label, os.path.join(out, "social-audit.html"))
    if args.json:
        print(json.dumps(dict(res, label=label), indent=2)); return
    print(f"\n  SOCIAL AUDIT: {label} · {res['posts']} posts ({source} export)\n")
    print(table([[f["format"], f["posts"], _sa_pct(f["share_posts"]), _sa_pct(f["share_views"]),
                  _sa_h(f["median_views"])] for f in res["formats"]],
                ["Format", "Posts", "Share", "Views share", "Med views"]))
    print()
    print(table([[t["topic"], t["posts"], _sa_h(t["median_views"]), _sa_h(t["median_likes"])]
                 for t in res["topics"]], ["Topic", "Posts", "Med views", "Med likes"]))
    o = res["outliers"]
    print(f"\n  Outliers on {o['metric'] or 'n/a'} (median {_sa_h(o['median'])}): "
          + f"10x+ {o['tiers']['10x']}, 5-10x {o['tiers']['5x']}, 3-5x {o['tiers']['3x']}")
    for x in o["posts"][:10]:
        print(f"   {x['tier']:>4} {x['mult']:>6.1f}x  {x['format']:<12} {x['caption'][:60]}")
    c = res["cadence"]
    print(f"\n  Cadence: {c['posts_per_week'] or 'n/a'}/week, median gap {c['median_gap_days'] or 'n/a'}d, "
          f"longest {c['longest_gap_days'] or 'n/a'}d, busiest hour {c['busiest_hour']}:00")
    print(f"  → JSON: {jpath}\n  → HTML report: {hpath}\n")

# ---------- Command: dash (offline HTML assembly, zero AI, zero network by default) ----------
# Pure read/render layer. Nothing below may import yt_dlp or call ollama/_ydl/_fetch_json/
# channel_dump/search_dump/_curl_json or open a socket. cmd_dash's --refresh branch is the
# one exception, and it is gated by an AST check in the plan's verification.

def _dash_num(s):
    """'3.89x' -> 3.89, '126.2K' -> 126200, '$1.3k' -> 1300. 0.0 on anything unparseable."""
    if not s:
        return 0.0
    s = str(s).strip()
    m = re.search(r"[\d.]+", s)
    if not m:
        return 0.0
    try:
        n = float(m.group(0))
    except Exception:
        return 0.0
    low = s.lower()
    if "k" in low:
        n *= 1000
    elif "m" in low:
        n *= 1_000_000
    return n

def _parse_weekly_md(path):
    """Parse one weekly*.md report. Returns None on any unreadable file, never raises."""
    try:
        if not os.path.exists(path):
            return None
        text = open(path, encoding="utf-8", errors="replace").read()
    except Exception:
        return None
    lines = text.splitlines()
    date = None
    niche = None
    rpm = None
    handles = []
    for line in lines:
        if line.startswith("#") and date is None:
            m = re.search(r"(\d{4}-\d{2}-\d{2})", line)
            if m:
                date = m.group(1)
        if line.strip().lower().startswith("channels:"):
            nm = re.search(r"niche:\s*([^\s(]+)", line)
            rm = re.search(r"\$([\d.]+)\s*RPM", line)
            niche = nm.group(1) if nm else None
            rpm = float(rm.group(1)) if rm else None
            handles = re.findall(r"@([A-Za-z0-9_.-]+)", line)
    if date is None:
        m = re.search(r"(\d{4}-\d{2}-\d{2})", os.path.basename(path))
        if m:
            date = m.group(1)
    if date is None:
        try:
            date = time.strftime("%Y-%m-%d", time.localtime(os.path.getmtime(path)))
        except Exception:
            date = None
    rows = []
    for line in lines:
        if not line.startswith("|"):
            continue
        try:
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) < 8:
                continue
            if cells[0].strip().lower() == "new" and cells[1].strip().lower() == "v/sub":
                continue  # header row (distinguish from a data row whose New flag is "NEW")
            if all(set(c) <= {"-"} for c in cells if c):
                continue  # separator row
            new = cells[0].upper() == "NEW"
            vsub = cells[1]
            vsmed = cells[2]
            views = cells[3]
            est = cells[4]
            channel = cells[5]
            link = cells[-1]
            title = " | ".join(cells[6:-1]).strip()
            if vsub in ("—", "-", ""):
                vsub = "n/a"
            row = {
                "new": new, "vsub": vsub, "vsmed": vsmed, "views": views, "est": est,
                "channel": channel, "title": title, "link": link,
                "vsmed_n": _dash_num(vsmed), "views_n": _dash_num(views), "est_n": _dash_num(est),
            }
            rows.append(row)
        except Exception:
            continue
    return {
        "path": path, "file": os.path.basename(path), "date": date, "niche": niche,
        "rpm": rpm, "handles": handles, "rows": rows,
    }

def _dash_cron_status(report_dir=None):
    """Reads weekly-cron.log/.err. Never raises; returns safe defaults on any exception."""
    report_dir = report_dir if report_dir is not None else REPORT_DIR
    out = {"present": False, "log_mtime": None, "err_mtime": None, "age_days": None,
           "error_lines": 0, "last_line": None}
    try:
        log_path = os.path.join(report_dir, "weekly-cron.log")
        err_path = os.path.join(report_dir, "weekly-cron.err")
        out["present"] = os.path.exists(log_path)
        if out["present"]:
            out["log_mtime"] = os.path.getmtime(log_path)
            out["age_days"] = int((time.time() - out["log_mtime"]) // 86400)
            try:
                lines = [l for l in open(log_path, encoding="utf-8", errors="replace").read().splitlines() if l.strip()]
                if lines:
                    last = re.sub(r"\x1b\[[0-9;]*m", "", lines[-1])
                    out["last_line"] = last[:120]
            except Exception:
                pass
        if os.path.exists(err_path):
            out["err_mtime"] = os.path.getmtime(err_path)
            try:
                err_text = open(err_path, encoding="utf-8", errors="replace").read()
                out["error_lines"] = sum(1 for l in err_text.splitlines() if l.startswith("ERROR:"))
            except Exception:
                pass
    except Exception:
        pass
    return out

def _dash_collect(report_dir=None, wl=None):
    """Pure offline assembly of the whole dashboard payload. Never raises."""
    report_dir = report_dir if report_dir is not None else REPORT_DIR
    wl = wl if wl is not None else load_watchlist()
    payload = {"reports": [], "lists": [], "trend": [], "latest": None,
               "rpm": {"value": DEFAULT_RPM, "niche": None, "source": "fallback default"},
               "seen_count": 0, "cron": _dash_cron_status(report_dir)}
    try:
        paths = sorted(glob.glob(os.path.join(report_dir, "weekly*.md")))
    except Exception:
        paths = []
    reports = []
    for p in paths:
        r = _parse_weekly_md(p)
        if r is not None:
            reports.append(r)
    reports.sort(key=lambda r: (r["date"] or "", r["file"]))
    payload["reports"] = reports
    active_name = wl.get("active")
    active_niche = None
    if active_name and active_name in wl.get("lists", {}):
        active_niche = wl["lists"][active_name].get("niche")
    latest = None
    if active_niche:
        for r in reversed(reports):
            if r["niche"] == active_niche:
                latest = r
                break
    if latest is None and reports:
        latest = reports[-1]
    payload["latest"] = latest
    # The trend must be ONE watchlist over time, not every list interleaved. Reports from
    # different niches on the same date are different runs of different channel sets, so
    # plotting them side by side would read as a rise or fall that never happened. Scope to
    # the niche we are actually showing, then drop same-date duplicates (the untagged
    # weekly-DATE.md filename predates the tagged one and repeats a run already counted).
    trend_niche = (latest or {}).get("niche") if latest else None
    trend_src = [r for r in reports if r["niche"] == trend_niche] if trend_niche else reports
    seen_dates, deduped = set(), []
    for r in trend_src:
        key = (r["date"], r["niche"])
        if key in seen_dates:
            continue
        seen_dates.add(key)
        deduped.append(r)
    payload["trend_niche"] = trend_niche
    payload["trend_skipped"] = len(reports) - len(deduped)
    payload["trend"] = [
        {"date": r["date"], "niche": r["niche"], "new": sum(1 for row in r["rows"] if row["new"]),
         "total": len(r["rows"])}
        for r in deduped
    ]
    lists = []
    for name, l in wl.get("lists", {}).items():
        niche = l.get("niche")
        lists.append({
            "name": name, "niche": niche, "count": len(l.get("handles", [])),
            "active": name == active_name, "rpm": real_rpm(niche),
        })
    payload["lists"] = lists
    rpm_niche = active_niche or (latest["niche"] if latest else None)
    rpm_value = real_rpm(rpm_niche)
    source = "fallback default"
    try:
        cfg_path = os.path.expanduser("~/ytscout/rpm.json")
        if os.path.exists(cfg_path):
            saved = json.load(open(cfg_path))
            if (rpm_niche and rpm_niche in saved) or "default" in saved:
                source = "your Studio number"
            elif rpm_niche in RPM_TIERS:
                source = "niche tier estimate"
        elif rpm_niche in RPM_TIERS:
            source = "niche tier estimate"
    except Exception:
        source = "fallback default"
    payload["rpm"] = {"value": rpm_value, "niche": rpm_niche, "source": source}
    try:
        seen_path = os.path.join(CACHE_DIR, "weekly_seen.json")
        if os.path.exists(seen_path):
            payload["seen_count"] = len(json.load(open(seen_path)))
    except Exception:
        payload["seen_count"] = 0
    return payload

_DASH_LINK_RE = re.compile(
    r"^https://(youtu\.be/[A-Za-z0-9_-]{6,20}|www\.youtube\.com/watch\?v=[A-Za-z0-9_-]{6,20})$")

def _dash_href(link):
    """Strict allowlist: only a real youtu.be/watch link is ever rendered as an anchor."""
    if link and _DASH_LINK_RE.match(link):
        return link
    return None

def _dash_esc(v):
    """html.escape plus an extra pass that neutralizes bare 'word=' attribute-look-alike
    sequences in third-party text, so a hostile title/channel string can never read back
    as an attribute-injection pattern even as inert escaped text."""
    s = html.escape(str(v if v is not None else ""), quote=True)
    return s.replace("=", "&#61;")

def _dash_title_html(row):
    href = _dash_href(row.get("link"))
    t = _dash_esc(row.get("title") or "(untitled)")
    if href:
        return f'<a class="v" href="{_dash_esc(href)}">{t}</a>'
    return f'<span class="v">{t}</span>'

def _dash_outlier_rows_html(rows):
    if not rows:
        return ('<tr><td class="empty" colspan="7">No outliers in the latest run. '
                'Run scout weekly to fill this in.</td></tr>')
    out = []
    for i, r in enumerate(rows):
        cls = ' class="alt"' if i % 2 == 1 else ""
        flag = '<span class="flag">NEW</span>' if r.get("new") else ""
        vsub = _dash_esc(r.get("vsub") or "n/a")
        vsmed = _dash_esc(r.get("vsmed") or "n/a")
        views = _dash_esc(r.get("views") or "n/a")
        est = _dash_esc(r.get("est") or "n/a")
        channel = f'<span class="v">{_dash_esc(r.get("channel") or "")}</span>'
        title = _dash_title_html(r)
        out.append(
            f"<tr{cls}><td>{flag}</td><td class=\"num\">{vsub}</td><td class=\"num\">{vsmed}</td>"
            f"<td class=\"num\">{views}</td><td class=\"num\">{est}</td><td>{channel}</td><td>{title}</td></tr>"
        )
    return "\n".join(out)

def _dash_trend_svg(trend):
    if not trend:
        return '<p class="empty">No runs on disk yet. Run scout weekly to start the trend.</p>'
    n = len(trend)
    bar_h = 140
    label_h = 24
    svg_h = bar_h + label_h
    w = max(360, n * 70)
    gap = 16.0
    bar_w = (w - gap * (n - 1)) / n if n > 1 else float(w)
    max_new = max((t.get("new") or 0) for t in trend) or 1
    parts = []
    for i, t in enumerate(trend):
        x = i * (bar_w + gap)
        newc = t.get("new") or 0
        bh = 2 if newc == 0 else max(4, round(bar_h * newc / max_new))
        y = bar_h - bh
        fill = "#D9541E" if i == n - 1 else "#EFE9E0"
        op = "" if i == n - 1 else ' opacity="0.45"'
        parts.append(f'<rect x="{x:.1f}" y="{y}" width="{bar_w:.1f}" height="{bh}" fill="{fill}"{op}></rect>')
        date = t.get("date") or ""
        mmdd = date[5:] if len(date) >= 10 else date
        lx = x + bar_w / 2
        parts.append(
            f'<text x="{lx:.1f}" y="{bar_h + 16}" font-size="11" fill="#EFE9E0" text-anchor="middle" '
            f'font-family="SF Mono, Menlo, ui-monospace, monospace">{_dash_esc(mmdd)}</text>'
        )
    bars = "\n".join(parts)
    return f'<svg viewBox="0 0 {w} {svg_h}" width="100%" height="{svg_h}" role="img" aria-label="run over run new outlier trend">{bars}</svg>'

_DASH_CSS = """
:root {
  --ground:#F7F4EF; --ink:#1A1815; --muted:#6E675C; --hairline:#E3DDD2;
  --dark-bg:#161310; --dark-ink:#EFE9E0; --ember:#D9541E;
  --font-display:"Iowan Old Style", Charter, Palatino, Georgia, serif;
  --font-body:-apple-system, "Avenir Next", "Helvetica Neue", sans-serif;
  --font-data:"SF Mono", Menlo, ui-monospace, monospace;
}
* { box-sizing: border-box; }
html, body { margin:0; padding:0; background:var(--ground); color:var(--ink); }
body { font-family:var(--font-body); font-size:15px; line-height:1.55; }
.wrap { max-width:1180px; margin:0 auto; padding:96px 32px 56px; }
.page-head { margin-bottom:56px; }
.eyebrow, .label { font-family:var(--font-data); font-size:11px; text-transform:uppercase; letter-spacing:.12em; color:var(--muted); margin:0 0 10px; }
h1 { font-family:var(--font-display); font-weight:700; font-size:34px; line-height:1.2; letter-spacing:-0.02em; margin:0 0 18px; text-wrap: balance; }
h2 { font-family:var(--font-display); font-weight:600; font-size:19px; line-height:1.2; letter-spacing:-0.02em; margin:0 0 18px; text-wrap: balance; }
p { max-width:66ch; color:var(--muted); text-wrap: pretty; margin:0; }
.layout { display:grid; grid-template-columns: minmax(0,1fr) 300px; gap:56px; }
@media (max-width: 900px) { .layout { grid-template-columns: 1fr; } }
.hero { margin-bottom:56px; }
.hero-num { font-family:var(--font-display); font-weight:700; font-size:88px; line-height:1.05; letter-spacing:-0.045em; color:var(--ember); margin:0; }
.hero-sub { font-size:15px; color:var(--ink); margin-top:10px; max-width:66ch; }
table.outliers { width:100%; border-collapse:collapse; font-family:var(--font-data); font-size:13px; line-height:1.4; }
table.outliers th { text-align:left; font-size:11px; text-transform:uppercase; letter-spacing:.12em; color:var(--muted); font-weight:500; padding:10px 8px; border-bottom:1px solid var(--hairline); }
table.outliers td { padding:10px 8px; vertical-align:top; }
table.outliers tr.alt td { background:rgba(26,24,21,0.035); }
table.outliers td.num, table.outliers th.num { text-align:right; }
table.outliers td.empty { color:var(--muted); font-family:var(--font-body); padding:30px 8px; }
.flag { color:var(--ember); font-weight:700; }
a { color:var(--ink); text-decoration:underline; text-decoration-color:var(--hairline); }
a:hover { color:var(--ember); }
.darkband { position:relative; background:var(--dark-bg); color:var(--dark-ink); margin:56px calc(50% - 50vw) 0; padding:56px 32px; overflow:hidden; }
.darkband .inner { max-width:1180px; margin:0 auto; position:relative; z-index:1; }
.darkband h2 { color:var(--dark-ink); }
.grain { position:absolute; inset:0; opacity:.07; pointer-events:none; }
.trend-caption { font-family:var(--font-data); font-size:11px; color:var(--dark-ink); opacity:.7; margin-top:18px; }
.rail > div { margin-bottom:56px; }
.rail > div:last-child { margin-bottom:0; }
.wl-item { margin-bottom:18px; font-size:15px; }
.wl-item:last-child { margin-bottom:0; }
.wl-name { font-weight:600; }
.wl-meta { font-family:var(--font-data); font-size:13px; color:var(--muted); display:block; margin-top:4px; }
.dot { margin-right:6px; vertical-align:middle; }
.rpm-val { font-family:var(--font-display); font-weight:700; font-size:34px; letter-spacing:-0.02em; color:var(--ink); }
.rpm-source { font-size:13px; color:var(--muted); margin-top:10px; }
.lr-date { font-family:var(--font-data); font-size:19px; font-weight:600; }
.lr-age { font-size:13px; color:var(--muted); margin-top:4px; }
.lr-line { font-family:var(--font-data); font-size:11px; color:var(--muted); margin-top:10px; word-break:break-word; }
.empty { color:var(--muted); font-size:15px; }
.wrap-foot { padding-top:0; }
.page-foot { margin-top:72px; padding-top:30px; border-top:1px solid var(--hairline); }
.page-foot p { font-size:13px; color:var(--muted); max-width:66ch; }
"""

def _write_dash_html(data, path=None):
    """Renders the whole self-contained dashboard.html from a _dash_collect payload.
    Zero network, zero model, zero images. Writes exactly one file and returns its path."""
    path = path or os.path.join(REPORT_DIR, "dashboard.html")
    latest = data.get("latest")
    latest_rows = (latest or {}).get("rows") or []

    lede = (f"Assembled from the run on {_dash_esc(latest['date'])}." if latest
            else "No weekly runs on disk yet. Run scout weekly to start one.")

    if latest_rows:
        top = latest_rows[0]
        hero_num = f"{top.get('vsmed_n', 0.0):.2f}x"
        hero_label = "TOP OUTLIER VS CHANNEL MEDIAN"
        hero_sub = (f'<span class="v">{_dash_esc(top.get("channel") or "")}</span>, '
                    f'{_dash_esc(top.get("views") or "n/a")} views')
    else:
        hero_num = "0"
        hero_label = "NO OUTLIERS IN THE LATEST RUN"
        hero_sub = "Run scout weekly to fill this in."

    outlier_rows_html = _dash_outlier_rows_html(latest_rows)

    trend = data.get("trend") or []
    trend_svg = _dash_trend_svg(trend)
    if trend:
        total_new = sum(t.get("new") or 0 for t in trend)
        span = f"{trend[0].get('date')} to {trend[-1].get('date')}"
        tn = data.get("trend_niche")
        scope = f"{_dash_esc(tn)} watchlist" if tn else "all watchlists"
        caption = (f"{len(trend)} {'run' if len(trend) == 1 else 'runs'} of the {scope}, "
                   f"{span}, {total_new} NEW outliers total.")
        skipped = data.get("trend_skipped") or 0
        if skipped:
            caption += (f" {skipped} report{'' if skipped == 1 else 's'} on disk "
                        f"{'is' if skipped == 1 else 'are'} from another watchlist or a "
                        f"duplicate of a run already counted, so held out of this line.")
    else:
        caption = "No trend yet. Run scout weekly to start one."

    lists = data.get("lists") or []
    if lists:
        wl_items = []
        for l in lists:
            dot = ('<svg class="dot" width="6" height="6" viewBox="0 0 6 6"><circle cx="3" cy="3" r="3" fill="#D9541E"></circle></svg>'
                   if l.get("active") else "")
            niche = _dash_esc(l.get("niche") or "no niche set")
            wl_items.append(
                f'<div class="wl-item">{dot}<span class="wl-name">{_dash_esc(l.get("name") or "")}</span>'
                f'<span class="wl-meta">{l.get("count", 0)} channels, {niche} niche</span></div>'
            )
        wl_html = "\n".join(wl_items)
    else:
        wl_html = '<p class="empty">No watchlists yet. Add one with scout watch --add.</p>'

    rpm = data.get("rpm") or {}
    rpm_val = rpm.get("value")
    rpm_html = (
        f'<div class="rpm-val">${rpm_val:.2f}</div>'
        f'<div class="rpm-source">Source: {_dash_esc(rpm.get("source") or "fallback default")}.</div>'
    ) if rpm_val is not None else '<p class="empty">No RPM on record. Set one with scout config --rpm.</p>'

    cron = data.get("cron") or {}
    if cron.get("present"):
        log_date = (time.strftime("%Y-%m-%d", time.localtime(cron["log_mtime"]))
                    if cron.get("log_mtime") else "unknown")
        age = cron.get("age_days")
        if age is None:
            age_words = "age unknown"
        elif age <= 0:
            age_words = "today"
        elif age == 1:
            age_words = "1 day ago"
        else:
            age_words = f"{age} days ago"
        err_lines = cron.get("error_lines") or 0
        last_line = cron.get("last_line") or ""
        lastrun_html = (
            f'<div class="lr-date">{_dash_esc(log_date)}</div>'
            f'<div class="lr-age">{_dash_esc(age_words)}, {err_lines} error line{"s" if err_lines != 1 else ""}</div>'
            f'<div class="lr-line"><span class="v">{_dash_esc(last_line)}</span></div>'
        )
    else:
        lastrun_html = '<p class="empty">The weekly job has not written a log here yet.</p>'

    gen_ts = time.strftime("%Y-%m-%d %H:%M")

    html_doc = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>ytscout dashboard</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>{_DASH_CSS}</style>
</head>
<body>
<div class="wrap">
  <header class="page-head">
    <div class="eyebrow">SCOUT</div>
    <h1>Idea farm</h1>
    <p>{lede}</p>
  </header>

  <div class="layout">
    <div class="col-wide">
      <section class="hero">
        <div class="hero-num">{hero_num}</div>
        <div class="label">{hero_label}</div>
        <div class="hero-sub">{hero_sub}</div>
      </section>

      <section class="outliers-section">
        <table class="outliers">
          <thead>
            <tr><th></th><th class="num">V/Sub</th><th class="num">vsMed</th><th class="num">Views</th>
                <th class="num">Est$</th><th>Channel</th><th>Title</th></tr>
          </thead>
          <tbody>
{outlier_rows_html}
          </tbody>
        </table>
      </section>
    </div>

    <aside class="col-rail rail">
      <div class="wl-block">
        <div class="label">WATCHLISTS</div>
        {wl_html}
      </div>
      <div class="rpm-block">
        <div class="label">RPM IN USE</div>
        {rpm_html}
      </div>
      <div class="lastrun-block">
        <div class="label">LAST RUN</div>
        {lastrun_html}
      </div>
    </aside>
  </div>
</div>

<div class="darkband">
  <div class="grain">
    <svg width="100%" height="100%">
      <filter id="dashgrain"><feTurbulence type="fractalNoise" baseFrequency="0.8" numOctaves="2" stitchTiles="stitch"></feTurbulence></filter>
      <rect width="100%" height="100%" filter="url(#dashgrain)"></rect>
    </svg>
  </div>
  <div class="inner">
    <h2>Run over run</h2>
    {trend_svg}
    <div class="trend-caption">{caption}</div>
  </div>
</div>

<div class="wrap wrap-foot">
  <footer class="page-foot">
    <p>Generated {gen_ts}. Assembled offline from files already on disk, no network call and no model
    call. Thumbnails are left out on purpose so this file stays under 150KB (reports/feed.html is
    3.1MB because it base64 embeds images).</p>
  </footer>
</div>
</body>
</html>
"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(html_doc)
    return path

def cmd_dash(args):
    if getattr(args, "refresh", False):
        print("  --refresh passed: running a live weekly scan first (this needs network)...")
        cmd_weekly(argparse.Namespace(scan=15, min_views=1000, niche=None, rpm=None, list=args.list, top=25,
                                      shorts="exclude", since_months=DEFAULT_SINCE_MONTHS))

    data = _dash_collect()
    path = _write_dash_html(data)

    reports = data.get("reports") or []
    latest = data.get("latest")
    lists = data.get("lists") or []
    active_name = next((l["name"] for l in lists if l.get("active")), None) or "none set"
    rpm = data.get("rpm") or {}
    latest_date = latest["date"] if latest else "n/a"
    new_count = sum(1 for r in (latest["rows"] if latest else []) if r.get("new"))

    if not reports:
        print("\n  No reports on disk yet. Run scout weekly first to fill in the outlier table and trend.")

    print(f"\n\033[1mSCOUT DASH\033[0m\n")
    print(table(
        [[str(len(reports)), latest_date, str(new_count), active_name, f"${rpm.get('value', 0.0):.2f}"]],
        ["Runs", "Latest", "NEW (latest)", "Active list", "RPM"],
    ))
    print(f"\n  -> Dashboard: {path}\n")

    if getattr(args, "open", False):
        import subprocess
        try:
            subprocess.run(["open", path])
        except Exception:
            pass

# ---------- Command: mine (YOUR OWN channel's private metrics via OAuth) ----------
# Uses curl for all Google HTTPS (this Python build has broken SSL certs) + stdlib loopback
# for the OAuth redirect. One-time setup: a Google Cloud "Desktop app" OAuth client.

OAUTH_DIR = os.path.expanduser("~/ytscout/.oauth")
OAUTH_PORT = 8731
SCOPES = "https://www.googleapis.com/auth/yt-analytics.readonly https://www.googleapis.com/auth/youtube.readonly"

def _curl_json(url, data=None, headers=None):
    """POST/GET via curl (SSL-safe on this box) → parsed JSON."""
    import subprocess
    cmd = ["curl", "-s", url]
    for k, v in (headers or {}).items():
        cmd += ["-H", f"{k}: {v}"]
    if data is not None:
        cmd += ["--data", data]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=60).stdout
        return json.loads(out) if out.strip() else {}
    except Exception as e:
        return {"error": str(e)}

def _load_client():
    p = os.path.join(OAUTH_DIR, "client_secret.json")
    if not os.path.exists(p):
        return None
    d = json.load(open(p))
    c = d.get("installed") or d.get("web") or d
    return {"id": c["client_id"], "secret": c["client_secret"]}

def _mine_setup_msg():
    print(f"""
  \033[1mscout mine — one-time setup (about 5 minutes, all free)\033[0m

  This reads YOUR channel's private stats (CTR, retention, real revenue) that no free tool can see
  without your permission. You authorize it once; the token stays on this machine.

  1. Go to  https://console.cloud.google.com/  → create a project (or use one you have).
  2. APIs & Services → Enable APIs → enable "YouTube Analytics API" and "YouTube Data API v3".
  3. APIs & Services → Credentials → Create Credentials → OAuth client ID → type "Desktop app".
     (If asked, configure the consent screen: External, add yourself as a test user.)
  4. Download the client JSON, save it as:  {OAUTH_DIR}/client_secret.json
  5. Run:  scout mine --auth   (opens your browser once to approve; then just `scout mine`)

  Nothing here costs money. The APIs are free; the token never leaves this machine.
""")

def _oauth_flow(client):
    import http.server, socketserver, webbrowser, urllib.parse
    code_box = {}
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            q = urllib.parse.urlparse(self.path).query
            code_box.update(urllib.parse.parse_qs(q))
            self.send_response(200); self.end_headers()
            self.wfile.write(b"<h2>ytscout authorized. You can close this tab.</h2>")
        def log_message(self, *a):
            pass
    redirect = f"http://localhost:{OAUTH_PORT}"
    auth_url = ("https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode({
        "client_id": client["id"], "redirect_uri": redirect, "response_type": "code",
        "scope": SCOPES, "access_type": "offline", "prompt": "consent"}))
    print(f"\n  Opening your browser to approve… if it doesn't open, paste this:\n  {auth_url}\n")
    webbrowser.open(auth_url)
    with socketserver.TCPServer(("localhost", OAUTH_PORT), H) as srv:
        srv.handle_request()  # serve exactly one redirect
    code = (code_box.get("code") or [None])[0]
    if not code:
        print("  ! No auth code received. Try again."); return False
    tok = _curl_json("https://oauth2.googleapis.com/token", data=urllib.parse.urlencode({
        "code": code, "client_id": client["id"], "client_secret": client["secret"],
        "redirect_uri": redirect, "grant_type": "authorization_code"}))
    if "refresh_token" not in tok:
        print(f"  ! Token exchange failed: {tok}"); return False
    os.makedirs(OAUTH_DIR, exist_ok=True)
    json.dump(tok, open(os.path.join(OAUTH_DIR, "token.json"), "w"))
    print("  ✓ Authorized. Token saved. Now run:  scout mine\n")
    return True

def _access_token(client):
    import urllib.parse
    tp = os.path.join(OAUTH_DIR, "token.json")
    if not os.path.exists(tp):
        return None
    rt = json.load(open(tp)).get("refresh_token")
    fresh = _curl_json("https://oauth2.googleapis.com/token", data=urllib.parse.urlencode({
        "client_id": client["id"], "client_secret": client["secret"],
        "refresh_token": rt, "grant_type": "refresh_token"}))
    return fresh.get("access_token")

def cmd_mine(args):
    client = _load_client()
    if not client or args.setup:
        _mine_setup_msg(); return
    if args.auth:
        _oauth_flow(client); return
    tok = _access_token(client)
    if not tok:
        print("\n  Not authorized yet. Run:  scout mine --auth   (or  scout mine --setup  for the steps)\n"); return
    hdr = {"Authorization": f"Bearer {tok}"}
    # resolve the channel
    ch = _curl_json("https://www.googleapis.com/youtube/v3/channels?part=snippet,statistics&mine=true", headers=hdr)
    if ch.get("error") or not ch.get("items"):
        print(f"\n  ! Could not read your channel: {ch.get('error', ch)}\n"); return
    c0 = ch["items"][0]
    name = c0["snippet"]["title"]
    subs = c0["statistics"].get("subscriberCount", "?")
    # analytics: last 28 days
    end = time.strftime("%Y-%m-%d")
    start = time.strftime("%Y-%m-%d", time.localtime(time.time() - args.days * 86400))
    metrics = "views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage,subscribersGained,estimatedRevenue"
    a = _curl_json(f"https://youtubeanalytics.googleapis.com/v2/reports?ids=channel==MINE"
                   f"&startDate={start}&endDate={end}&metrics={metrics}", headers=hdr)
    print(f"\n\033[1mYOUR CHANNEL — private metrics (last {args.days} days)\033[0m  {name} ({subs} subs)\n")
    if a.get("error"):
        print(f"  ! Analytics API said: {a['error'].get('message', a['error'])}")
        print("  (If it mentions the API being disabled, enable 'YouTube Analytics API' in your Cloud project.)\n"); return
    cols = [h["name"] for h in a.get("columnHeaders", [])]
    row = (a.get("rows") or [[]])[0]
    d = dict(zip(cols, row))
    def g(k):
        return d.get(k, "?")
    print(f"  Views: {g('views')}   |   Watch time: {g('estimatedMinutesWatched')} min")
    avd = g('averageViewDuration')
    print(f"  Avg view duration: {avd if avd=='?' else str(int(avd))+'s'}   |   Avg % viewed: {g('averageViewPercentage')}%")
    print(f"  Subscribers gained: {g('subscribersGained')}")
    print(f"  \033[1mEstimated revenue: ${g('estimatedRevenue')}\033[0m  \033[2m(REAL, from your Studio — not a niche guess)\033[0m")
    print(f"\n  This is the data Reggie said no free tool could see. Now it can — because it's YOUR data, with YOUR permission.\n")

def cmd_config(args):
    cfg = os.path.expanduser("~/ytscout/rpm.json")
    data = json.load(open(cfg)) if os.path.exists(cfg) else {}
    if args.rpm is not None:
        key = args.niche or "default"
        data[key] = args.rpm
        json.dump(data, open(cfg, "w"), indent=2)
        print(f"\n  Saved your real RPM: {key} = ${args.rpm}/1000 views.")
        print("  This now overrides the niche guess in outliers/audit/weekly. (Find yours in YouTube Studio > Analytics > Revenue > RPM.)\n")
    else:
        print(f"\n  Your saved RPMs ({cfg}):")
        if data:
            for k, v in data.items():
                print(f"   • {k}: ${v}/1000")
        else:
            print("   (none — set with: scout config --rpm 6.2 [--niche ai])")
        print()

# ---------- CLI ----------

def build_parser():
    p = argparse.ArgumentParser(prog="scout", description="Free local vidIQ/TubeBuddy, grounded in the consensus doctrine.")
    sub = p.add_subparsers(dest="cmd", required=True)

    o = sub.add_parser("outliers", help="find proven video ideas by view-to-subscriber ratio")
    o.add_argument("handle")
    o.add_argument("--vs", default="", help="comma-separated comparable-niche handles to hunt across")
    o.add_argument("--min-views", type=int, default=1000)
    o.add_argument("--scan", type=int, default=30, help="recent videos to scan per channel (default 30)")
    o.add_argument("--niche", default=None, help="niche for RPM/revenue: ai, tech, business, finance, family, homeschool, education, lifestyle, gaming...")
    o.add_argument("--rpm", type=float, default=None, help="your real RPM (overrides niche guess)")
    o.add_argument("--top", type=int, default=20)
    o.add_argument("--ai", action="store_true", help="use gemma to port the top outlier into your niches")
    o.add_argument("--html", action="store_true")
    _add_shared_filters(o, screen=True)
    o.set_defaults(func=cmd_outliers)

    f = sub.add_parser("feed", help="render your title+thumbnail among REAL niche videos (thumbsup.tv-style)")
    f.add_argument("query", nargs="?", default="", help="the niche/search to build the feed from (optional with --input)")
    f.add_argument("--input", default=None, help="competitor tiles JSON instead of a live search (offline)")
    f.add_argument("--grid", choices=FEED_GRIDS, default="yt",
                   help="extra mock to render next to feed.html: tv (YouTube TV home, 5-across) or ig (4:5, 3-across)")
    f.add_argument("--tv", action="store_true", help="shortcut for --grid tv")
    f.add_argument("--my-title", default="", help="your proposed title")
    f.add_argument("--my-thumb", default="", help="path to your proposed thumbnail image")
    f.add_argument("--pos", type=int, default=3, help="where to place your card (0-based)")
    f.add_argument("--n", type=int, default=11, help="real videos to surround it with")
    f.add_argument("--open", action="store_true", help="open the HTML when done")
    f.set_defaults(func=cmd_feed)

    st = sub.add_parser("studio", help="visual GUI: test title+thumbnail against the live feed AND the audience panel")
    st.add_argument("--niche", default=None, help="niche feed to test against (default: your active watchlist niche)")
    st.add_argument("--port", type=int, default=8756, help="local port (default 8756)")
    st.add_argument("--no-open", action="store_true", help="don't auto-open the browser")
    st.set_defaults(func=cmd_studio)

    w = sub.add_parser("weekly", help="scan your watchlist for new outliers (zero AI, schedulable)")
    w.add_argument("--scan", type=int, default=15, help="recent videos per channel (default 15)")
    w.add_argument("--min-views", type=int, default=1000)
    w.add_argument("--niche", default=None, help="override the watchlist niche for RPM")
    w.add_argument("--rpm", type=float, default=None, help="your real RPM (overrides niche guess)")
    w.add_argument("--list", default=None, help="which watchlist to scan (default: active)")
    w.add_argument("--top", type=int, default=25)
    _add_shared_filters(w)
    w.set_defaults(func=cmd_weekly)

    ti = sub.add_parser("tiers", help="3-tier small-channel study: per-tier median views and top outliers")
    ti.add_argument("handles", nargs="*", help="channel handles (default: the active watchlist)")
    ti.add_argument("--list", default=None, help="watchlist to study (added to any handles given)")
    ti.add_argument("--input", default=None, help="channels JSON (channel_dump shape) instead of fetching, offline")
    ti.add_argument("--tiers", default=DEFAULT_TIERS, help=f"subscriber bands, lower bound inclusive (default {DEFAULT_TIERS})")
    ti.add_argument("--top", type=int, default=5, help="outliers to show per tier (default 5)")
    ti.add_argument("--scan", type=int, default=30, help="recent videos per channel when fetching (default 30)")
    ti.add_argument("--min-views", type=int, default=0)
    ti.add_argument("--json", action="store_true", help="print the study as JSON")
    _add_shared_filters(ti, screen=True)
    ti.set_defaults(func=cmd_tiers)

    sa = sub.add_parser("social-audit", help="audit an Instagram/Facebook export: formats, topics, outliers, cadence (offline)")
    sa.add_argument("export", help="Meta 'Download your information' JSON, or a list of post dicts")
    sa.add_argument("--tz", type=float, default=0.0, help="hours offset from UTC for the day/hour table (e.g. -5)")
    sa.add_argument("--topics", type=int, default=8, help="max keyword topics (default 8)")
    sa.add_argument("--label", default=None, help="account name for the report (default: file name)")
    sa.add_argument("--out", default=None, help="output folder (default reports/)")
    sa.add_argument("--json", action="store_true", help="print the audit as JSON")
    sa.set_defaults(func=cmd_social_audit)

    pe = sub.add_parser("peers", help="discover same-size peer channels with outsized returns (saves list peers-<list>)")
    pe.add_argument("--list", default="ai", help="niche list name; reads peers-queries-<list>.txt, saves peers-<list> (default ai)")
    pe.add_argument("--queries", default=None, help="queries file, one per line (default ~/ytscout/peers-queries-<list>.txt)")
    pe.add_argument("--min-subs", type=int, default=1000)
    pe.add_argument("--max-subs", type=int, default=50000)
    pe.add_argument("--n", type=int, default=10, help="peers to keep/show")
    pe.add_argument("--cap", type=int, default=120, help="max candidate channels to scan")
    pe.add_argument("--per-query", type=int, default=12, help="search results per query")
    pe.add_argument("--scan", type=int, default=15, help="recent videos per candidate channel (default 15, shares the weekly cache)")
    pe.add_argument("--workers", type=int, default=4, help="parallel channel fetches")
    pe.add_argument("--sleep", type=float, default=1.5, help="seconds between network calls")
    pe.add_argument("--no-save", dest="save", action="store_false", help="don't write the peers list to watchlist.json")
    pe.set_defaults(func=cmd_peers)

    wa = sub.add_parser("watch", help="manage watchlists of comparable channels (one per channel/niche)")
    wa.add_argument("--list", default=None, help="which named list to edit (e.g. ai, homeschool)")
    wa.add_argument("--add", default="", help="comma-separated handles to add")
    wa.add_argument("--remove", default="", help="a handle to remove")
    wa.add_argument("--niche", default=None, help="set the list's niche (for RPM)")
    wa.add_argument("--activate", action="store_true", help="make this the active list weekly scans")
    wa.set_defaults(func=cmd_watch)

    t = sub.add_parser("title", help="score a proposed title against the data-study rules")
    t.add_argument("text")
    t.add_argument("--ai", action="store_true", help="gemma generates 5 stronger variants")
    t.set_defaults(func=cmd_title)

    n = sub.add_parser("niche", help="see what ranks for a search term and how saturated it is")
    n.add_argument("query")
    n.add_argument("--n", type=int, default=25)
    n.add_argument("--html", action="store_true")
    n.add_argument("--shorts", choices=SHORTS_MODES, default="exclude",
                   help="Shorts (<=60s): exclude (default, long-form only), include, or only")
    n.set_defaults(func=cmd_niche)

    kw = sub.add_parser("keywords", help="free keyword demand + competition, no API key")
    kw.add_argument("seed")
    kw.add_argument("--expand", choices=["none", "quick", "full"], default="quick",
                    help="autocomplete expansion breadth (none=1 request, quick=9, full=35)")
    kw.add_argument("--top", type=int, default=20, help="keywords to show (default 20)")
    kw.add_argument("--check", type=int, default=5,
                    help="how many top keywords get a competition read, each costs about n seconds cold (default 5)")
    kw.add_argument("--n", type=int, default=12, help="search results per competition read (default 12)")
    kw.add_argument("--html", action="store_true")
    kw.set_defaults(func=cmd_keywords)

    da = sub.add_parser("dash", help="assemble reports/dashboard.html from what is already on disk, offline")
    da.add_argument("--refresh", action="store_true", help="run a live weekly scan first, then assemble (needs network)")
    da.add_argument("--list", default=None, help="watchlist to refresh (default: active)")
    da.add_argument("--open", action="store_true", help="open the dashboard when done")
    da.set_defaults(func=cmd_dash)

    a = sub.add_parser("audit", help="audit a channel's public packaging/length/consistency + revenue")
    a.add_argument("handle")
    a.add_argument("--niche", default=None, help="niche for RPM/revenue estimate")
    a.add_argument("--rpm", type=float, default=None, help="your real RPM (overrides niche guess)")
    a.add_argument("--html", action="store_true")
    a.set_defaults(func=cmd_audit)

    cf = sub.add_parser("config", help="save your real RPM (from YouTube Studio) so estimates use YOUR number")
    cf.add_argument("--rpm", type=float, default=None, help="your $ per 1000 views")
    cf.add_argument("--niche", default=None, help="which niche/channel this RPM is for (else 'default')")
    cf.set_defaults(func=cmd_config)

    m = sub.add_parser("mine", help="YOUR channel's private CTR/retention/real revenue (one-time Google auth)")
    m.add_argument("--setup", action="store_true", help="show the one-time setup steps")
    m.add_argument("--auth", action="store_true", help="authorize (opens browser once)")
    m.add_argument("--days", type=int, default=28, help="lookback window (default 28)")
    m.set_defaults(func=cmd_mine)

    return p

def main(argv=None):
    args = build_parser().parse_args(argv)
    args.func(args)

if __name__ == "__main__":
    main()
