import csv

import pytest

from helpers import item, track
from s2d import placements
from s2d.placements import Placement


@pytest.mark.parametrize(
    ("raw", "out"),
    [
        ("", (None, False)),
        ("SKIP", (None, True)),
        ("skip", (None, True)),
        ("2020-05-06", ("2020-05-06T23:59:59Z", False)),
        ("2020-05-06T01:02:03Z", ("2020-05-06T01:02:03Z", False)),
    ],
)
def test_parse(tmp_path, raw, out):
    assert placements._parse(tmp_path / "r.csv", 2, raw) == out


def test_parse_rejects_other_formats(tmp_path):
    with pytest.raises(ValueError, match=r"r\.csv:7: added_at must be"):
        placements._parse(tmp_path / "r.csv", 7, "06/05/2020")


def test_sync_creates_file_and_keeps_filled_dates(tmp_path):
    path = tmp_path / "data" / "reconcile.csv"
    a, b = item("spotify:local:a"), item("spotify:local:b", duration_ms=None)
    first = placements.sync(path, [a, b])
    assert [p.added_at for p in first] == [None, None]
    rows = list(csv.DictReader(path.open()))
    assert tuple(rows[0]) == placements.HEADER
    assert rows[1]["duration_s"] == ""

    rows[0]["added_at"] = "2020-01-02"
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(placements.HEADER))
        w.writeheader()
        w.writerows(rows)

    second = placements.sync(path, [a])
    assert second == [Placement(a, "2020-01-02T23:59:59Z", False)]
    assert [r["source_uri"] for r in csv.DictReader(path.open())] == ["spotify:local:a"]


def test_merge_places_after_equal_timestamps_and_renumbers():
    existing = [
        track(0, added_at="2020-01-01T00:00:00Z"),
        track(1, added_at="2020-01-02T00:00:00Z"),
        track(2, added_at="2020-01-03T00:00:00Z"),
    ]
    placed = [
        Placement(item("spotify:local:tie"), "2020-01-02T00:00:00Z", False),
        Placement(item("spotify:local:undated"), None, False),
        Placement(item("spotify:local:last"), "2020-01-04T00:00:00Z", False),
    ]
    merged, inserted = placements.merge(existing, placed)
    uris = [t.source_uri for t in merged]
    assert uris == [
        "spotify:local:undated",
        "spotify:track:0",
        "spotify:track:1",
        "spotify:local:tie",
        "spotify:track:2",
        "spotify:local:last",
    ]
    assert [t.position for t in merged] == list(range(6))
    assert [t.source_uri for t in inserted] == ["spotify:local:undated", "spotify:local:tie", "spotify:local:last"]
    assert inserted[1].is_local and inserted[1].isrc is None


def test_merge_keeps_existing_order():
    existing = [track(i, added_at=f"2020-01-0{i + 1}T00:00:00Z") for i in range(5)]
    placed = [Placement(item(f"spotify:local:{i}"), f"2020-01-0{i + 1}T12:00:00Z", False) for i in range(5)]
    merged, _ = placements.merge(existing, placed)
    kept = [t.source_uri for t in merged if not t.is_local]
    assert kept == [t.source_uri for t in existing]
