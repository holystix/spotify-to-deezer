import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Config:
    data_dir: Path
    deezer_country: str
    deezer_user_id: str | None
    add_delay_min: float
    add_delay_max: float
    batch_size: int
    browser_channel: str | None
    headless: bool
    match_threshold: float
    duration_tolerance_ms: int

    @property
    def browser_profile(self) -> Path:
        return self.data_dir / "browser-profile"

    @property
    def reports_dir(self) -> Path:
        return self.data_dir / "reports"

    @property
    def export_dir(self) -> Path:
        return self.data_dir / "export"

    @property
    def state_path(self) -> Path:
        return self.data_dir / "state.sqlite"

    @property
    def overrides_path(self) -> Path:
        return self.data_dir / "overrides.csv"


def load() -> Config:
    load_dotenv()
    country = os.environ.get("DEEZER_COUNTRY", "").strip().upper()
    if len(country) != 2:
        raise SystemExit("DEEZER_COUNTRY must be a two-letter code; see .env.example")
    return Config(
        data_dir=Path(os.environ.get("DATA_DIR", "data")),
        deezer_country=country,
        deezer_user_id=os.environ.get("DEEZER_USER_ID") or None,
        add_delay_min=float(os.environ.get("ADD_DELAY_MIN", "2.0")),
        add_delay_max=float(os.environ.get("ADD_DELAY_MAX", "3.0")),
        batch_size=int(os.environ.get("BATCH_SIZE", "100")),
        browser_channel=os.environ.get("BROWSER_CHANNEL", "chrome") or None,
        headless=os.environ.get("HEADLESS", "false").lower() in ("1", "true", "yes"),
        match_threshold=float(os.environ.get("MATCH_THRESHOLD", "0.85")),
        duration_tolerance_ms=int(os.environ.get("DURATION_TOLERANCE_MS", "3000")),
    )
