from datetime import datetime
from typing import cast

import pytest

from helpers import EPOCH, favourite, resolution, track
from s2d.deezer import favourites
from s2d.deezer.favourites import AddError
from s2d.deezer.web import GwSession


@pytest.fixture
def seeded(state):
    state.replace_tracks([track(i) for i in range(3)])
    for pos, id in enumerate((10, 11, 12)):
        state.upsert_resolution(resolution(f"spotify:track:{pos}", deezer_id=id))
    state.record_add(0, 10, 1, "2020-01-01T00:00:00")
    return state


def test_reconcile_missing_add_aborts(seeded, fake_catalog):
    with pytest.raises(AddError, match=r"1 recorded adds are no longer favourites, e.g. \[10\]"):
        favourites.reconcile(seeded, "1", 2, False)


def test_reconcile_adopts_the_next_pending_row(seeded, fake_catalog):
    fake_catalog.favourites = [favourite(10, EPOCH), favourite(11, EPOCH + 5)]
    assert favourites.reconcile(seeded, "1", 2, False) == 2
    adopted = dict(seeded.adds()[1])
    assert adopted == {
        "position": 1,
        "deezer_id": 11,
        "batch": 2,
        "added_at": datetime.fromtimestamp(EPOCH + 5).isoformat(timespec="seconds"),
    }


def test_reconcile_rejects_an_extra_that_is_not_next(seeded, fake_catalog):
    fake_catalog.favourites = [favourite(10, EPOCH), favourite(12, EPOCH + 5)]
    with pytest.raises(AddError, match=r"1 favourites are not recorded adds, e.g. \[12\]"):
        favourites.reconcile(seeded, "1", 2, False)
    assert favourites.reconcile(seeded, "1", 2, True) == 2
    assert seeded.count("adds") == 1


def test_reconcile_rejects_two_extras_even_if_one_is_next(seeded, fake_catalog):
    fake_catalog.favourites = [favourite(10, EPOCH), favourite(11, EPOCH + 5), favourite(12, EPOCH + 10)]
    with pytest.raises(AddError, match="2 favourites are not recorded adds"):
        favourites.reconcile(seeded, "1", 2, False)
    assert favourites.reconcile(seeded, "1", 2, True) == 3
    assert seeded.count("adds") == 1


def test_reconcile_clean(seeded, fake_catalog):
    fake_catalog.favourites = [favourite(10, EPOCH)]
    assert favourites.reconcile(seeded, "1", 2, False) == 1


def test_add_all_records_in_order(seeded, fake_catalog, fake_gw):
    fake_catalog.favourites = [favourite(10, EPOCH)]
    rows = seeded.pending_adds()
    favourites.add_all(seeded, cast(GwSession, fake_gw), "1", rows, 2, 0, 0, 1)
    assert [(a["position"], a["deezer_id"], a["batch"]) for a in seeded.adds()] == [(0, 10, 1), (1, 11, 2), (2, 12, 2)]
    assert [f["id"] for f in fake_catalog.favourites] == [10, 11, 12]


def test_add_all_stops_when_count_jumps(seeded, fake_catalog, fake_gw):
    fake_catalog.favourites = [favourite(10, EPOCH)]
    fake_gw.jump = 1
    with pytest.raises(AddError, match="position 1: favourite count jumped to 3, expected 2"):
        favourites.add_all(seeded, cast(GwSession, fake_gw), "1", seeded.pending_adds(), 2, 0, 0, 1)
    assert [a["position"] for a in seeded.adds()] == [0]


def test_add_all_refuses_incomplete_resolution(seeded, fake_gw):
    rows = [(track(1), resolution("spotify:track:1", deezer_id=None))]
    with pytest.raises(AddError, match="position 1: matched row has no Deezer track"):
        favourites.add_all(seeded, cast(GwSession, fake_gw), "1", rows, 2, 0, 0, 0)


def test_await_total_times_out(fake_catalog):
    fake_catalog.favourites = [favourite(10, EPOCH)]
    with pytest.raises(AddError, match="position 4: favourite count stayed at 1, expected 2"):
        favourites._await_total("1", 2, 4, timeout_s=-1)
