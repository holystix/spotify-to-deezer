import json
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote_plus

LOCAL = "spotify:local:"


@dataclass(frozen=True)
class Item:
    uri: str
    title: str
    artists: tuple[str, ...]
    album: str
    duration_ms: int | None
    is_local: bool


def read(path: Path) -> list[Item]:
    lib = json.loads(path.read_text(encoding="utf-8"))
    items = [Item(t["uri"], t["track"], _artists(t["artist"]), t["album"], None, False) for t in lib.get("tracks", [])]
    # Liked local files are listed under "other" as bare URIs:
    # spotify:local:<artist>:<album>:<title>:<seconds>, fields url-encoded.
    items += [_local(uri) for uri in lib.get("other", []) if uri.startswith(LOCAL)]
    return items


def _local(uri: str) -> Item:
    parts = uri[len(LOCAL):].split(":")
    if len(parts) != 4:
        raise ValueError(f"unexpected local file URI {uri!r}")
    artist, album, title, seconds = (unquote_plus(p) for p in parts)
    return Item(uri, title, _artists(artist), album, int(seconds) * 1000 if seconds.isdigit() else None, True)


def _artists(s: str) -> tuple[str, ...]:
    return tuple(a.strip() for a in s.split(", ") if a.strip())
