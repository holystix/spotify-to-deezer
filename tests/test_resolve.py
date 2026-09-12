import pytest

from helpers import obj, resolution, track, write_csv
from s2d import overrides
from s2d.deezer import resolve
from s2d.deezer.resolve import Resolver


@pytest.fixture
def resolver(state, fake_catalog):
    return Resolver(state, "XX", 0.85, 3000)


def test_summary_fills_link_and_isrc():
    s = resolve.summary(obj(7))
    assert s["link"] == "https://www.deezer.com/track/7"
    assert s["isrc"] is None
    assert resolve.summary({**obj(7), "link": "x"})["link"] == "x"


def test_candidate_prefers_contributors_and_title_short():
    c = resolve.candidate(obj(1, contributors=["Artist A", "Artist B"], title_short="Short"))
    assert (c.artists, c.title_short, c.duration_ms) == (("Artist A", "Artist B"), "Short", 200_000)
    c = resolve.candidate(obj(1))
    assert (c.artists, c.title_short) == (("Artist A",), "Song A")


def test_track_uses_cache_then_catalog(resolver, state, fake_catalog):
    state.cache_track(obj(1, title="Cached"))
    assert resolver.track(1)["title"] == "Cached"
    assert fake_catalog.calls == []
    fake_catalog.add(obj(2))
    assert resolver.track(2)["id"] == 2
    assert state.cached_track(2) is not None
    with pytest.raises(SystemExit, match="personal upload"):
        resolver.track(-1)


@pytest.mark.parametrize(
    ("countries", "alt", "alt_countries", "want"),
    [
        (None, None, None, (1, False)),
        (["XX"], None, None, (1, False)),
        (["YY"], None, None, (None, False)),
        (["YY"], 2, ["XX"], (2, True)),
        (["YY"], 2, None, (2, True)),
        (["YY"], 2, ["ZZ"], (None, False)),
    ],
)
def test_available(resolver, fake_catalog, countries, alt, alt_countries, want):
    if alt:
        fake_catalog.add(obj(alt, countries=alt_countries))
    got, via_alt = resolver._available(obj(1, countries=countries, alternative=alt))
    assert (got and got["id"], via_alt) == want


def test_resolve_by_isrc_skips_search(resolver, fake_catalog):
    fake_catalog.add(obj(1, isrc="XX1"))
    res = resolver.resolve(track(isrc="XX1"))
    assert (res.status, res.method, res.deezer_id, res.score) == ("matched", "isrc", 1, 1.0)
    assert fake_catalog.searches() == []


def test_resolve_isrc_duration_mismatch_prefers_search_hit(resolver, fake_catalog):
    fake_catalog.add(obj(1, isrc="XX1", duration=230), obj(2))
    fake_catalog.results = [obj(2)]
    res = resolver.resolve(track(isrc="XX1"))
    assert (res.status, res.method, res.deezer_id) == ("matched", "search", 2)
    assert res.note == "ISRC hit https://www.deezer.com/track/1 duration differs by 30s; matched by search instead"


def test_resolve_isrc_duration_mismatch_without_search_hit(resolver, fake_catalog):
    fake_catalog.add(obj(1, isrc="XX1", duration=230))
    res = resolver.resolve(track(isrc="XX1"))
    assert (res.status, res.method, res.deezer_id) == ("needs-review", "isrc", 1)
    assert res.note == "duration differs by 30s; no search candidates"


def test_resolve_isrc_unavailable_falls_back_to_search(resolver, fake_catalog):
    fake_catalog.add(obj(1, isrc="XX1", countries=["YY"]), obj(2))
    fake_catalog.results = [obj(2)]
    res = resolver.resolve(track(isrc="XX1"))
    assert (res.status, res.method, res.deezer_id, res.note) == ("matched", "search", 2, None)


def test_resolve_isrc_unavailable_without_candidates(resolver, fake_catalog):
    fake_catalog.add(obj(1, isrc="XX1", countries=["YY"]))
    res = resolver.resolve(track(isrc="XX1"))
    assert res.status == "unmatched"
    assert res.candidate["id"] == 1
    assert res.note == "ISRC hit unavailable in XX; no search candidates"


def test_resolve_isrc_unavailable_with_weak_candidate(resolver, fake_catalog):
    fake_catalog.add(obj(1, isrc="XX1", countries=["YY"]), obj(2, title="Unrelated", artist="Nobody"))
    fake_catalog.results = [obj(2, title="Unrelated", artist="Nobody")]
    res = resolver.resolve(track(isrc="XX1"))
    assert (res.status, res.candidate["id"]) == ("unmatched", 2)
    assert res.note.startswith("ISRC hit unavailable in XX: https://www.deezer.com/track/1; best available scored")


