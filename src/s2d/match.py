import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher

from .model import Track

VERSION_WORDS = {
    "live",
    "remix",
    "acoustic",
    "instrumental",
    "demo",
    "edit",
    "mix",
    "version",
    "cover",
    "karaoke",
    "sped",
    "slowed",
    "reprise",
    "unplugged",
    "session",
    "sessions",
    "dub",
    "rework",
    "bootleg",
    "extended",
    "radio",
    "mono",
    "stereo",
}
# Remasters and "Original Mix" are the standard recording, not a version.
NEUTRAL = re.compile(r"\b(original mix|album version|(\d{4} )?remaster(ed)?( \d{4})?)\b")


@dataclass(frozen=True)
class Candidate:
    id: int
    title: str
    title_short: str
    artists: tuple[str, ...]
    duration_ms: int


@dataclass(frozen=True)
class Score:
    total: float
    title: float
    artist: float
    duration: float

    def __str__(self) -> str:
        return f"title {self.title:.2f} artist {self.artist:.2f} duration {self.duration:.2f}"


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower().replace("&", " and ")
    s = re.sub(r"[’'`]", "", s)
    return re.sub(r"[\W_]+", " ", s).strip()


def core(title: str) -> str:
    t = re.sub(r"[\(\[][^\)\]]*[\)\]]", " ", title)
    t = re.split(r"\s+-\s+", t)[0]
    return norm(t)


def versions(title: str) -> set[str]:
    return {w for w in NEUTRAL.sub(" ", norm(title)).split() if w in VERSION_WORDS}


def ratio(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio() if a and b else 0.0


def title_score(a: str, b: Candidate) -> float:
    s = max(ratio(norm(a), norm(b.title)), ratio(core(a), core(b.title_short or b.title)))
    if versions(a) != versions(b.title):
        s = min(s, 0.6)
    return s


def artist_score(spotify: tuple[str, ...], deezer: tuple[str, ...]) -> float:
    if not spotify or not deezer:
        return 0.0
    names = [norm(d) for d in deezer]

    def best(a: str) -> float:
        return max(ratio(norm(a), d) for d in names)

    coverage = sum(best(a) >= 0.8 for a in spotify) / len(spotify)
    return 0.7 * best(spotify[0]) + 0.3 * coverage


def duration_score(a_ms: int | None, b_ms: int, tolerance_ms: int) -> float:
    if a_ms is None:
        return 0.5
    delta = abs(a_ms - b_ms)
    return 1.0 if delta <= tolerance_ms else 0.5 if delta <= 10_000 else 0.0


def score(track: Track, cand: Candidate, tolerance_ms: int) -> Score:
    t = title_score(track.title, cand)
    a = artist_score(track.artists, cand.artists)
    d = duration_score(track.duration_ms, cand.duration_ms, tolerance_ms)
    return Score(0.5 * t + 0.3 * a + 0.2 * d, t, a, d)
