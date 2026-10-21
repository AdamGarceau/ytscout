from conftest import run
import scout


def _vid(c, title):
    return next(v for v in c["videos"] if v["title"] == title)


def test_faceless_outlier_gets_every_reason(by_handle):
    c = by_handle["facelessfacts"]
    v = _vid(c, "10 AI facts that sound fake")
    r = scout.screen_video(v, c["videos"], c["subs"])
    assert "subs/1k 4.0" in r
    assert "likes hidden" in r
    assert "comments off" in r
    assert "batch x3" in r
    assert any(x.startswith("faceless:") for x in r)


def test_clean_outlier_has_no_reasons(by_handle):
    c = by_handle["midcode"]
    v = _vid(c, "Cursor vs Claude Code for owners")
    assert scout.screen_video(v, c["videos"], c["subs"]) == []


def test_dead_subs_channel_flagged(by_handle):
    c = by_handle["deadsubs"]
    assert "subs>>views" in scout.screen_video(c["videos"][0], c["videos"], c["subs"])


def test_missing_fields_are_unknown_not_flagged():
    v = {"title": "x", "views": 1000, "date": "20260101"}  # old cache record, no likes/comments keys
    assert scout.screen_video(v, [v], 500) == []


def test_faceless_patterns():
    for t in ["Reddit stories that broke me", "AI voiceover tutorial", "text to speech compilation", "AITA for this"]:
        assert scout.FACELESS_RE.search(t), t
    for t in ["I built a CRM with Claude", "My face reveal"]:
        assert not scout.FACELESS_RE.search(t), t


def test_outliers_screen_column(offline_channels, capsys):
    run(["outliers", "facelessfacts", "--vs", "midcode", "--screen", "--min-views", "0"])
    out = capsys.readouterr().out
    header = next(l for l in out.splitlines() if "V/Sub" in l and "Title" in l)
    assert header.rstrip().endswith("Flags")
    line = next(l for l in out.splitlines() if "10 AI facts" in l)
    assert "likes hidden" in line and "batch x3" in line
    assert any("Cursor vs Claude" in l and l.rstrip().endswith("ok") for l in out.splitlines())


def test_outliers_drop_flagged(offline_channels, capsys):
    run(["outliers", "facelessfacts", "--vs", "midcode", "--drop-flagged", "--min-views", "0"])
    out = capsys.readouterr().out
    assert "10 AI facts" not in out
    assert "AI facts part 2" not in out  # batch upload
    assert "Cursor vs Claude" in out
    assert "Dropped 3 flagged rows" in out


def test_outliers_without_screen_has_no_flags(offline_channels, capsys):
    run(["outliers", "facelessfacts", "--min-views", "0"])
    out = capsys.readouterr().out
    assert "Flags" not in out and "10 AI facts" in out


def test_outliers_html_flags(offline_channels, capsys, sandbox):
    run(["outliers", "facelessfacts", "--screen", "--html", "--min-views", "0"])
    doc = (sandbox / "outliers.html").read_text()
    assert "<th>Flags</th>" in doc and "likes hidden" in doc
