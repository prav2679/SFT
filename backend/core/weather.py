"""Weather-data availability and validation for Tawhiri CUSF binary datasets.

Datasets are files named exactly YYYYMMDDHH in TAWHIRI_DATA_DIR (no
extension). The temperature-enabled engine/downloader use the 4-variable
layout (65, 47, 4, 361, 720) float32 = 12,704,889,600 bytes. A 3-variable
legacy file is reported as INCOMPATIBLE, never silently used.

Validity window: [cycle, cycle + 192 h) - the upper bound is exclusive
(V4 Stage 6: 191.99 h worked, 192 h failed).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import config
from core.db import iso


class WeatherDataError(Exception):
    """Raised when required weather data is missing/invalid. Never ignored."""

    def __init__(self, message: str, code: str = "WEATHER_DATA_UNAVAILABLE", details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


@dataclass
class DatasetInfo:
    cycle: str
    path: Path
    size: int
    status: str            # VALID | INCOMPLETE | INCOMPATIBLE_3VAR | UNKNOWN_SIZE
    valid_from: datetime
    valid_to: datetime     # exclusive

    def as_dict(self) -> dict:
        return {
            "cycle": self.cycle, "path": str(self.path), "size_bytes": self.size, "status": self.status,
            "expected_size_bytes": config.DATASET_SIZE_BYTES,
            "valid_from_utc": iso(self.valid_from), "valid_to_utc_exclusive": iso(self.valid_to),
            "usable": self.status == "VALID",
        }


def cycle_to_datetime(cycle: str) -> datetime:
    return datetime.strptime(cycle, "%Y%m%d%H").replace(tzinfo=timezone.utc)


def list_datasets(data_dir: Path | None = None) -> list[DatasetInfo]:
    d = Path(data_dir or config.TAWHIRI_DATA_DIR)
    out: list[DatasetInfo] = []
    if not d.exists():
        return out
    for p in sorted(d.iterdir()):
        if not (p.is_file() and len(p.name) == 10 and p.name.isdigit()):
            continue
        try:
            start = cycle_to_datetime(p.name)
        except ValueError:
            continue
        size = p.stat().st_size
        if size == config.DATASET_SIZE_BYTES:
            status = "VALID"
        elif size == config.LEGACY_3VAR_SIZE_BYTES:
            status = "INCOMPATIBLE_3VAR"
        elif size < config.DATASET_SIZE_BYTES:
            status = "INCOMPLETE"
        else:
            status = "UNKNOWN_SIZE"
        out.append(DatasetInfo(p.name, p, size, status, start,
                               start + timedelta(hours=config.DATASET_MAX_LEAD_HOURS)))
    return out


def in_progress_downloads(data_dir: Path | None = None) -> list[str]:
    d = Path(data_dir or config.TAWHIRI_DATA_DIR)
    if not d.exists():
        return []
    return sorted(p.name for p in d.iterdir() if p.name.startswith("download-"))


def status() -> dict:
    sets = list_datasets()
    usable = [s for s in sets if s.status == "VALID"]
    now = datetime.now(timezone.utc)
    current = [s for s in usable if s.valid_from <= now < s.valid_to]
    if not config.TAWHIRI_DATA_DIR.exists():
        overall = "DATA_DIR_MISSING"
    elif not usable:
        overall = "NO_VALID_DATA"
    elif current:
        overall = "AVAILABLE"
    else:
        overall = "STALE"            # valid files exist but none cover 'now'
    return {
        "overall": overall,
        "data_dir": str(config.TAWHIRI_DATA_DIR),
        "datasets": [s.as_dict() for s in sets],
        "latest_valid_cycle": usable[-1].cycle if usable else None,
        "covers_now": [s.cycle for s in current],
        "downloads_in_progress": in_progress_downloads(),
        "layout": {"shape": config.DATASET_SHAPE, "variables": ["height", "wind_u", "wind_v", "temperature"],
                   "pressure_levels": 47, "grid": "global 0.5 deg", "forecast_hours": "0-192 every 3 h"},
    }


def select_cycle(start: datetime, end: datetime, requested: str | None = None) -> DatasetInfo:
    """Pick a VALID dataset covering [start, end]. Raises WeatherDataError.

    If ``requested`` is given it must exist, be valid and cover the window.
    Otherwise the most recent covering cycle is chosen.
    """
    sets = list_datasets()
    if requested:
        match = next((s for s in sets if s.cycle == requested), None)
        if match is None:
            raise WeatherDataError(f"Forecast cycle {requested} is not present in {config.TAWHIRI_DATA_DIR}.",
                                   details={"requested_cycle": requested})
        candidates = [match]
    else:
        candidates = list(reversed(sets))
    problems = []
    for s in candidates:
        if s.status != "VALID":
            problems.append(f"{s.cycle}: {s.status} ({s.size:,} bytes)")
            continue
        if start < s.valid_from or end >= s.valid_to:
            problems.append(f"{s.cycle}: covers {iso(s.valid_from)} to {iso(s.valid_to)} (exclusive)")
            continue
        return s
    raise WeatherDataError(
        f"No valid Tawhiri dataset covers {iso(start)} to {iso(end)}. "
        "Download the appropriate forecast cycle before running this simulation.",
        details={"window_start": iso(start), "window_end": iso(end), "checked": problems,
                 "data_dir": str(config.TAWHIRI_DATA_DIR)},
    )


def worker_env(cycle: DatasetInfo) -> dict:
    env = dict(os.environ)
    env["TAWHIRI_DATA_DIR"] = str(config.TAWHIRI_DATA_DIR)
    env["TAWHIRI_CYCLE"] = cycle.cycle
    env["TAWHIRI_ENGINE_DIR"] = str(config.TAWHIRI_ENGINE_DIR)
    env["PYTHONUNBUFFERED"] = "1"
    env["MPLBACKEND"] = "Agg"
    return env
