import random
import time
from datetime import datetime

from ..state import State
from . import catalog
from .web import GwSession


class AddError(Exception):
    pass


def reconcile(state: State, user_id: str, batch: int, allow_existing: bool) -> int:
    favs = {t["id"]: t for t in catalog.user_favourites(user_id)}
    recorded = {r["deezer_id"] for r in state.adds()}
    missing = sorted(recorded - set(favs))
    if missing:
        raise AddError(f"{len(missing)} recorded adds are no longer favourites, e.g. {missing[:5]}")
    extra = sorted(set(favs) - recorded)
    pending = state.pending_adds()
    if len(extra) == 1 and pending and pending[0][1].deezer_id == extra[0]:
        t, r = pending[0]
        state.record_add(t.position, r.deezer_id, batch, _iso(favs[extra[0]]["time_add"]))
        print(f"  adopted position {t.position}: favourited by the previous run but not recorded")
        extra = []
    if extra and not allow_existing:
        raise AddError(
            f"{len(extra)} favourites are not recorded adds, e.g. {extra[:5]}. Remove them or pass --allow-existing."
        )
    return len(favs)


def add_all(
    state: State, gw: GwSession, user_id: str, rows, batch: int, delay_min: float, delay_max: float, total: int
) -> None:
    for i, (t, r) in enumerate(rows, 1):
        gw.add_favourites([r.deezer_id])
        total = _await_total(user_id, total + 1, t.position)
        state.record_add(t.position, r.deezer_id, batch, datetime.now().isoformat(timespec="seconds"))
        print(f"  {i}/{len(rows)} [{t.position}] {r.candidate['artist']} - {r.candidate['title']}")
        if i < len(rows):
            time.sleep(random.uniform(delay_min, delay_max))


def _await_total(user_id: str, want: int, position: int, timeout_s: float = 15) -> int:
    deadline = time.monotonic() + timeout_s
    while True:
        total = catalog.favourites_total(user_id)
        if total == want:
            return total
        if total > want:
            raise AddError(f"position {position}: favourite count jumped to {total}, expected {want}")
        if time.monotonic() > deadline:
            raise AddError(f"position {position}: favourite count stayed at {total}, expected {want}")
        time.sleep(1)


def _iso(ts: int) -> str:
    return datetime.fromtimestamp(ts).isoformat(timespec="seconds")
