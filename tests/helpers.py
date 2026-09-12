import argparse
import csv
from pathlib import Path

from s2d.deezer import catalog
from s2d.model import Resolution, Track
from s2d.sources.spotify_export import Item

EPOCH = 1_600_000_000


def track(
    position: int = 0,
    uri: str | None = None,
    title: str = "Song A",
    artists: tuple[str, ...] = ("Artist A",),
    album: str = "Album A",
    duration_ms: int | None = 200_000,
    added_at: str | None = "2020-01-01T00:00:00Z",
    isrc: str | None = None,
    is_local: bool = False,
) -> Track:
    return Track(
        position, uri or f"spotify:track:{position}", title, artists, album, duration_ms, added_at, isrc, is_local
    )


def item(
    uri: str = "spotify:local:a",
    title: str = "Song L",
    artists: tuple[str, ...] = ("Artist L",),
    album: str = "Album L",
    duration_ms: int | None = 180_000,
    is_local: bool = True,
) -> Item:
    return Item(uri, title, artists, album, duration_ms, is_local)


def obj(
    id: int = 1,
    title: str = "Song A",
    artist: str = "Artist A",
    duration: int = 200,
    countries: list[str] | None = None,
    alternative: int | None = None,
    contributors: list[str] | None = None,
    title_short: str | None = None,
    isrc: str | None = None,
) -> dict:
    o: dict = {"id": id, "title": title, "artist": {"name": artist}, "duration": duration}
    o["album"] = {"title": "Album A"}
    if countries is not None:
        o["available_countries"] = countries
    if alternative is not None:
        o["alternative"] = {"id": alternative}
    if contributors is not None:
        o["contributors"] = [{"name": c} for c in contributors]
    if title_short is not None:
        o["title_short"] = title_short
    if isrc is not None:
        o["isrc"] = isrc
    return o


def resolution(
    uri: str,
    status: str = "matched",
    method: str | None = "isrc",
    deezer_id: int | None = 1,
    score: float | None = 1.0,
    candidate: dict | None = None,
    note: str | None = None,
) -> Resolution:
    if candidate is None and deezer_id is not None:
        candidate = {
            "id": deezer_id,
            "title": "Song A",
            "artist": "Artist A",
            "duration": 200,
            "link": "",
            "isrc": None,
        }
    return Resolution(uri, status, method, deezer_id, score, candidate, note)


def favourite(id: int, time_add: int) -> dict:
    return {"id": id, "time_add": time_add, "title": "Song", "duration": 200, "artist": {"name": "Artist"}}


def write_csv(path: Path, header: tuple[str, ...] | list[str], rows: list[list], encoding: str = "utf-8") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding=encoding) as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    return path


def ns(**kw) -> argparse.Namespace:
    defaults = {
        "csv": None,
        "retry": False,
        "limit": 0,
        "apply": False,
        "batch": 0,
        "allow_existing": False,
        "dry_run": False,
        "against": None,
        "yes": False,
        "delay": 0.0,
        "library": None,
    }
    return argparse.Namespace(**{**defaults, **kw})


class FakeCatalog:
    def __init__(self):
        self.tracks: dict[int, dict] = {}
        self.by_isrc: dict[str, dict] = {}
        self.results: list[dict] = []
        self.favourites: list[dict] = []
        self.calls: list[tuple] = []

    def add(self, *objs: dict) -> None:
        for o in objs:
            self.tracks[o["id"]] = o
            if o.get("isrc"):
                self.by_isrc[o["isrc"]] = o

    def track(self, track_id: int) -> dict:
        self.calls.append(("track", track_id))
        if track_id not in self.tracks:
            raise catalog.ApiError(f"track/{track_id}")
        return self.tracks[track_id]

    def track_by_isrc(self, isrc: str) -> dict | None:
        self.calls.append(("isrc", isrc))
        return self.by_isrc.get(isrc)

    def search(self, q: str, limit: int = 10) -> list[dict]:
        self.calls.append(("search", q))
        return list(self.results)

    def user_favourites(self, user_id: str) -> list[dict]:
        return list(self.favourites)

    def favourites_total(self, user_id: str) -> int:
        return len(self.favourites)

    def searches(self) -> list[str]:
        return [q for kind, q in self.calls if kind == "search"]


class FakeGw:
    def __init__(self, fake: FakeCatalog, user_id: str = "1"):
        self.fake = fake
        self.user_id = user_id
        self.removed: list[int] = []
        self.uploads: list[dict] = []
        self.jump = 0

    def _fav(self, id: int) -> None:
        last = max((f["time_add"] for f in self.fake.favourites), default=EPOCH)
        self.fake.favourites.append(favourite(id, last + 5))

    def add_favourites(self, ids: list[int]) -> None:
        for i in ids:
            self._fav(i)
        for n in range(self.jump):
            self._fav(900 + n)
        self.jump = 0

    def remove_favourites(self, ids: list[int]) -> None:
        self.removed += ids
        self.fake.favourites = [f for f in self.fake.favourites if f["id"] not in ids]

    def personal_songs(self) -> list[dict]:
        return list(self.uploads)


class FakePage:
    def __init__(
        self, user_id: str = "1", rows: list[dict] | None = None, total: int | None = None, error: str | None = None
    ):
        self.user_id = user_id
        self.rows = rows or []
        self.total = total
        self.error = error
        self.calls: list[dict] = []

    def evaluate(self, _js: str, arg: dict) -> dict:
        self.calls.append(arg)
        if arg["method"] == "deezer.getUserData":
            return {"results": {"USER": {"USER_ID": self.user_id}, "checkForm": "tok"}}
        if self.error:
            return {"error": self.error}
        if arg["method"] == "personal_song.getList":
            start, nb = arg["body"]["start"], arg["body"]["nb"]
            return {"results": {"data": self.rows[start : start + nb], "total": self.total or len(self.rows)}}
        return {"results": {}}

    def content(self) -> str:
        return ""
