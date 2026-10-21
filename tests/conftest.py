import copy, json, os, sys, time

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import scout  # noqa: E402

FIXTURES = os.path.join(ROOT, "tests", "fixtures")
NOW = time.mktime(time.strptime("2026-09-25 12:00", "%Y-%m-%d %H:%M"))


def fixture_path(name):
    return os.path.join(FIXTURES, name)


@pytest.fixture
def channels():
    return json.load(open(fixture_path("channels.json")))["channels"]


@pytest.fixture
def by_handle(channels):
    return {c["handle"]: c for c in channels}


@pytest.fixture(autouse=True)
def sandbox(monkeypatch, tmp_path):
    """Pin today, keep reports out of ~/ytscout, and make any live fetch fail loudly."""
    monkeypatch.setattr(scout, "_now", lambda: NOW)
    monkeypatch.setattr(scout, "REPORT_DIR", str(tmp_path))
    monkeypatch.setattr(scout, "CACHE_DIR", str(tmp_path))

    def no_network(*a, **k):
        raise AssertionError("tests must not hit the network")
    monkeypatch.setattr(scout, "_ydl", no_network)
    return tmp_path


@pytest.fixture
def offline_channels(monkeypatch, by_handle):
    """channel_dump served from fixtures (deep-copied so commands can mutate records)."""
    def fake(handle, limit=30, tolerant=False):
        c = by_handle.get(handle.lstrip("@"))
        if c is None:
            return {"error": "not found", "name": handle, "subs": None, "videos": []}
        return copy.deepcopy({"name": c["name"], "subs": c["subs"], "videos": c["videos"]})
    monkeypatch.setattr(scout, "channel_dump", fake)
    return fake


def run(argv):
    scout.main(argv)
