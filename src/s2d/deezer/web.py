"""Calls the web app's own gw-light endpoint from inside a logged-in page."""

from playwright.sync_api import Page

_CALL = """async ({method, token, body}) => {
    const r = await fetch(`/ajax/gw-light.php?method=${method}&input=3&api_version=1.0&api_token=${token}`,
                          {method: 'POST', body: JSON.stringify(body)});
    return await r.json();
}"""


class GwError(Exception):
    pass


def _personal(row: dict) -> dict:
    """A personal upload in the shape the public API uses, so it caches and summarises like any track."""
    return {
        "id": int(row["SNG_ID"]),
        "title": row["SNG_TITLE"],
        "duration": int(row["DURATION"]),
        "artist": {"name": row["ART_NAME"]},
        "album": {"title": row["ALB_TITLE"]},
        "link": f"https://www.deezer.com/track/{row['SNG_ID']}",
        "isrc": row.get("ISRC") or None,
    }


class GwSession:
    def __init__(self, page: Page) -> None:
        self.page = page
        data = self._call("deezer.getUserData", {}, token="")
        self.user_id = str(data["USER"]["USER_ID"])
        self.token = data["checkForm"]
        if self.user_id == "0":
            raise GwError("page is not logged in")

    def _call(self, method: str, body: dict, token: str | None = None) -> dict:
        res = self.page.evaluate(
            _CALL, {"method": method, "token": self.token if token is None else token, "body": body}
        )
        if res.get("error"):
            raise GwError(f"{method}: {res['error']}")
        return res["results"]

    def remove_favourites(self, ids: list[int]) -> None:
        self._call("song.removeFavorites", {"IDS": [str(i) for i in ids]})

    def add_favourites(self, ids: list[int]) -> None:
        self._call("song.addFavorites", {"IDS": [str(i) for i in ids]})

    def personal_songs(self) -> list[dict]:
        out = []
        while True:
            res = self._call("personal_song.getList", {"start": len(out), "nb": 100})
            out += [_personal(r) for r in res["data"]]
            if not res["data"] or len(out) >= res["total"]:
                return out
