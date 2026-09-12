from pathlib import Path

import pytest

from s2d import config

VARS = (
    "DATA_DIR",
    "DEEZER_COUNTRY",
    "DEEZER_USER_ID",
    "ADD_DELAY_MIN",
    "ADD_DELAY_MAX",
    "BATCH_SIZE",
    "BROWSER_CHANNEL",
    "HEADLESS",
    "MATCH_THRESHOLD",
    "DURATION_TOLERANCE_MS",
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    monkeypatch.setattr(config, "load_dotenv", lambda: None)
    for name in VARS:
        monkeypatch.delenv(name, raising=False)


@pytest.mark.parametrize("country", ["", "X", "XXX"])
def test_country_is_required(monkeypatch, country):
    monkeypatch.setenv("DEEZER_COUNTRY", country)
    with pytest.raises(SystemExit, match="DEEZER_COUNTRY"):
        config.load()


def test_defaults(monkeypatch):
    monkeypatch.setenv("DEEZER_COUNTRY", " xx ")
    cfg = config.load()
    assert cfg.deezer_country == "XX"
    assert cfg.data_dir == Path("data")
    assert cfg.deezer_user_id is None
    assert cfg.browser_channel == "chrome"
    assert not cfg.headless
    assert (cfg.add_delay_min, cfg.add_delay_max, cfg.batch_size) == (2.0, 3.0, 100)
    assert (cfg.match_threshold, cfg.duration_tolerance_ms) == (0.85, 3000)
    assert cfg.state_path == Path("data/state.sqlite")
    assert cfg.placements_path == Path("data/reconcile.csv")


@pytest.mark.parametrize(("raw", "want"), [("1", True), ("true", True), ("YES", True), ("0", False), ("no", False)])
def test_headless(monkeypatch, raw, want):
    monkeypatch.setenv("DEEZER_COUNTRY", "XX")
    monkeypatch.setenv("HEADLESS", raw)
    assert config.load().headless is want


def test_overrides(monkeypatch, tmp_path):
    for name, value in {
        "DEEZER_COUNTRY": "XX",
        "DATA_DIR": str(tmp_path),
        "DEEZER_USER_ID": "",
        "BROWSER_CHANNEL": "",
        "BATCH_SIZE": "7",
        "ADD_DELAY_MIN": "0.5",
        "MATCH_THRESHOLD": "0.9",
        "DURATION_TOLERANCE_MS": "1500",
    }.items():
        monkeypatch.setenv(name, value)
    cfg = config.load()
    assert cfg.data_dir == tmp_path
    assert cfg.deezer_user_id is None
    assert cfg.browser_channel is None
    assert (cfg.batch_size, cfg.add_delay_min, cfg.match_threshold, cfg.duration_tolerance_ms) == (7, 0.5, 0.9, 1500)
