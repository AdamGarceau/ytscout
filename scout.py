#!/usr/bin/env python3
"""
ytscout — a free, local, keyless replacement for the parts of vidIQ and TubeBuddy
that actually move the needle, grounded in Adam's consensus doctrine.

Data: yt-dlp (no API key). Brain: local gemma4:12b via ollama (optional). Deps: stdlib only.

Commands:
  scout outliers <handle> [--vs h1,h2,...] [--min-views N] [--days N] [--top N] [--html]
  scout title "<proposed title>" [--ai]
  scout niche "<search query>" [--n N] [--html]
  scout keywords "<seed>" [--expand none|quick|full] [--top N] [--check N] [--n N] [--html]
  scout dash [--refresh] [--open]
  scout audit <handle> [--html]

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

def _ydl(url, limit):
    # Non-flat extraction is the only reliable free way to get view counts.
    # Bounded to `limit` recent items so it stays fast; results are cached hard.
    import yt_dlp
    opts = {"quiet": True, "no_warnings": True, "skip_download": True,
            "extract_flat": False, "playlist_items": f"1-{limit}"}
    with yt_dlp.YoutubeDL(opts) as ydl:
        return ydl.extract_info(url, download=False)

def channel_dump(handle, limit=30):
    """Return {name, subs, videos:[{id,title,views,dur,date}]}. Cached 6h."""
    handle = handle.lstrip("@")
    key = f"chan_{handle}_{limit}"
    cached = _cache_get(key)
    if cached:
        return cached
    sys.stderr.write(f"  … fetching @{handle} ({limit} recent, ~{limit}s first time; cached after)\n"); sys.stderr.flush()
    try:
        info = _ydl(f"https://www.youtube.com/@{handle}/videos", limit)
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
        })
    out = {
        "name": info.get("channel") or info.get("uploader") or handle,
        "subs": info.get("channel_follower_count"),
        "videos": vids,
    }
    _cache_put(key, out)
    return out

def search_dump(query, n=20):
    key = f"search_{query}_{n}"
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

# ---------- Command: outliers (the crown jewel) ----------

def cmd_outliers(args):
    handles = [args.handle] + (args.vs.split(",") if args.vs else [])
    handles = [h.strip().lstrip("@") for h in handles if h.strip()]
    print(f"\n\033[1mOUTLIER FINDER\033[0m  (view-to-subscriber ratio = the #1 idea-validation signal, 6 corpora agree)\n")
    all_rows = []
    html_rows = []
    for h in handles:
        ch = channel_dump(h, limit=args.scan)
        if ch.get("error"):
            print(f"  ! {h}: {ch['error']}")
            continue
        subs = ch.get("subs") or 0
        vids = [v for v in ch["videos"] if v["dur"] > SHORT_MAX_SEC and v["views"] >= args.min_views]
        if not vids:
            print(f"  ! {h}: no long-form videos above {args.min_views} views")
            continue
        med = statistics.median([v["views"] for v in vids]) or 1
        for v in vids:
            v["ch"] = ch["name"]
            v["subs"] = subs
            # two multipliers the doctrine names:
            v["vsr"] = round(v["views"] / subs, 2) if subs else None   # view-to-subscriber (AmplifyViews)
            v["osc"] = round(v["views"] / med, 2)                       # outlier score vs channel median (vidIQ/One10)
        all_rows.extend(vids)
    if not all_rows:
        print("  No data. Check the handles (use the exact @handle).")
        return
    # rank: prefer view-to-sub where available, else outlier score
    rpm = real_rpm(args.niche, getattr(args, "rpm", None))
    ranked = sorted(all_rows, key=lambda v: (v["vsr"] or 0, v["osc"]), reverse=True)[:args.top]
    rows = []
    for v in ranked:
        vsr = f"{v['vsr']}x" if v["vsr"] is not None else "—"
        v["rev"] = est_rev(v["views"], rpm, v["dur"])
        rows.append([vsr, f"{v['osc']}x", human(v["views"]), money(v["rev"]),
                     human(v["subs"]), v["ch"][:15], v["title"][:52]])
        html_rows.append(v)
    print(table(rows, ["V/Sub", "vsMed", "Views", "Est$", "Subs", "Channel", "Title"]))
    print(f"\n  V/Sub = views ÷ subscribers (5x+ strong, 20x gold — AmplifyViews).  vsMed = views ÷ channel median (3x+ = vidIQ outlier).")
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
        write_outlier_html(handles, html_rows)

def write_outlier_html(handles, vids):
    path = os.path.join(REPORT_DIR, "outliers.html")
    rows = "".join(
        f"<tr><td>{v['vsr'] or '—'}x</td><td>{v['osc']}x</td><td>{human(v['views'])}</td>"
        f"<td>{human(v['subs'])}</td><td>{html.escape(v['ch'])}</td>"
        f"<td><a href='https://youtu.be/{v['id']}'>{html.escape(v['title'])}</a></td></tr>"
        for v in vids)
    doc = f"""<!doctype html><meta charset=utf-8><title>ytscout outliers</title>
