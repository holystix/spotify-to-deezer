import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Self

from .model import Resolution, Track

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tracks (
  position INTEGER PRIMARY KEY,
  source_uri TEXT NOT NULL UNIQUE,
  title TEXT NOT NULL,
  artists_json TEXT NOT NULL,
  album TEXT NOT NULL,
  duration_ms INTEGER,
  added_at TEXT,
  isrc TEXT,
  is_local INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS resolutions (
  source_uri TEXT PRIMARY KEY,
  status TEXT NOT NULL,
  method TEXT,
  deezer_id INTEGER,
  score REAL,
  candidate_json TEXT,
  note TEXT,
  resolved_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS deezer_tracks (
  id INTEGER PRIMARY KEY,
  json TEXT NOT NULL,
  fetched_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS adds (
  position INTEGER PRIMARY KEY REFERENCES tracks(position),
  deezer_id INTEGER NOT NULL,
  batch INTEGER NOT NULL,
  added_at TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _track(r: sqlite3.Row) -> Track:
    return Track(
        r["position"],
        r["source_uri"],
        r["title"],
        tuple(json.loads(r["artists_json"])),
        r["album"],
        r["duration_ms"],
        r["added_at"],
        r["isrc"],
        bool(r["is_local"]),
    )


def _resolution(r: sqlite3.Row) -> Resolution:
    return Resolution(
        r["source_uri"],
        r["status"],
        r["method"],
        r["deezer_id"],
        r["score"],
        json.loads(r["candidate_json"]) if r["candidate_json"] else None,
        r["note"],
    )


class State:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.db.close()

    def get_meta(self, key: str) -> str | None:
        row = self.db.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def set_meta(self, key: str, value: str) -> None:
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, value))

    def count(self, table: str) -> int:
        return self.db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]

    def replace_tracks(self, tracks: list[Track]) -> None:
        with self.db:
            self.db.execute("DELETE FROM tracks")
            self.db.executemany(
                "INSERT INTO tracks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        t.position,
                        t.source_uri,
                        t.title,
                        json.dumps(list(t.artists)),
                        t.album,
                        t.duration_ms,
                        t.added_at,
                        t.isrc,
                        int(t.is_local),
                    )
                    for t in tracks
                ],
            )

    def tracks(self) -> list[Track]:
        return [_track(r) for r in self.db.execute("SELECT * FROM tracks ORDER BY position")]

    def has_track(self, source_uri: str) -> bool:
        return self.db.execute("SELECT 1 FROM tracks WHERE source_uri = ?", (source_uri,)).fetchone() is not None

    def pending_tracks(self, retry: bool) -> list[Track]:
        statuses = ("unmatched", "needs-review") if retry else ()
        rows = self.db.execute(
            "SELECT t.* FROM tracks t LEFT JOIN resolutions r ON r.source_uri = t.source_uri "
            "WHERE r.source_uri IS NULL OR r.status IN (?, ?) ORDER BY t.position",
            statuses or ("", ""),
        )
        return [_track(r) for r in rows]

    def upsert_resolution(self, res: Resolution) -> None:
        with self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO resolutions VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    res.source_uri,
                    res.status,
                    res.method,
                    res.deezer_id,
                    res.score,
                    json.dumps(res.candidate) if res.candidate else None,
                    res.note,
                    _now(),
                ),
            )

    def set_status(self, source_uri: str, status: str, note: str | None) -> None:
        with self.db:
            self.db.execute(
                "UPDATE resolutions SET status = ?, note = ?, resolved_at = ? WHERE source_uri = ?",
                (status, note, _now(), source_uri),
            )

    def resolved(self, statuses: tuple[str, ...] = ()) -> list[tuple[Track, Resolution]]:
        where = f"WHERE r.status IN ({','.join('?' * len(statuses))})" if statuses else ""
        rows = self.db.execute(
            "SELECT t.*, r.status, r.method, r.deezer_id, r.score, r.candidate_json, r.note "
            f"FROM tracks t JOIN resolutions r ON r.source_uri = t.source_uri {where} ORDER BY t.position",
            statuses,
        )
        return [(_track(r), _resolution(r)) for r in rows]

    def resolution_counts(self) -> list[tuple[str, str | None, int]]:
        rows = self.db.execute(
            "SELECT r.status, r.method, COUNT(*) FROM resolutions r JOIN tracks t ON t.source_uri = r.source_uri "
            "GROUP BY r.status, r.method ORDER BY r.status, r.method"
        )
        return [tuple(r) for r in rows]

    def pending_adds(self) -> list[tuple[Track, Resolution]]:
        rows = self.db.execute(
            "SELECT t.*, r.status, r.method, r.deezer_id, r.score, r.candidate_json, r.note "
            "FROM tracks t JOIN resolutions r ON r.source_uri = t.source_uri "
            "LEFT JOIN adds a ON a.position = t.position "
            "WHERE r.status = 'matched' AND a.position IS NULL ORDER BY t.position"
        )
        return [(_track(r), _resolution(r)) for r in rows]

    def blocking(self, upto: int) -> list[tuple[Track, str]]:
        rows = self.db.execute(
            "SELECT t.*, r.status FROM tracks t LEFT JOIN resolutions r ON r.source_uri = t.source_uri "
            "WHERE t.position <= ? AND (r.status IS NULL OR r.status IN ('unmatched', 'needs-review')) "
            "ORDER BY t.position",
            (upto,),
        )
        return [(_track(r), r["status"] or "unresolved") for r in rows]

    def adds(self) -> list[sqlite3.Row]:
        return self.db.execute("SELECT * FROM adds ORDER BY position").fetchall()

    def record_add(self, position: int, deezer_id: int, batch: int, added_at: str) -> None:
        with self.db:
            self.db.execute("INSERT INTO adds VALUES (?, ?, ?, ?)", (position, deezer_id, batch, added_at))

    def clear_adds(self) -> int:
        with self.db:
            return self.db.execute("DELETE FROM adds").rowcount

    def reset_duplicates(self) -> None:
        with self.db:
            self.db.execute("UPDATE resolutions SET status = 'matched', note = NULL WHERE status = 'dup-skip'")

    def next_batch(self) -> int:
        return self.db.execute("SELECT COALESCE(MAX(batch), 0) + 1 FROM adds").fetchone()[0]

    def cached_track(self, track_id: int) -> dict | None:
        row = self.db.execute("SELECT json FROM deezer_tracks WHERE id = ?", (track_id,)).fetchone()
        return json.loads(row["json"]) if row else None

    def cache_track(self, obj: dict) -> None:
        with self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO deezer_tracks VALUES (?, ?, ?)", (obj["id"], json.dumps(obj), _now())
            )
