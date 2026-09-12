import pytest

from helpers import write_csv
from s2d.sources import exportify

APP = ["Track URI", "Track Name", "Artist Name(s)", "Album Name", "Track Duration (ms)", "Added At", "ISRC"]
NET = ["Track URI", "Track Name", "Artist Name(s)", "Album Name", "Duration (ms)", "Added At"]


def row(
    uri="spotify:track:a",
    title="Song A",
    artists="Artist A",
    album="Album A",
    ms="200000",
    added="2020-01-01T00:00:00Z",
    isrc="XX0000000001",
):
    return [uri, title, artists, album, ms, added, isrc]


def test_detects_app_variant(tmp_path):
    export = exportify.read(write_csv(tmp_path / "e.csv", APP, [row()]))
    assert export.variant == "exportify.app"
    assert export.has_isrc
    assert export.tracks[0].isrc == "XX0000000001"


def test_detects_net_variant(tmp_path):
    export = exportify.read(write_csv(tmp_path / "e.csv", NET, [row()[:6]]))
    assert export.variant == "exportify.net"
    assert not export.has_isrc
    assert export.tracks[0].isrc is None


def test_rejects_unknown_columns(tmp_path):
    with pytest.raises(ValueError, match="not an Exportify CSV"):
        exportify.read(write_csv(tmp_path / "e.csv", ["Track URI", "Added At"], []))


def test_orders_oldest_first_with_ties_reversed(tmp_path):
    rows = [
        row(uri="spotify:track:newest", added="2020-01-03T00:00:00Z"),
        row(uri="spotify:track:tie1", added="2020-01-02T00:00:00Z"),
        row(uri="spotify:track:tie2", added="2020-01-02T00:00:00Z"),
        row(uri="spotify:track:epoch", added="1970-01-01T00:00:00Z"),
        row(uri="spotify:track:blank", added=""),
    ]
    tracks = exportify.read(write_csv(tmp_path / "e.csv", APP, rows)).tracks
    assert [t.source_uri.split(":")[-1] for t in tracks] == ["blank", "epoch", "tie2", "tie1", "newest"]
    assert [t.position for t in tracks] == [0, 1, 2, 3, 4]
    assert tracks[0].added_at is None
    assert tracks[1].added_at is None


def test_app_splits_artists_on_unescaped_comma(tmp_path):
    t = exportify.read(write_csv(tmp_path / "e.csv", APP, [row(artists="Tyler\\, The Creator, Artist B")])).tracks[0]
    assert t.artists == ("Tyler, The Creator", "Artist B")


def test_net_splits_artists_on_semicolon(tmp_path):
    t = exportify.read(write_csv(tmp_path / "e.csv", NET, [row(artists="Artist A;Artist B; ")[:6]])).tracks[0]
    assert t.artists == ("Artist A", "Artist B")


def test_empty_uri_reports_line(tmp_path):
    with pytest.raises(ValueError, match="line 3: empty Track URI"):
        exportify.read(write_csv(tmp_path / "e.csv", APP, [row(), row(uri=" ")]))


def test_bad_added_at_reports_line(tmp_path):
    with pytest.raises(ValueError, match="line 2: unexpected Added At"):
        exportify.read(write_csv(tmp_path / "e.csv", APP, [row(added="2020-01-01")]))


def test_local_blank_duration_and_bom(tmp_path):
    path = write_csv(tmp_path / "e.csv", APP, [row(uri="spotify:local:x:y:z:1", ms="", isrc="")], encoding="utf-8-sig")
    t = exportify.read(path).tracks[0]
    assert t.is_local
    assert t.duration_ms is None
    assert t.isrc is None
