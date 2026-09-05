"""Calls the web app's own gw-light endpoint from inside a logged-in page."""
from playwright.sync_api import Page

_CALL = """async ({method, token, body}) => {
    const r = await fetch(`/ajax/gw-light.php?method=${method}&input=3&api_version=1.0&api_token=${token}`,
                          {method: 'POST', body: JSON.stringify(body)});
    return await r.json();
}"""


class GwError(Exception):
    pass


class GwSession:
    def __init__(self, page: Page):
        self.page = page
        data = self._call("deezer.getUserData", {}, token="")
        self.user_id = str(data["USER"]["USER_ID"])
        self.token = data["checkForm"]
        if self.user_id == "0":
            raise GwError("page is not logged in")

    def _call(self, method: str, body: dict, token: str | None = None):
        res = self.page.evaluate(_CALL, {"method": method, "token": self.token if token is None else token, "body": body})
        if res.get("error"):
            raise GwError(f"{method}: {res['error']}")
        return res["results"]

    def remove_favourites(self, ids: list[int]) -> None:
        self._call("song.removeFavorites", {"IDS": [str(i) for i in ids]})

    def add_favourites(self, ids: list[int]) -> None:
        self._call("song.addFavorites", {"IDS": [str(i) for i in ids]})
