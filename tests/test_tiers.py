import json

import pytest

from conftest import NOW, fixture_path, run
import scout

TIERS = scout.parse_tiers(scout.DEFAULT_TIERS)


def test_parse_tiers():
    assert TIERS == [(1000, 10000), (10000, 50000), (50000, 250000)]
    assert scout.parse_tiers("500-2.5k, 2.5K-1M") == [(500, 2500), (2500, 1000000)]
    with pytest.raises(ValueError):
        scout.parse_tiers("10K-1K")


def _study(channels, **kw):
    kw.setdefault("now", NOW)
    return scout.tiers_study(channels, TIERS, **kw)


def test_bucketing(channels):
    res = _study(channels)
    names = [t["channel_names"] for t in res["tiers"]]
    assert names[0] == ["Tiny AI Lab", "Small Build Co"]
    assert names[1] == ["Edge Ten K", "Mid Code", "Faceless Facts"]  # 10K is lower-bound inclusive
    assert names[2] == ["Big Dev", "Dead Subs Inc"]
    assert {u["channel"] for u in res["unbucketed"]} == {"Mega Channel", "Hidden Subs"}
    assert [t["tier"] for t in res["tiers"]] == ["1K-10K", "10K-50K", "50K-250K"]


def test_tier_medians_and_multiples(channels):
    t1 = _study(channels)["tiers"][0]
    # Tiny AI Lab long-forms in window: 7 regular + 30000 outlier; Short and 2024 video excluded
    assert t1["videos"] == 8 + 7
    tiny_med = 3100.0
    top = t1["top"][0]
    assert top["title"] == "I replaced my bookkeeper with Claude"
    assert top["channel_median"] == tiny_med
    assert top["mult"] == round(30000 / tiny_med, 2)
    assert t1["top"][1]["title"] == "Built an invoice app in one day"
    views = sorted([3000, 2500, 4000, 3500, 2800, 3200, 2900, 30000, 5000, 6000, 7000, 8000, 5500, 6500, 45000])
    assert t1["median_views"] == views[7]


def test_top_n_limit_and_order(channels):
    for t in _study(channels, top=3)["tiers"]:
        assert len(t["top"]) <= 3
        mults = [r["mult"] for r in t["top"]]
        assert mults == sorted(mults, reverse=True)


def test_shorts_and_window_options(channels):
    only = _study(channels, shorts="only")["tiers"][0]
    assert [r["title"] for r in only["top"]] == ["Short: one prompt trick"]
    assert only["top"][0]["is_short"] is True
    allt = _study(channels, since_months=0)["tiers"][0]
    assert "Old evergreen hit" in [r["title"] for r in allt["top"]]


def test_screen_and_drop(channels):
    t2 = _study(channels, screen=True)["tiers"][1]
    assert t2["top"][0]["title"] == "10 AI facts that sound fake"
    assert "likes hidden" in t2["top"][0]["flags"]
    dropped = _study(channels, drop_flagged=True)["tiers"][1]
    assert dropped["top"][0]["title"] == "Cursor vs Claude Code for owners"
    assert dropped["dropped_flagged"] == 3


def test_study_does_not_mutate_input(channels):
    before = json.dumps(channels, sort_keys=True)
    _study(channels, screen=True)
    assert json.dumps(channels, sort_keys=True) == before


def test_cmd_tiers_json(capsys):
    run(["tiers", "--input", fixture_path("channels.json"), "--json", "--top", "2"])
    res = json.loads(capsys.readouterr().out)
    assert [len(t["top"]) for t in res["tiers"]] == [2, 2, 2]
    assert res["params"]["since_months"] == 6


def test_cmd_tiers_table(capsys):
    run(["tiers", "--input", fixture_path("channels.json"), "--tiers", "1K-50K,50K-250K", "--screen"])
    out = capsys.readouterr().out
    assert "TIER STUDY" in out and "1K-50K" in out and "MedChanMed" in out
    assert "Flags" in out and "Outside every tier" in out


def test_cmd_tiers_fetches_handles(offline_channels, capsys):
    run(["tiers", "tinyai", "bigdev", "--json"])
    res = json.loads(capsys.readouterr().out)
    assert res["tiers"][0]["channel_names"] == ["Tiny AI Lab"]
    assert res["tiers"][2]["channel_names"] == ["Big Dev"]


def test_cmd_tiers_bad_spec(capsys):
    run(["tiers", "--input", fixture_path("channels.json"), "--tiers", "5K-1K"])
    assert "--tiers" in capsys.readouterr().out
