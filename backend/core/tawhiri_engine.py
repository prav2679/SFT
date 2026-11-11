"""Adapter for the ORIGINAL Tawhiri Engine (tawhiri/api.py Flask application).

The engine is invoked exactly as the preserved Leaflet predictor does it:
HTTP GET {TAWHIRI_API_URL}/api/v1/ with the documented query parameters.
No trajectory mathematics is duplicated here; this module only validates
inputs, checks weather-data availability, calls the engine, and converts the
response into the application's shared trajectory format.

Start the engine as documented in legacy/leaflet_predictor/LOCAL_TAWHIRI_SETUP.md:
    export TAWHIRI_SETTINGS=$PWD/local_settings.py   # sets WIND_DATASET_DIR
    TZ=UTC tawhiri-webapp runserver
TZ=UTC matters: tawhiri/api.py resolves the dataset with
datetime.fromtimestamp(), which uses the server's local timezone.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta

import httpx

import config
from core import weather
from core.db import iso, parse_iso

SHARES_DATA_DIR = os.environ.get("TAWHIRI_ENGINE_SHARES_DATA_DIR", "1") == "1"


class TawhiriEngineError(Exception):
    def __init__(self, message: str, code: str, details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


async def engine_status() -> dict:
    url = f"{config.TAWHIRI_API_URL}/api/datasetcheck"
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            r = await client.get(url)
    except httpx.HTTPError as exc:
        return {"status": "UNREACHABLE", "api_url": config.TAWHIRI_API_URL,
                "message": f"Tawhiri engine not reachable: {exc.__class__.__name__}. Start tawhiri-webapp."}
    try:
        body = r.json()
    except ValueError:
        body = {}
    if r.status_code == 200:
        return {"status": "OK", "api_url": config.TAWHIRI_API_URL,
                "engine_dataset": body.get("request", {}).get("dataset")}
    if r.status_code == 404:
        return {"status": "NO_DATASET", "api_url": config.TAWHIRI_API_URL,
                "message": body.get("error", {}).get("description", "Engine found no dataset")}
    return {"status": "ERROR", "api_url": config.TAWHIRI_API_URL, "http_status": r.status_code,
            "message": str(body)[:300]}


def _rfc3339(dt: datetime) -> str:
    return iso(dt).replace(".000000", "")


async def predict(params: dict) -> dict:
    """Run one Tawhiri prediction. ``params`` keys:
    profile (standard_profile|float_profile|reverse_profile), launch_latitude,
    launch_longitude (-180..180 accepted), launch_altitude, launch_datetime,
    ascent_rate, burst_altitude, descent_rate, float_altitude, stop_datetime,
    forecast_cycle (optional), duration_hours_estimate (for coverage check).
    """
    profile = params.get("profile", "standard_profile")
    launch = parse_iso(params["launch_datetime"])
    lat = float(params["launch_latitude"])
    lon = float(params["launch_longitude"])
    if not -90 <= lat <= 90:
        raise TawhiriEngineError("launch_latitude must be between -90 and 90.", "INVALID_INPUT")
    q = {
        "profile": profile,
        "launch_latitude": lat,
        "launch_longitude": lon % 360.0,                 # engine requires 0 <= lon < 360
        "launch_datetime": _rfc3339(launch),
        "launch_altitude": float(params.get("launch_altitude", 0.0)),
        "ascent_rate": float(params["ascent_rate"]),
        "format": "json",
    }
    if profile == "standard_profile":
        q["burst_altitude"] = float(params["burst_altitude"])
        q["descent_rate"] = float(params["descent_rate"])
        end = launch + timedelta(hours=float(params.get("duration_hours_estimate", 6)))
        start = launch
    elif profile == "float_profile":
        q["float_altitude"] = float(params["float_altitude"])
        stop = parse_iso(params["stop_datetime"])
        q["stop_datetime"] = _rfc3339(stop)
        start, end = launch, stop
    elif profile == "reverse_profile":
        hrs = float(q["launch_altitude"]) / max(q["ascent_rate"], 0.2) / 3600 + 0.5
        start, end = launch - timedelta(hours=hrs), launch
    else:
        raise TawhiriEngineError(f"Unknown profile {profile}", "INVALID_INPUT")

    cycle = None
    if SHARES_DATA_DIR:
        # Validate weather-data availability BEFORE calling the engine so a
        # data problem is reported as such, not as an engine failure.
        try:
            cycle = weather.select_cycle(start, end, params.get("forecast_cycle"))
        except weather.WeatherDataError as exc:
            raise TawhiriEngineError(str(exc), exc.code, exc.details) from exc
        q["dataset"] = _rfc3339(cycle.valid_from)
    elif params.get("forecast_cycle"):
        q["dataset"] = _rfc3339(weather.cycle_to_datetime(params["forecast_cycle"]))

    url = f"{config.TAWHIRI_API_URL}/api/v1/"
    try:
        async with httpx.AsyncClient(timeout=config.TAWHIRI_API_TIMEOUT_S) as client:
            r = await client.get(url, params=q)
    except httpx.HTTPError as exc:
        raise TawhiriEngineError(f"Tawhiri engine unreachable at {config.TAWHIRI_API_URL}: {exc}",
                                 "TAWHIRI_ENGINE_UNAVAILABLE") from exc
    try:
        body = r.json()
    except ValueError as exc:
        raise TawhiriEngineError(f"Engine returned non-JSON (HTTP {r.status_code})", "ENGINE_EXECUTION_FAILED") from exc
    if "error" in body:
        etype = body["error"].get("type", "")
        code = {"RequestException": "INVALID_INPUT",
                "InvalidDatasetException": "WEATHER_DATA_UNAVAILABLE",
                "PredictionException": "ENGINE_EXECUTION_FAILED"}.get(etype, "ENGINE_EXECUTION_FAILED")
        raise TawhiriEngineError(body["error"].get("description", "Tawhiri error"), code, {"engine_error": etype})
    return to_shared(body, profile, cycle.cycle if cycle else None)


def to_shared(body: dict, profile: str, cycle: str | None) -> dict:
    traj = []
    for stage in body.get("prediction", []):
        for p in stage["trajectory"]:
            traj.append({"t": p["datetime"], "lat": p["latitude"],
                         "lon": (p["longitude"] + 180.0) % 360.0 - 180.0, "alt": p["altitude"],
                         "phase": stage["stage"]})
    # Vertical velocity derived from consecutive engine output points.
    for a, b in zip(traj, traj[1:]):
        dt = (parse_iso(b["t"]) - parse_iso(a["t"])).total_seconds()
        if dt:
            b["vz"] = (b["alt"] - a["alt"]) / dt
    out = {
        "model": "tawhiri",
        "model_version": "Tawhiri engine (preserved, temperature-enabled build) - " + profile,
        "profile": profile,
        "forecast_cycle": cycle,
        "engine_dataset": body.get("request", {}).get("dataset"),
        "engine_request": body.get("request"),
        "engine_warnings": body.get("warnings"),
        "engine_metadata": body.get("metadata"),
        "atmosphere_source": "Tawhiri wind interpolation (FORECAST); descent rate scaled by engine's density model.",
        "trajectory": traj,
    }
    if "launch_estimate" in body:
        le = dict(body["launch_estimate"])
        le["longitude"] = (le["longitude"] + 180.0) % 360.0 - 180.0
        # tawhiri/api.py echoes the *request* datetime here; the estimated
        # launch time is the final point of the backward-integrated trajectory.
        le["engine_reported_datetime"] = le.pop("datetime", None)
        le["datetime"] = traj[-1]["t"] if traj else None
        out["launch_estimate"] = le
    return out
