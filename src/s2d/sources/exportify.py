import csv
import re
from dataclasses import dataclass
from pathlib import Path

from ..model import Track

ADDED_AT = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

DURATION = {"exportify.net": "Duration (ms)", "exportify.app": "Track Duration (ms)"}
# exportify.app escapes commas inside artist names as "\,".
SPLIT = {
    "exportify.net": lambda s: s.split(";"),
    "exportify.app": lambda s: [a.replace("\\,", ",") for a in re.split(r"(?<!\\), ", s)],
}


@dataclass(frozen=True)
class Export:
    tracks: list[Track]
    variant: str
    has_isrc: bool


def read(path: Path) -> Export:
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fields = reader.fieldnames or []
        variant = _detect(fields)
        parsed = [_parse(variant, n, row) for n, row in enumerate(reader, start=2)]
    # Exportify emits newest first, so equal timestamps keep file order reversed;
    # a missing timestamp sorts oldest.
    order = sorted(range(len(parsed)), key=lambda i: (parsed[i]["added_at"] or "", -i))
    tracks = [Track(position=pos, **parsed[i]) for pos, i in enumerate(order)]
    return Export(tracks, variant, "ISRC" in fields)


def _detect(fields: list[str]) -> str:
    for variant, column in DURATION.items():
        if column in fields:
            return variant
    raise ValueError(f"not an Exportify CSV, columns: {fields}")


def _parse(variant: str, line: int, row: dict) -> dict:
    uri = row["Track URI"].strip()
    if not uri:
        raise ValueError(f"line {line}: empty Track URI")
    added = row["Added At"].strip()
    if added and not ADDED_AT.match(added):
        raise ValueError(f"line {line}: unexpected Added At {added!r}")
    duration = row[DURATION[variant]].strip()
    return dict(
        source_uri=uri,
        title=row["Track Name"].strip(),
        artists=tuple(a.strip() for a in SPLIT[variant](row["Artist Name(s)"]) if a.strip()),
        album=row["Album Name"].strip(),
        duration_ms=int(duration) if duration else None,
        added_at=added if added and not added.startswith("1970") else None,
        isrc=(row.get("ISRC") or "").strip() or None,
        is_local=uri.startswith("spotify:local:"),
    )
