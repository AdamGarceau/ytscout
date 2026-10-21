from conftest import NOW, run
import scout


def test_apply_since_window():
    vids = [{"date": "20260901"}, {"date": "20260301"}, {"date": None}, {}]
    kept = scout.apply_since(vids, 6, NOW)
    assert {"date": "20260301"} not in kept
    assert len(kept) == 3  # undated records are kept


def test_apply_since_zero_disables():
    vids = [{"date": "20100101"}]
    assert scout.apply_since(vids, 0, NOW) == vids
    assert scout.apply_since(vids, None, NOW) == vids


def test_apply_since_fractional_months():
    vids = [{"date": "20260901"}, {"date": "20260801"}]
    assert scout.apply_since(vids, 1, NOW) == [{"date": "20260901"}]


def test_outliers_default_six_months(offline_channels, capsys):
    run(["outliers", "tinyai", "--min-views", "0"])
    out = capsys.readouterr().out
    assert "Old evergreen hit" not in out
    assert "last 6 months" in out


def test_outliers_since_zero_brings_back_old(offline_channels, capsys):
    run(["outliers", "tinyai", "--min-views", "0", "--since-months", "0"])
    assert "Old evergreen hit" in capsys.readouterr().out


def test_weekly_uses_window(offline_channels, monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(scout, "load_watchlist",
                        lambda: {"lists": {"t": {"handles": ["tinyai"], "niche": "ai"}}, "active": "t"})
    monkeypatch.setattr(scout, "real_rpm", lambda niche, override=None: 5.0)
    run(["weekly", "--min-views", "0", "--since-months", "0"])
    assert "Old evergreen hit" in capsys.readouterr().out
    run(["weekly", "--min-views", "0"])
    assert "Old evergreen hit" not in capsys.readouterr().out


def test_dash_refresh_namespace_still_works(offline_channels, monkeypatch, capsys):
    # cmd_dash builds its own Namespace for cmd_weekly; it must carry the new fields
    monkeypatch.setattr(scout, "load_watchlist",
                        lambda: {"lists": {"t": {"handles": ["tinyai"], "niche": "ai"}}, "active": "t"})
    run(["dash", "--refresh"])
    assert "SCOUT DASH" in capsys.readouterr().out
