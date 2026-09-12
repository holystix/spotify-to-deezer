from helpers import obj, resolution, track
from s2d.state import State


def test_open_is_idempotent(cfg):
    with State(cfg.state_path) as a:
        a.set_meta("k", "1")
    with State(cfg.state_path) as b:
        b.set_meta("k", "2")
        assert b.get_meta("k") == "2"
        assert b.get_meta("missing") is None


def test_replace_tracks_round_trips(state):
    t = track(0, artists=("Artist A", "Artist B"), duration_ms=None, added_at=None, isrc=None, is_local=True)
    state.replace_tracks([t, track(1)])
    assert state.tracks() == [t, track(1)]
    assert state.has_track("spotify:track:1")
    assert not state.has_track("spotify:track:9")
    state.replace_tracks([track(5)])
    assert [t.position for t in state.tracks()] == [5]


def seed(state):
    state.replace_tracks([track(i) for i in range(6)])
    state.upsert_resolution(resolution("spotify:track:0", "matched", deezer_id=10))
    state.upsert_resolution(resolution("spotify:track:1", "unmatched", None, None, 0.4))
    state.upsert_resolution(resolution("spotify:track:2", "needs-review", deezer_id=12))
    state.upsert_resolution(resolution("spotify:track:3", "skip", "override", None, None))
    state.upsert_resolution(resolution("spotify:track:4", "dup-skip", deezer_id=10))


def test_pending_tracks(state):
    seed(state)
    assert [t.position for t in state.pending_tracks(retry=False)] == [5]
    assert [t.position for t in state.pending_tracks(retry=True)] == [1, 2, 5]


def test_resolutions(state):
    seed(state)
    state.upsert_resolution(resolution("spotify:track:0", "matched", "search", 11, 0.9, {"id": 11}, "n"))
    _, r = state.resolved(("matched",))[0]
    assert (r.deezer_id, r.candidate, r.note) == (11, {"id": 11}, "n")
    assert [t.position for t, _ in state.resolved()] == [0, 1, 2, 3, 4]
    assert [t.position for t, _ in state.resolved(("skip", "dup-skip"))] == [3, 4]
    assert state.resolution_counts() == [
        ("dup-skip", "isrc", 1),
        ("matched", "search", 1),
        ("needs-review", "isrc", 1),
        ("skip", "override", 1),
        ("unmatched", None, 1),
    ]
    state.set_status("spotify:track:1", "matched", None)
    assert state.resolved(("matched",))[1][1].note is None


def test_adds_and_blocking(state):
    seed(state)
    state.upsert_resolution(resolution("spotify:track:5", "matched", deezer_id=15))
    assert [t.position for t, _ in state.pending_adds()] == [0, 5]
    assert state.next_batch() == 1
    state.record_add(0, 10, 1, "2020-01-01T00:00:00")
    assert [t.position for t, _ in state.pending_adds()] == [5]
    assert [(t.position, s) for t, s in state.blocking(2)] == [(1, "unmatched"), (2, "needs-review")]
    assert state.blocking(0) == []
    state.replace_tracks([*state.tracks(), track(6)])
    assert [(t.position, s) for t, s in state.blocking(6)][-1] == (6, "unresolved")
    assert state.next_batch() == 2
    assert [dict(a) for a in state.adds()] == [
        {"position": 0, "deezer_id": 10, "batch": 1, "added_at": "2020-01-01T00:00:00"}
    ]
    assert state.clear_adds() == 1
    assert state.count("adds") == 0


def test_reset_duplicates(state):
    seed(state)
    state.reset_duplicates()
    statuses = {t.position: r.status for t, r in state.resolved()}
    assert statuses[4] == "matched"
    assert statuses[3] == "skip"


def test_track_cache(state):
    assert state.cached_track(1) is None
    state.cache_track(obj(1, title="Old"))
    state.cache_track(obj(1, title="New"))
    assert state.cached_track(1)["title"] == "New"