def test_resolve_below_threshold_reports_best(resolver, fake_catalog):
    weak = obj(2, title="Unrelated", artist="Nobody")
    fake_catalog.add(weak)
    fake_catalog.results = [weak]
    res = resolver.resolve(track())
    assert (res.status, res.method, res.deezer_id, res.candidate["id"]) == ("unmatched", None, None, 2)
    assert res.score < 0.85
    assert res.note.startswith("best candidate scored")
    assert len(fake_catalog.searches()) == 4


def test_resolve_stops_querying_once_confident(resolver, fake_catalog):
    fake_catalog.add(obj(2))
    fake_catalog.results = [obj(2)]
    resolver.resolve(track())
    assert fake_catalog.searches() == ["Artist A song a"]


def test_resolve_no_results(resolver, fake_catalog):
    res = resolver.resolve(track())
    assert (res.status, res.candidate, res.note) == ("unmatched", None, "no search results")


def test_resolve_search_isrc(resolver, fake_catalog):
    other = obj(3, title="Renamed Release", artist="Other Name", isrc="XX1")
    fake_catalog.add(other)
    fake_catalog.by_isrc.clear()
    fake_catalog.results = [other]
    res = resolver.resolve(track(isrc="XX1"))
    assert (res.status, res.method, res.deezer_id) == ("matched", "search-isrc", 3)


def test_accept_duration_rule(resolver):
    assert resolver._accept(track(duration_ms=None), obj(duration=999), "isrc").status == "matched"
    assert resolver._accept(track(), obj(duration=230), "search").status == "matched"
    assert resolver._accept(track(), obj(duration=211), "isrc-alt").status == "needs-review"


def test_apply_overrides(resolver, state, fake_catalog, tmp_path):
    state.replace_tracks([track(i) for i in range(3)])
    state.cache_track(obj(-3, title="Upload"))
    fake_catalog.add(obj(5))
    path = write_csv(
        tmp_path / "o.csv",
        overrides.HEADER,
        [
            ["spotify:track:9", "1", "unknown"],
            ["spotify:track:0", "SKIP", "gone"],
            ["spotify:track:1", "5", "picked"],
            ["spotify:track:2", "-3", ""],
        ],
    )
    assert resolve.apply_overrides(state, resolver, path) == 3
    by_pos = {t.position: r for t, r in state.resolved()}
    assert (by_pos[0].status, by_pos[0].method, by_pos[0].note) == ("skip", "override", "gone")
    assert (by_pos[1].status, by_pos[1].method, by_pos[1].deezer_id, by_pos[1].candidate["id"]) == (
        "matched",
        "override",
        5,
        5,
    )
    assert (by_pos[2].method, by_pos[2].candidate["title"]) == ("upload", "Upload")


def test_apply_overrides_unknown_upload_exits(resolver, state, tmp_path):
    state.replace_tracks([track(0)])
    path = write_csv(tmp_path / "o.csv", overrides.HEADER, [["spotify:track:0", "-9", ""]])
    with pytest.raises(SystemExit):
        resolve.apply_overrides(state, resolver, path)


def test_match_uploads(state):
    state.replace_tracks([track(0), track(1, title="Something Else")])
    state.upsert_resolution(resolution("spotify:track:0", "unmatched", None, None, None))
    state.upsert_resolution(resolution("spotify:track:1", "matched", deezer_id=4))
    upload = obj(-1)
    [(got, pair, score)] = resolve.match_uploads(state, [upload], 3000)
    assert got is upload
    assert pair is not None
    assert pair[0].position == 0
    assert score == 1.0
    state.set_status("spotify:track:0", "matched", None)
    assert resolve.match_uploads(state, [upload], 3000) == [(upload, None, 0.0)]


def test_collapse_duplicates(state):
    state.replace_tracks([track(i) for i in range(4)])
    state.upsert_resolution(resolution("spotify:track:0", deezer_id=10))
    state.upsert_resolution(resolution("spotify:track:1", deezer_id=10))
    state.upsert_resolution(resolution("spotify:track:2", deezer_id=11))
    state.upsert_resolution(resolution("spotify:track:3", "dup-skip", deezer_id=12, note="stale"))
    assert resolve.collapse_duplicates(state) == 2
    by_pos = {t.position: r for t, r in state.resolved()}
    assert (by_pos[1].status, by_pos[1].note) == ("dup-skip", "duplicate of position 0")
    assert (by_pos[3].status, by_pos[3].note) == ("matched", None)
    assert by_pos[0].status == by_pos[2].status == "matched"
    assert resolve.collapse_duplicates(state) == 0
