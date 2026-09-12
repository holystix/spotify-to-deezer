import time
import urllib.request

import pytest

from helpers import FakeCatalog, FakeGw
from s2d import browser
from s2d.config import Config
from s2d.deezer import catalog
from s2d.state import State


@pytest.fixture(autouse=True)
def no_io(monkeypatch):
    def refuse(*_a, **_k):
        raise AssertionError("network or browser reached from a test")

    monkeypatch.setattr(urllib.request, "urlopen", refuse)
    monkeypatch.setattr(browser, "sync_playwright", refuse)
    monkeypatch.setattr(time, "sleep", lambda _s: None)


@pytest.fixture
def cfg(tmp_path):
    return Config(
        data_dir=tmp_path / "data",
        deezer_country="XX",
        deezer_user_id="1",
        add_delay_min=0,
        add_delay_max=0,
        batch_size=3,
        browser_channel=None,
        headless=True,
        match_threshold=0.85,
        duration_tolerance_ms=3000,
    )


@pytest.fixture
def state(cfg):
    with State(cfg.state_path) as st:
        yield st


@pytest.fixture
def fake_catalog(monkeypatch):
    fake = FakeCatalog()
    for name in ("track", "track_by_isrc", "search", "user_favourites", "favourites_total"):
        monkeypatch.setattr(catalog, name, getattr(fake, name))
    return fake


@pytest.fixture
def fake_gw(fake_catalog):
    return FakeGw(fake_catalog)
