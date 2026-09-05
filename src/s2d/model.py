from dataclasses import dataclass


@dataclass(frozen=True)
class Track:
    position: int
    source_uri: str
    title: str
    artists: tuple[str, ...]
    album: str
    duration_ms: int | None
    added_at: str | None
    isrc: str | None
    is_local: bool


STATUSES = ("matched", "unmatched", "needs-review", "dup-skip", "skip")


@dataclass(frozen=True)
class Resolution:
    source_uri: str
    status: str
    method: str | None
    deezer_id: int | None
    score: float | None
    candidate: dict | None
    note: str | None
