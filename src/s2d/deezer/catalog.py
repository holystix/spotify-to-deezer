"""Deezer public API. Unauthenticated, read-only, IP-relative `readable`."""

import http.client
import json
import time
import urllib.parse
import urllib.request
from collections import deque
from collections.abc import Iterator

BASE = "https://api.deezer.com"
QUOTA_CODE = 4
NO_DATA_CODE = 800
WINDOW_S, WINDOW_MAX = 5.0, 40

_recent: deque[float] = deque()


class ApiError(Exception):
    pass


def get(path: str, **params: str | int) -> dict:
    return get_url(_url(path, params))


def get_optional(path: str, **params: str | int) -> dict | None:
    return _fetch(_url(path, params), allow_missing=True)


def _url(path: str, params: dict) -> str:
    url = f"{BASE}/{path.lstrip('/')}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    return url


def get_url(url: str) -> dict:
    data = _fetch(url)
    if data is None:
        raise ApiError(f"{url}: no data")
    return data


def _fetch(url: str, allow_missing: bool = False) -> dict | None:
    for attempt in range(6):
        _throttle()
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                data = json.load(r)
        except (OSError, http.client.HTTPException, ValueError) as e:
            if attempt == 5:
                raise ApiError(f"{url}: {e}") from None
            time.sleep(2 + attempt * 2)
            continue
        err = data.get("error") if isinstance(data, dict) else None
        if not err:
            return data
        if err.get("code") == QUOTA_CODE:
            time.sleep(2 + attempt * 2)
            continue
        if err.get("code") == NO_DATA_CODE and allow_missing:
            return None
        raise ApiError(f"{url}: {err}")
    raise ApiError(f"{url}: quota retries exhausted")


def _throttle() -> None:
    now = time.monotonic()
    while _recent and now - _recent[0] > WINDOW_S:
        _recent.popleft()
    if len(_recent) >= WINDOW_MAX:
        time.sleep(WINDOW_S - (now - _recent[0]) + 0.05)
    _recent.append(time.monotonic())


def iter_pages(path: str, **params: str | int) -> Iterator[dict]:
    data = get(path, **params)
    while True:
        yield from data["data"]
        if not data.get("next"):
            return
        data = get_url(data["next"])


def track(track_id: int) -> dict:
    return get(f"track/{track_id}")


def track_by_isrc(isrc: str) -> dict | None:
    return get_optional(f"track/isrc:{isrc}")


def search(q: str, limit: int = 10) -> list[dict]:
    return get("search", q=q, limit=limit)["data"]


def user_favourites(user_id: str) -> list[dict]:
    return list(iter_pages(f"user/{user_id}/tracks", limit=100))


def favourites_total(user_id: str) -> int:
    return get(f"user/{user_id}/tracks", limit=1)["total"]
