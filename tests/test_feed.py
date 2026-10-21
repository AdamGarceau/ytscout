import re

from conftest import fixture_path, run
import scout


def _cards():
    return scout.load_feed_json(fixture_path("feed_tiles.json"))


def test_load_feed_json():
    cards, cand, label, profile = _cards()
    assert label == "ai for small business"
    assert profile["handle"] == "test.account"
    assert len(cards) == 7
    assert cards[0]["thumb"].startswith("data:image/png;base64,")      # local file embedded
    assert cards[1]["thumb"].startswith("https://i.ytimg.com/")       # URL passed through
    assert cards[2]["thumb"] is None                                  # javascript: rejected
    assert cards[5]["thumb"] is None                                  # missing file -> placeholder
    assert cards[0]["dur"] == "12:34" and cards[3]["dur"] == "1:02:05" and cards[1]["dur"] == "18:02"
    assert cards[0]["views_str"] == "182.0K views" and cards[3]["views_str"] == "1.2M views"
    assert cand["mine"] and cand["carousel"] and cand["thumb"].startswith("data:image/png")


def test_load_feed_bare_list(tmp_path):
    p = tmp_path / "t.json"
    p.write_text('[{"title": "a", "channel": "b", "views": 5}]')
    cards, cand, label, profile = scout.load_feed_json(str(p))
    assert cards[0]["views_str"] == "5 views" and cand is None and label is None


def _no_external(doc, allowed=("https://i.ytimg.com/vi/vid0001/hqdefault.jpg",)):
    urls = set(re.findall(r"https?://[^'\")\s<>]+", doc))
    assert urls <= set(allowed), urls
    assert "<link" not in doc and "<script" not in doc and "@import" not in doc


def test_tv_html():
    cards, cand, label, _ = _cards()
    cards.insert(3, cand)
    doc = scout._feed_tv_html(cards, label)
    assert "repeat(5,minmax(0,1fr))" in doc and "aspect-ratio:16/9" in doc and "--bg:#0f0f0f" in doc
    assert doc.count("class='tile") == 8
    assert doc.count("tile mine") == 1 and "class='tile focus'" in doc
    assert "&lt;script&gt;" in doc and "javascript:" not in doc
    assert "<span class=dur>12:34</span>" in doc
    _no_external(doc)


def test_ig_html():
    cards, cand, label, profile = _cards()
    cards.insert(0, cand)
    doc = scout._feed_ig_html(cards, label, profile)
    assert "repeat(3,minmax(0,1fr))" in doc and "aspect-ratio:4/5" in doc
    assert doc.count("class='cell") == 8 and doc.count("cell mine") == 1
    assert doc.count("<span class=multi>") == 2
    assert "test.account" in doc and "<b>42</b> posts" in doc
    assert "&lt;script&gt;" in doc and "javascript:" not in doc
    _no_external(doc)


def test_cmd_feed_tv_writes_both(sandbox, capsys):
    run(["feed", "--input", fixture_path("feed_tiles.json"), "--tv", "--my-title", "My <b>test</b> title"])
    out = capsys.readouterr().out
    assert "feed.html" in out and "feed-tv.html" in out
    yt = (sandbox / "feed.html").read_text()
    tv = (sandbox / "feed-tv.html").read_text()
    assert "My &lt;b&gt;test&lt;/b&gt; title" in tv and "My &lt;b&gt;test&lt;/b&gt; title" in yt
    tiles = re.findall(r"<div class='(tile[^']*)'", tv)
    assert tiles[3] == "tile mine"  # default --pos 3
    assert "javascript:" not in yt


def test_cmd_feed_ig_grid(sandbox):
    run(["feed", "--input", fixture_path("feed_tiles.json"), "--grid", "ig", "--pos", "0",
         "--my-thumb", fixture_path("thumb.png")])
    doc = (sandbox / "feed-ig.html").read_text()
    first = re.search(r"<div class='(cell[^']*)'[^>]*><img src='([^']+)'", doc)
    assert first.group(1) == "cell mine" and first.group(2).startswith("data:image/png")
    assert not (sandbox / "feed-tv.html").exists()


def test_cmd_feed_default_unchanged(monkeypatch, sandbox, capsys):
    res = [{"id": f"id{i}", "title": f"Real {i}", "views": 1000 * i, "dur": 600, "channel": "C"} for i in range(1, 5)]
    res.append({"id": "s", "title": "A short", "views": 10, "dur": 20, "channel": "S"})
    monkeypatch.setattr(scout, "search_dump", lambda q, n=20: {"results": res})
    run(["feed", "ai tools", "--my-title", "Mine"])
    doc = (sandbox / "feed.html").read_text()
    assert "A short" not in doc and doc.count("class='card") == 5
    assert "https://i.ytimg.com/vi/id1/hqdefault.jpg" in doc
    assert not (sandbox / "feed-tv.html").exists() and not (sandbox / "feed-ig.html").exists()


def test_cmd_feed_needs_query_or_input(capsys):
    run(["feed"])
    assert "--input" in capsys.readouterr().out
