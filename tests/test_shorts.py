from conftest import run
import scout


def test_tag_shorts_marks_60s_and_under():
    vids = [{"dur": 60}, {"dur": 61}, {"dur": 0}, {"dur": 15}]
    scout.tag_shorts(vids)
    assert [v["is_short"] for v in vids] == [True, False, True, True]


def test_apply_shorts_modes(by_handle):
    vids = by_handle["tinyai"]["videos"]
    assert all(not v["is_short"] for v in scout.apply_shorts(list(vids), "exclude"))
    only = scout.apply_shorts(list(vids), "only")
    assert [v["title"] for v in only] == ["Short: one prompt trick"]
    assert len(scout.apply_shorts(list(vids), "include")) == len(vids)


def test_default_mode_matches_old_long_form_filter(by_handle):
    vids = by_handle["tinyai"]["videos"]
    old = [v["id"] for v in vids if v["dur"] > scout.SHORT_MAX_SEC]
    assert [v["id"] for v in scout.apply_shorts(list(vids))] == old


def test_outliers_default_excludes_shorts(offline_channels, capsys):
    run(["outliers", "tinyai", "--min-views", "0"])
    out = capsys.readouterr().out
    assert "Short: one prompt trick" not in out
    assert "Short  " not in out.splitlines()[3]


def test_outliers_include_adds_short_column(offline_channels, capsys):
    run(["outliers", "tinyai", "--shorts", "include", "--min-views", "0"])
    out = capsys.readouterr().out
    assert "Short: one prompt trick" in out
    header = next(l for l in out.splitlines() if "V/Sub" in l and "Title" in l)
    assert header.startswith("Short")


def test_outliers_only_shorts(offline_channels, capsys):
    run(["outliers", "tinyai", "--shorts", "only", "--min-views", "0"])
    out = capsys.readouterr().out
    assert "Short: one prompt trick" in out
    assert "I replaced my bookkeeper" not in out


def test_niche_shorts_flag(monkeypatch, capsys):
    res = [{"id": "a", "title": "Long one", "views": 1000, "dur": 600, "channel": "A"},
           {"id": "b", "title": "Tiny short", "views": 9000, "dur": 30, "channel": "B"}]
    monkeypatch.setattr(scout, "search_dump", lambda q, n=20: {"results": [dict(r) for r in res]})
    run(["niche", "x"])
    assert "Tiny short" not in capsys.readouterr().out
    run(["niche", "x", "--shorts", "only"])
    out = capsys.readouterr().out
    assert "Tiny short" in out and "Long one" not in out
