from dataclasses import replace
from pathlib import Path

from .. import match, overrides
from ..model import Resolution, Track
from ..state import State
from . import catalog


def summary(obj: dict) -> dict:
    return {
        "id": obj["id"],
        "title": obj["title"],
        "artist": obj["artist"]["name"],
        "duration": obj["duration"],
        "link": obj.get("link") or f"https://www.deezer.com/track/{obj['id']}",
        "isrc": obj.get("isrc"),
    }


def candidate(obj: dict) -> match.Candidate:
    names = tuple(c["name"] for c in obj.get("contributors", [])) or (obj["artist"]["name"],)
    return match.Candidate(obj["id"], obj["title"], obj.get("title_short") or obj["title"], names, obj["duration"] * 1000)


class Resolver:
    def __init__(self, state: State, country: str, threshold: float, tolerance_ms: int):
        self.state = state
        self.country = country
        self.threshold = threshold
        self.tolerance_ms = tolerance_ms

    def track(self, track_id: int) -> dict:
        obj = self.state.cached_track(track_id)
        if obj is None:
            if track_id < 0:
                raise SystemExit(f"{track_id} is a personal upload the state file does not know; run `s2d uploads`")
            obj = catalog.track(track_id)
            self.state.cache_track(obj)
        return obj

    def resolve(self, t: Track) -> Resolution:
        fallback = None
        if t.isrc:
            hit = catalog.track_by_isrc(t.isrc)
            if hit:
                self.state.cache_track(hit)
                obj, via_alt = self._available(hit)
                if obj:
                    fallback = self._accept(t, obj, "isrc-alt" if via_alt else "isrc")
                    if fallback.status == "matched":
                        return fallback
                else:
                    fallback = Resolution(t.source_uri, "unmatched", None, None, None, summary(hit),
                                          f"ISRC hit unavailable in {self.country}")
        res = self._search(t, fallback)
        if res.status == "matched" and fallback and fallback.status == "needs-review":
            return replace(res, note=f"ISRC hit {fallback.candidate['link']} {fallback.note}; matched by search instead")
        return res

    def _available(self, obj: dict) -> tuple[dict | None, bool]:
        countries = obj.get("available_countries")
        if countries is None or self.country in countries:
            return obj, False
        alt = obj.get("alternative")
        if alt:
            full = self.track(alt["id"])
            if self.country in full.get("available_countries", [self.country]):
                return full, True
        return None, False

    def _accept(self, t: Track, obj: dict, method: str, score: float = 1.0) -> Resolution:
        cand = summary(obj)
        delta = abs(cand["duration"] * 1000 - t.duration_ms) if t.duration_ms else 0
        if method != "search" and delta > 10_000:
            return Resolution(t.source_uri, "needs-review", method, cand["id"], score, cand,
                              f"duration differs by {delta // 1000}s")
        return Resolution(t.source_uri, "matched", method, cand["id"], score, cand, None)

    def _score(self, t: Track, obj: dict) -> match.Score:
        return match.score(t, candidate(obj), self.tolerance_ms)

    def _search(self, t: Track, fallback: Resolution | None) -> Resolution:
        title = match.core(t.title) or match.norm(t.title)
        artist = t.artists[0] if t.artists else ""
        queries = [f"{artist} {title}".strip(), f'artist:"{artist}" track:"{title}"', title, t.title.strip()]
        results, seen = [], set()
        for q in dict.fromkeys(q for q in queries if q):
            for r in catalog.search(q):
                if r["id"] not in seen:
                    seen.add(r["id"])
                    results.append(r)
            if any(self._score(t, r).total >= self.threshold for r in results):
                break
        if t.isrc:
            for r in results:
                if r.get("isrc") == t.isrc:
                    obj, _ = self._available(self.track(r["id"]))
                    if obj:
                        res = self._accept(t, obj, "search-isrc")
                        if res.status == "matched":
                            return res
                        fallback = fallback or res
        best = None
        for r in sorted(results, key=lambda r: self._score(t, r).total, reverse=True)[:3]:
            obj, _ = self._available(self.track(r["id"]))
            if obj is None:
                continue
            sc = self._score(t, obj)
            if best is None or sc.total > best[1].total:
                best = (obj, sc)
        if best and best[1].total >= self.threshold:
            return self._accept(t, best[0], "search", round(best[1].total, 3))
        if fallback:
            if not best:
                return replace(fallback, note=f"{fallback.note}; no search candidates")
            cand, sc = summary(best[0]), best[1]
            if fallback.status == "unmatched":
                return Resolution(t.source_uri, "unmatched", None, None, round(sc.total, 3), cand,
                                  f"{fallback.note}: {fallback.candidate['link']}; best available scored {sc.total:.2f} ({sc})")
            if cand["id"] != fallback.deezer_id:
                return replace(fallback, note=f"{fallback.note}; search best {cand['link']} scored {sc.total:.2f}")
            return replace(fallback, note=f"{fallback.note}; search found the same track")
        if best:
            return Resolution(t.source_uri, "unmatched", None, None, round(best[1].total, 3), summary(best[0]),
                              f"best candidate scored {best[1].total:.2f} ({best[1]})")
        return Resolution(t.source_uri, "unmatched", None, None, None, None, "no search results")


def apply_overrides(state: State, resolver: Resolver, path: Path) -> int:
    n = 0
    for o in overrides.read(path):
        if not state.has_track(o.source_uri):
            print(f"  override for unknown source_uri {o.source_uri} ignored")
            continue
        if o.deezer_id is None:
            res = Resolution(o.source_uri, "skip", "override", None, None, None, o.note)
        else:
            method = "upload" if o.deezer_id < 0 else "override"
            res = Resolution(o.source_uri, "matched", method, o.deezer_id, None,
                             summary(resolver.track(o.deezer_id)), o.note)
        state.upsert_resolution(res)
        n += 1
    return n


def match_uploads(state: State, uploads: list[dict], tolerance_ms: int) -> list[tuple[dict, tuple | None, float]]:
    undecided = state.resolved(("unmatched", "needs-review", "skip"))
    out = []
    for obj in uploads:
        cand = match.Candidate(obj["id"], obj["title"], obj["title"], (obj["artist"]["name"],), obj["duration"] * 1000)
        best, score = None, 0.0
        for pair in undecided:
            total = match.score(pair[0], cand, tolerance_ms).total
            if total > score:
                best, score = pair, total
        out.append((obj, best, round(score, 3)))
    return out


def collapse_duplicates(state: State) -> int:
    first: dict[int, int] = {}
    changes = 0
    for t, r in state.resolved(("matched", "dup-skip")):
        if r.deezer_id not in first:
            first[r.deezer_id] = t.position
            if r.status == "dup-skip":
                state.set_status(t.source_uri, "matched", None)
                changes += 1
        elif r.status != "dup-skip":
            state.set_status(t.source_uri, "dup-skip", f"duplicate of position {first[r.deezer_id]}")
            changes += 1
    return changes
