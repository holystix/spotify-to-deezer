import csv
from datetime import datetime

from helpers import favourite, track
from s2d.deezer import verify


def seed(state):
    state.replace_tracks([track(i) for i in range(3)])
    for pos, id in enumerate((10, 11, 12)):
        state.record_add(pos, id, 1 + pos // 2, "2020-01-01T00:00:00")


def test_ok(state, fake_catalog):
    seed(state)
    fake_catalog.favourites = [favourite(10, 100), favourite(11, 200), favourite(12, 300)]
    report = verify.check(state, "1")
    assert report.ok
    assert [r["position"] for r in report.rows] == [0, 1, 2]
    assert report.rows[2]["time_add_iso"] == datetime.fromtimestamp(300).isoformat(timespec="seconds")
    assert report.rows[2]["batch"] == 2


def test_missing_does_not_break_the_chain(state, fake_catalog):
    seed(state)
    fake_catalog.favourites = [favourite(10, 100), favourite(12, 300)]
    report = verify.check(state, "1")
    assert report.issues == ["position 1: missing from favourites"]
    assert report.rows[1]["time_add_iso"] == ""


def test_time_add_must_strictly_increase(state, fake_catalog):
    seed(state)
    fake_catalog.favourites = [favourite(10, 100), favourite(11, 100), favourite(12, 50)]
    report = verify.check(state, "1")
    assert report.issues == [
        "position 1: time_add 100 not after previous 100",
        "position 2: time_add 50 not after previous 100",
    ]


def test_extras_are_reported(state, fake_catalog):
    seed(state)
    fake_catalog.favourites = [favourite(10, 100), favourite(11, 200), favourite(12, 300), favourite(99, 400)]
    assert verify.check(state, "1").issues == ["1 favourites not recorded as adds, e.g. [99]"]


def test_write(state, fake_catalog, tmp_path):
    seed(state)
    fake_catalog.favourites = [favourite(10, 100), favourite(11, 200), favourite(12, 300)]
    out = tmp_path / "verify.csv"
    verify.write(verify.check(state, "1"), out)
    rows = list(csv.DictReader(out.open()))
    assert tuple(rows[0]) == verify.FIELDS
    assert [r["deezer_id"] for r in rows] == ["10", "11", "12"]