<style>body{{font:15px/1.5 -apple-system,system-ui,sans-serif;max-width:1000px;margin:2rem auto;padding:0 1rem}}
h1{{font-size:1.4rem}}table{{border-collapse:collapse;width:100%}}td,th{{padding:.4rem .6rem;border-bottom:1px solid #ddd;text-align:left}}
th{{font-size:.8rem;text-transform:uppercase;color:#666}}a{{color:#0645ad;text-decoration:none}}</style>
<h1>Outlier finder</h1><p>Channels: {html.escape(', '.join(handles))}. V/Sub = views ÷ subscribers (5x+ strong, 20x gold). vsMed = views ÷ channel median (3x+ = outlier).</p>
<table><tr><th>V/Sub</th><th>vs Median</th><th>Views</th><th>Subs</th><th>Channel</th><th>Title</th></tr>{rows}</table>"""
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
    res = [r for r in d["results"] if r["dur"] > SHORT_MAX_SEC]
    if not res:
        print("  No long-form results."); return
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

def cmd_feed(args):
    d = search_dump(args.query, args.n)
    if d.get("error"):
        print("  ! " + d["error"]); return
    vids = [v for v in d["results"] if v["dur"] > SHORT_MAX_SEC][:args.n]
    if not vids:
        print("  No results."); return

    # Adam's card
    my_thumb = _b64_img(args.my_thumb) if args.my_thumb else None
    my = {
        "title": args.my_title or "[your proposed title here]",
        "channel": "Your Channel",
        "views_str": "NEW",
        "thumb": my_thumb,  # data URI or None -> placeholder
        "mine": True,
    }
    cards = []
    for v in vids:
        cards.append({
            "title": v["title"],
            "channel": v["channel"],
            "views_str": _yt_views(v["views"]),
            "thumb": f"https://i.ytimg.com/vi/{v['id']}/hqdefault.jpg",
            "mine": False,
        })
    pos = max(0, min(len(cards), args.pos))
    cards.insert(pos, my)

    def card_html(c):
        cls = "card mine" if c.get("mine") else "card"
        if c["thumb"]:
            thumb = f"<img class=thumb src='{c['thumb']}' alt=''>"
        else:
            thumb = f"<div class='thumb ph'>{html.escape(c['title'][:40])}</div>"
        badge = "<span class=badge>YOU</span>" if c.get("mine") else ""
        return (f"<div class='{cls}'>{thumb}{badge}"
                f"<div class=meta><div class=title>{html.escape(c['title'])}</div>"
                f"<div class=sub>{html.escape(c['channel'])} · {c['views_str']}</div></div></div>")

    grid = "".join(card_html(c) for c in cards)
    doc = f"""<!doctype html><meta charset=utf-8><title>ytscout feed — {html.escape(args.query)}</title>
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
<header>Test feed · niche: <b>{html.escape(args.query)}</b> · your card is outlined in blue. Does your packaging stop the scroll?</header>
<div class=grid>{grid}</div>"""
    path = os.path.join(REPORT_DIR, "feed.html")
    open(path, "w").write(doc)
    print(f"\n\033[1mTEST FEED\033[0m built with {len(vids)} real '{args.query}' videos + your card at position {pos+1}.")
    print(f"  → {path}")
    print(f"  Open it and ask: does YOUR thumbnail/title pull the eye, or blend in? (thumbsup.tv-style preview, doctrine's pre-upload gate)\n")
    if args.open:
        os.system(f"open '{path}' 2>/dev/null")

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
    <textarea id=thumbdesc placeholder="e.g. split screen: 'vidIQ $40/mo' with a red X vs a terminal at '$0', my face closed-mouth"></textarea>

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
const seed=["I Replaced a $40/Month App in One Afternoon",""];

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
        vids = [v for v in ch["videos"] if v["dur"] > SHORT_MAX_SEC and v["views"] >= args.min_views]
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
        cmd_weekly(argparse.Namespace(scan=15, min_views=1000, niche=None, rpm=None, list=args.list, top=25))

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

def main():
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
    o.set_defaults(func=cmd_outliers)

    f = sub.add_parser("feed", help="render your title+thumbnail among REAL niche videos (thumbsup.tv-style)")
    f.add_argument("query", help="the niche/search to build the feed from")
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
    w.set_defaults(func=cmd_weekly)

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

    args = p.parse_args()
    args.func(args)

if __name__ == "__main__":
    main()
