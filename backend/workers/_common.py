"""Shared plumbing for model worker processes.

Workers run ONE preserved SFT model in an isolated interpreter:
  python <worker>.py <job_dir>
The job directory contains request.json. The worker writes:
  progress.json  (periodic progress snapshots)
  model.log      (everything the original model prints)
  result.json    (on success)   |   error.json (on failure)

Isolation matters: the burst-calculator package and the forward/reverse
package both contain modules named ascent_model_time_dependent.py,
wind_model_time_dependent.py, etc. with DIFFERENT contents. Running each in
its own process guarantees the correct original module is imported.

Workers never modify the original model source. Where progress reporting is
needed, the module-level ``get_wind`` reference is wrapped at runtime by a
pass-through that records (time, altitude) and returns the original value
unchanged.
"""
from __future__ import annotations

import contextlib
import json
import math
import os
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

WORKERS_DIR = Path(__file__).resolve().parent
BACKEND_DIR = WORKERS_DIR.parent


class Job:
    def __init__(self, job_dir: str):
        self.dir = Path(job_dir)
        self.request = json.loads((self.dir / "request.json").read_text(encoding="utf-8"))
        self._last_progress = 0.0
        self.log_path = self.dir / "model.log"

    def progress(self, fraction: float | None, message: str, force: bool = False, **extra):
        now = time.monotonic()
        if not force and now - self._last_progress < 0.5:
            return
        self._last_progress = now
        payload = {"fraction": None if fraction is None else max(0.0, min(1.0, float(fraction))),
                   "message": message, "updated_utc": datetime.now(timezone.utc).isoformat(), **extra}
        tmp = self.dir / "progress.json.tmp"
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        tmp.replace(self.dir / "progress.json")

    def write_result(self, result: dict):
        tmp = self.dir / "result.json.tmp"
        tmp.write_text(json.dumps(sanitize(result), default=str), encoding="utf-8")
        tmp.replace(self.dir / "result.json")

    def write_error(self, exc: BaseException):
        kind = "WEATHER_DATA_UNAVAILABLE" if isinstance(exc, FileNotFoundError) else (
            "TAWHIRI_ENGINE_UNAVAILABLE" if isinstance(exc, ImportError) else (
                "INVALID_INPUT" if isinstance(exc, (ValueError, TypeError)) else "MODEL_ERROR"))
        (self.dir / "error.json").write_text(json.dumps({
            "error_type": kind,
            "exception": type(exc).__name__,
            "message": str(exc),
            "traceback": traceback.format_exc(),
        }), encoding="utf-8")


def sanitize(obj):
    """Replace NaN/Inf with None so results are valid JSON."""
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [sanitize(v) for v in obj]
    if isinstance(obj, datetime):
        return obj.isoformat()
    return obj


def prepare_paths(model_dir: Path):
    """Make the selected original model package importable (first on path)."""
    sys.path.insert(0, str(model_dir))
    engine_dir = os.environ.get("TAWHIRI_ENGINE_DIR")
    if engine_dir and os.environ.get("SFT_ADD_ENGINE_TO_PYTHONPATH", "1") == "1":
        # Appended, so an engine installed into the venv takes precedence.
        sys.path.append(engine_dir)


def wrap_get_wind(modules, job: Job, progress_fn):
    """Wrap ``get_wind`` references held by imported model modules.

    The wrapper is a pure pass-through (identical arguments and return
    value); it only reports progress.
    """
    originals = {}
    for mod in modules:
        if hasattr(mod, "get_wind"):
            original = mod.get_wind
            originals[mod] = original

            def make(orig):
                def wrapped(latitude, longitude, altitude_m, simulation_time):
                    value = orig(latitude, longitude, altitude_m, simulation_time)
                    try:
                        progress_fn(float(altitude_m), simulation_time)
                    except Exception:
                        pass
                    return value
                return wrapped
            mod.get_wind = make(original)
    return originals


def run(main_fn):
    job = Job(sys.argv[1])
    job.progress(0.0, "Starting model worker", force=True)
    with open(job.log_path, "a", encoding="utf-8") as log, contextlib.redirect_stdout(log):
        try:
            result = main_fn(job)
            job.write_result(result)
            job.progress(1.0, "Completed", force=True)
            code = 0
        except BaseException as exc:  # noqa: BLE001 - report every failure
            traceback.print_exc(file=log)
            job.write_error(exc)
            job.progress(None, f"Failed: {exc}", force=True)
            code = 1
    sys.exit(code)


def as_utc(value) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def norm_lon(lon: float) -> float:
    return (float(lon) + 180.0) % 360.0 - 180.0


def normalise_point(p: dict, default_phase: str | None = None) -> dict:
    """Map an SFT model state dict to the shared trajectory point format."""
    out = {
        "t": p.get("datetime_utc"),
        "lat": p.get("latitude"),
        "lon": norm_lon(p["longitude"]) if p.get("longitude") is not None else None,
        "alt": p.get("altitude_m"),
        "phase": p.get("phase") or default_phase,
    }
    mapping = {
        "wind_u": "wind_u", "wind_v": "wind_v", "wind_speed": "wind_speed",
        "temperature_C": "temperature_c", "pressure_hpa": "pressure_hpa",
        "air_density": "air_density", "volume_m3": "volume_m3", "diameter_m": "diameter_m",
        "ascent_rate": "ascent_rate", "vertical_velocity_mps": "descent_velocity",
        "terminal_velocity_mps": "terminal_velocity", "flight_time_s": "flight_time_s",
    }
    for src, dst in mapping.items():
        if p.get(src) is not None:
            out[dst] = p[src]
    return out
