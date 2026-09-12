from typing import cast

import pytest
from playwright.sync_api import Page

from helpers import FakePage
from s2d.deezer import web
from s2d.deezer.web import GwError, GwSession


def page(**kw) -> tuple[FakePage, Page]:
    fake = FakePage(**kw)
    return fake, cast(Page, fake)


def upload_row(n: int) -> dict:
    return {
        "SNG_ID": str(-n),
        "SNG_TITLE": f"Song {n}",
        "DURATION": "180",
        "ART_NAME": "Artist U",
        "ALB_TITLE": "Album U",
        "ISRC": "",
    }


def test_personal_reshapes_to_api_form():
    got = web._personal(upload_row(5))
    assert got == {
        "id": -5,
        "title": "Song 5",
        "duration": 180,
        "artist": {"name": "Artist U"},
        "album": {"title": "Album U"},
        "link": "https://www.deezer.com/track/-5",
        "isrc": None,
    }


def test_session_requires_login():
    with pytest.raises(GwError, match="not logged in"):
        GwSession(page(user_id="0")[1])


def test_session_bootstraps_token_then_uses_it():
    fake, p = page()
    gw = GwSession(p)
    gw.add_favourites([1, 2])
    assert (gw.user_id, gw.token) == ("1", "tok")
    assert fake.calls[0]["token"] == ""
    assert fake.calls[1] == {"method": "song.addFavorites", "token": "tok", "body": {"IDS": ["1", "2"]}}


def test_call_surfaces_errors():
    gw = GwSession(page(error="VALID_TOKEN_REQUIRED")[1])
    with pytest.raises(GwError, match=r"song\.removeFavorites: VALID_TOKEN_REQUIRED"):
        gw.remove_favourites([1])


def test_personal_songs_paginates_until_total():
    fake, p = page(rows=[upload_row(n) for n in range(150)])
    got = GwSession(p).personal_songs()
    assert len(got) == 150
    assert [c["body"]["start"] for c in fake.calls[1:]] == [0, 100]


def test_personal_songs_stops_on_empty_page():
    fake, p = page(rows=[upload_row(n) for n in range(3)], total=10)
    assert len(GwSession(p).personal_songs()) == 3
    assert [c["body"]["start"] for c in fake.calls[1:]] == [0, 3]
