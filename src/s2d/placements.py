import csv
import re
import urllib.parse
from bisect import bisect_right
from dataclasses import dataclass, replace
from pathlib import Path

from .model import Track
from .sources.spotify_export import Item

HEADER = ("source_uri", "added_at", "artists", "title", "album", "duration_s", "search_link")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
STAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


@dataclass(frozen=True)
class Placement:
    item: Item
    added_at: str | None
    skip: bool


def sync(path: Path, missing: list[Item]) -> list[Placement]:
    """Rewrite the file to list exactly `missing`, keeping any added_at already filled in."""
    filled = {}
    if path.exists():
        with path.open(newline="", encoding="utf-8-sig") as f:
            for n, row in enumerate(csv.DictReader(f), start=2):
                filled[(row.get("source_uri") or "").strip()] = (n, (row.get("added_at") or "").strip())
    out = [Placement(i, *_parse(path, *filled.get(i.uri, (0, "")))) for i in missing]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(HEADER)
        for i in missing:
            raw = filled.get(i.uri, (0, ""))[1]
            q = urllib.parse.quote(f"{i.artists[0] if i.artists else ''} {i.title}")
            w.writerow([i.uri, raw, "; ".join(i.artists), i.title, i.album,
                        round(i.duration_ms / 1000) if i.duration_ms else "", f"https://www.deezer.com/search/{q}"])
    return out


def _parse(path: Path, line: int, raw: str) -> tuple[str | None, bool]:
    if not raw:
        return None, False
    if raw.upper() == "SKIP":
        return None, True
    if DATE.match(raw):
        return f"{raw}T23:59:59Z", False
    if STAMP.match(raw):
        return raw, False
    raise ValueError(f"{path}:{line}: added_at must be YYYY-MM-DD, YYYY-MM-DDTHH:MM:SSZ or SKIP, got {raw!r}")


def merge(existing: list[Track], placed: list[Placement]) -> tuple[list[Track], list[Track]]:
    """Insert each placed track after every track added at or before its timestamp; renumber positions."""
    order = list(existing)
    keys = [t.added_at or "" for t in order]
    for p in placed:
        i = p.item
        t = Track(-1, i.uri, i.title, i.artists, i.album, i.duration_ms, p.added_at, None, i.is_local)
        at = bisect_right(keys, t.added_at or "")
        order.insert(at, t)
        keys.insert(at, t.added_at or "")
    new = {p.item.uri for p in placed}
    merged = [replace(t, position=n) for n, t in enumerate(order)]
    return merged, [t for t in merged if t.source_uri in new]
