import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from ..state import State
from . import catalog

FIELDS = ("position", "deezer_id", "batch", "time_add", "time_add_iso", "issue")


@dataclass
class Report:
    rows: list[dict]
    issues: list[str]

    @property
    def ok(self) -> bool:
        return not self.issues


def check(state: State, user_id: str) -> Report:
    time_add = {t["id"]: t["time_add"] for t in catalog.user_favourites(user_id)}
    adds = state.adds()
    rows, issues, prev = [], [], None
    for a in adds:
        ts = time_add.get(a["deezer_id"])
        issue = ""
        if ts is None:
            issue = "missing from favourites"
        elif prev is not None and ts <= prev:
            issue = f"time_add {ts} not after previous {prev}"
        rows.append(
            {
                "position": a["position"],
                "deezer_id": a["deezer_id"],
                "batch": a["batch"],
                "time_add": ts,
                "time_add_iso": datetime.fromtimestamp(ts).isoformat(timespec="seconds") if ts else "",
                "issue": issue,
            }
        )
        if issue:
            issues.append(f"position {a['position']}: {issue}")
        if ts is not None:
            prev = ts
    extra = sorted(set(time_add) - {a["deezer_id"] for a in adds})
    if extra:
        issues.append(f"{len(extra)} favourites not recorded as adds, e.g. {extra[:5]}")
    return Report(rows, issues)


def write(report: Report, path: Path) -> None:
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(report.rows)
