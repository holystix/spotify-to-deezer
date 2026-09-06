import csv
import re
from dataclasses import dataclass
from pathlib import Path

HEADER = ("source_uri", "deezer_id", "note")


@dataclass(frozen=True)
class Override:
    source_uri: str
    deezer_id: int | None
    note: str


def read(path: Path) -> list[Override]:
    if not path.exists():
        return []
    out = []
    with path.open(newline="", encoding="utf-8-sig") as f:
        for n, row in enumerate(csv.DictReader(f), start=2):
            uri = (row.get("source_uri") or "").strip()
            raw = (row.get("deezer_id") or "").strip()
            if not uri and not raw:
                continue
            if raw.upper() == "SKIP":
                deezer_id = None
            else:
                m = re.search(r"track/(-?\d+)", raw) or re.fullmatch(r"-?\d+", raw)
                if not uri or not m:
                    raise ValueError(f"{path}:{n}: need a source_uri and a Deezer track id, URL or SKIP")
                deezer_id = int(m.group(1) if m.lastindex else m.group(0))
            out.append(Override(uri, deezer_id, (row.get("note") or "").strip()))
    return out


def ensure(path: Path) -> None:
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(",".join(HEADER) + "\n")
