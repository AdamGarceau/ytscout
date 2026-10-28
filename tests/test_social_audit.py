import json

from conftest import fixture_path, run
import scout


def _audit(name, **kw):
    posts, source = scout.load_social_export(fixture_path(name))
    return scout.social_audit(posts, source=source, **kw)


def test_simple_format_mix():
    res = _audit("social_simple.json")
    assert res["source"] == "simple" and res["posts"] == 20
    fmt = {f["format"]: f for f in res["formats"]}
    assert [fmt[k]["posts"] for k in scout.SA_FORMATS] == [10, 4, 5, 1]
    assert fmt["Reel"]["share_posts"] == 0.5
    total = sum(f["views"] for f in res["formats"])
    assert fmt["Reel"]["views"] == 28650 and fmt["Reel"]["share_views"] == round(28650 / total, 4)
    assert fmt["Text"]["median_views"] is None
    assert abs(sum(f["share_posts"] for f in res["formats"]) - 1) < 1e-9


def test_topics_cluster_by_keyword():
    topics = {t["keyword"]: t for t in _audit("social_simple.json")["topics"]}
    assert set(topics) == {"garden", "meal", "sourdough", "other"}
    assert topics["garden"]["posts"] == 7
    assert topics["sourdough"]["posts"] == 4
    assert topics["sourdough"]["median_views"] == 950
    assert topics["other"]["posts"] == 5
    assert sum(t["posts"] for t in topics.values()) == 20


def test_outlier_tiers():
    o = _audit("social_simple.json")["outliers"]
    assert o["metric"] == "views" and o["median"] == 950
    assert o["tiers"] == {"10x": 1, "5x": 1, "3x": 1}
    assert [(p["id"], p["tier"]) for p in o["posts"]] == [("syn005", "10x"), ("syn010", "5x"), ("syn012", "3x")]
    assert o["posts"][0]["mult"] == round(12000 / 950, 2)


def test_outliers_fall_back_to_likes():
    posts = [{"id": str(i), "caption": "", "media_type": "IMAGE", "like_count": l}
             for i, l in enumerate([10, 10, 10, 10, 50, 100])]
    res = scout.social_audit([scout._sa_simple(p) for p in posts])
    assert res["outliers"]["metric"] == "likes"
    assert [p["tier"] for p in res["outliers"]["posts"]] == ["10x", "5x"]


def test_cadence_and_heat():
    c = _audit("social_simple.json")["cadence"]
    assert c["timed_posts"] == 20 and c["first"] == "2026-06-01"
    assert sum(map(sum, c["heat"])) == 20
    assert c["heat"][0][14] == 1  # Mon 14:00 UTC, the first post
    assert c["busiest_hour"] == 14
    assert [m["posts"] for m in c["per_month"]] == [10, 10]
    shifted = _audit("social_simple.json", tz_offset=-5)["cadence"]
    assert shifted["heat"][0][9] == 1


def test_meta_instagram_export():
    res = _audit("social_meta_ig.json")
    assert res["source"] == "meta" and res["posts"] == 4
    assert [f["posts"] for f in res["formats"]] == [1, 1, 2, 0]
    assert res["outliers"]["metric"] is None and res["outliers"]["posts"] == []
    posts, _ = scout.load_social_export(fixture_path("social_meta_ig.json"))
    assert "—" in posts[0]["caption"]  # Meta latin-1 mojibake undone
    assert {t["keyword"] for t in res["topics"]} >= {"garden", "sourdough"}


def test_meta_reels_and_facebook_exports():
    assert [f["posts"] for f in _audit("social_meta_reels.json")["formats"]] == [2, 0, 0, 0]
    fb = _audit("social_meta_fb.json")
    assert [f["posts"] for f in fb["formats"]] == [1, 1, 1, 1]
    assert fb["cadence"]["timed_posts"] == 4


def test_cli_writes_json_and_html(sandbox, capsys):
    run(["social-audit", fixture_path("social_simple.json"), "--label", "synthetic"])
    assert "SOCIAL AUDIT: synthetic" in capsys.readouterr().out
    data = json.load(open(sandbox / "social-audit.json"))
    assert data["label"] == "synthetic" and data["outliers"]["tiers"]["10x"] == 1
    page = (sandbox / "social-audit.html").read_text()
    assert "<script" not in page and "Format mix" in page and "12.6x" in page
    assert "https://example.com/p/syn005" in page


def test_cli_bad_input(sandbox, capsys, tmp_path):
    bad = tmp_path / "x.json"
    bad.write_text("{not json")
    run(["social-audit", str(bad)])
    assert "could not read" in capsys.readouterr().out
