import pytest

from helpers import track
from s2d import match
from s2d.match import Candidate, Score


def cand(title="Song A", title_short="", artists=("Artist A",), duration_ms=200_000):
    return Candidate(1, title, title_short, artists, duration_ms)


@pytest.mark.parametrize(
    ("raw", "out"),
    [
        ("Café Ünïcode", "cafe unicode"),
        ("Rock & Roll", "rock and roll"),
        ("Don’t Stop", "dont stop"),
        ("A  -- B_c!", "a b c"),
        ("", ""),
    ],
)
def test_norm(raw, out):
    assert match.norm(raw) == out


@pytest.mark.parametrize(
    ("raw", "out"),
    [
        ("Song (Live)", "song"),
        ("Song [Remix] - Radio Edit", "song"),
        ("Song - 2011 Remaster", "song"),
        ("Plain", "plain"),
        ("Hyphen-Word - Tail", "hyphen word"),
    ],
)
def test_core(raw, out):
    assert match.core(raw) == out


@pytest.mark.parametrize(
    ("raw", "out"),
    [
        ("Song - Live", {"live"}),
        ("Song (2011 Remaster)", set()),
        ("Song (Remastered 2011)", set()),
        ("Song (Original Mix)", set()),
        ("Song - Album Version", set()),
        ("Song - Radio Edit", {"radio", "edit"}),
    ],
)
def test_versions(raw, out):
    assert match.versions(raw) == out


def test_title_score_identical():
    assert match.title_score("Song A", cand()) == 1.0


def test_title_score_caps_version_mismatch():
    assert match.title_score("Song A", cand("Song A (Live)")) == 0.6
    assert match.title_score("Song A - Live", cand("Song A")) == 0.6


def test_title_score_uses_title_short():
    with_short = match.title_score("Song A", cand("Song A feat. Somebody", title_short="Song A"))
    without = match.title_score("Song A", cand("Song A feat. Somebody"))
    assert with_short == 1.0
    assert without < 1.0


@pytest.mark.parametrize(
    ("spotify", "deezer", "out"),
    [
        ((), ("Artist A",), 0.0),
        (("Artist A",), (), 0.0),
        (("Artist A",), ("Artist A",), 1.0),
        (("Artist A", "Someone Else"), ("Artist A",), 0.85),
        (("Artist A",), ("Artist B", "Artist A"), 1.0),
    ],
)
def test_artist_score(spotify, deezer, out):
    assert match.artist_score(spotify, deezer) == pytest.approx(out)


@pytest.mark.parametrize(
    ("a", "b", "out"),
    [
        (None, 200_000, 0.5),
        (200_000, 203_000, 1.0),
        (200_000, 203_001, 0.5),
        (200_000, 210_000, 0.5),
        (200_000, 210_001, 0.0),
    ],
)
def test_duration_score(a, b, out):
    assert match.duration_score(a, b, 3000) == out


def test_score_weights():
    perfect = match.score(track(), cand(), 3000)
    assert perfect == Score(1.0, 1.0, 1.0, 1.0)
    far = match.score(track(duration_ms=None), cand(), 3000)
    assert far.total == pytest.approx(0.9)
    assert str(far) == "title 1.00 artist 1.00 duration 0.50"
