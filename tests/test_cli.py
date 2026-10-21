import scout


def test_old_invocations_still_parse():
    p = scout.build_parser()
    cases = [
        ["outliers", "someone", "--vs", "a,b", "--top", "5", "--html"],
        ["feed", "ai tools", "--my-title", "x", "--pos", "2", "--open"],
        ["weekly", "--list", "ai"],
        ["niche", "claude code", "--n", "10"],
        ["keywords", "seed", "--expand", "none"],
        ["dash"], ["audit", "someone"], ["title", "A title"],
    ]
    for argv in cases:
        args = p.parse_args(argv)
        assert callable(args.func)


def test_new_defaults():
    p = scout.build_parser()
    o = p.parse_args(["outliers", "x"])
    assert (o.shorts, o.since_months, o.screen, o.drop_flagged) == ("exclude", 6, False, False)
    w = p.parse_args(["weekly"])
    assert (w.shorts, w.since_months) == ("exclude", 6)
    f = p.parse_args(["feed", "q"])
    assert f.grid == "yt" and not f.tv and f.input is None
    t = p.parse_args(["tiers"])
    assert t.tiers == scout.DEFAULT_TIERS and t.top == 5
