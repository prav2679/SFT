"""Telemetry-triggered re-forecast orchestration.

The observed telemetry state becomes the initial condition of the existing SFT models (see
workers/telemetry_reforecast_worker.py). The original prediction (V1) is never touched; each completed job
appends a REVISED prediction version. Jobs run in background worker processes - callers never wait for them.
"""
from __future__ import annotations

import asyncio
import json
from datetime import timedelta

from core import db, predictions, weather
from core.db import iso, parse_iso
from core.tasks import get_manager
from core.telemetry import detect_phase, hub

FLIGHT_PHASES = ("ASCENT", "FLOAT", "DESCENT")


class ReforecastError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code = status, code


def validate_phase_vs_velocity(phase: str, vz: float | None) -> None:
    """Reject physically contradictory phase / vertical-velocity combinations (never silently coerce)."""
    if vz is None:
        if phase == "DESCENT":
            raise ReforecastError(422, "INVALID_INPUT", "vertical velocity is required for a DESCENT re-forecast")
        return
    if phase == "ASCENT" and vz < -1.0:
        raise ReforecastError(422, "INVALID_INPUT", f"Phase ASCENT contradicts vertical velocity {vz:+.2f} m/s (sinking).")
    if phase == "DESCENT" and vz > 1.0:
        raise ReforecastError(422, "INVALID_INPUT", f"Phase DESCENT contradicts vertical velocity {vz:+.2f} m/s (climbing).")
    if phase == "FLOAT" and abs(vz) > 2.0:
        raise ReforecastError(422, "INVALID_INPUT", f"Phase FLOAT contradicts vertical velocity {vz:+.2f} m/s (|vz| > 2 m/s).")


def resolve_context(mission_id: str, baseline_simulation_id: str | None = None) -> dict:
    orig = predictions.original_set(mission_id)
    if not orig:
        raise ReforecastError(409, "NO_ORIGINAL_PREDICTION",
                              "This mission has no original prediction. Attach a burst-calculator or forward-trajectory "
                              "result as the mission prediction before re-forecasting.")
    sim_id = baseline_simulation_id or json.loads(orig["metadata_json"] or "{}").get("simulation_id")
    if not sim_id:
        raise ReforecastError(409, "REFORECAST_CONTEXT_MISSING",
                              "The original prediction does not record which model run produced it (e.g. recorded "
                              "output). Pass baseline_simulation_id (a completed burst or forward job with the "
                              "mission's parameters) to re-forecast.")
    row = db.query_one("SELECT kind, request_json FROM simulations WHERE simulation_id=?", (sim_id,))
    if not row or row["kind"] not in ("burst", "forward"):
        raise ReforecastError(409, "REFORECAST_CONTEXT_MISSING", f"Simulation {sim_id} is not a burst or forward job.")
    req = json.loads(row["request_json"])
    return {"model": row["kind"], "parameters": req["parameters"], "simulation_id": sim_id,
            "forecast_cycle": req.get("forecast_cycle"), "original": orig}


def _store_version(task, result: dict, ctx: dict) -> dict:
    mission_id, anchor = ctx["mission_id"], ctx["anchor"]
    latest = db.query_one("SELECT prediction_set FROM prediction_sets WHERE mission_id=? ORDER BY version DESC LIMIT 1",
                          (mission_id,))
    set_id = predictions.store_prediction(
        mission_id, result["trajectory"], kind="REVISED",
        source=f"Telemetry re-forecast ({result['phase']}) from {anchor['timestamp_utc']}",
        model_version=result.get("model_version"), forecast_cycle=result.get("forecast_cycle"),
        parent_set=latest["prediction_set"] if latest else None, anchor_telemetry_id=anchor["telemetry_id"],
        anchor_timestamp=anchor["timestamp_utc"], anchor_phase=result["phase"],
        metadata={"simulation_id": task.id, "engine": result.get("engine"), "warnings": result.get("warnings"),
                  "baseline_simulation_id": ctx["baseline_simulation_id"], "mission_model": result.get("mission_model"),
                  "ascent_rate_used_mps": result.get("ascent_rate_used_mps"),
                  "remaining_duration_s": result.get("remaining_duration_s")})
    version = db.query_one("SELECT version FROM prediction_sets WHERE prediction_set=?", (set_id,))["version"]
    hub.reload(mission_id)
    try:
        asyncio.get_running_loop().create_task(hub.broadcast(
            mission_id, {"type": "prediction_version", "prediction_set": set_id, "version": version}))
    except RuntimeError:
        pass
    return {"prediction_set": set_id, "version": version}


def submit(mission_id: str, telemetry_id: int | None = None, phase: str | None = None,
           baseline_simulation_id: str | None = None, float_end_datetime: str | None = None,
           hold_duration_hours: float | None = None, use_measured_ascent_rate: bool = True,
           forecast_cycle: str | None = None) -> dict:
    where, params = ("telemetry_id=?", (telemetry_id,)) if telemetry_id else (
        "quality IN ('VALID','DEGRADED') AND superseded_by IS NULL AND latitude IS NOT NULL AND gps_altitude IS NOT NULL "
        "AND quality_flags NOT LIKE '%OUT_OF_ORDER%' ORDER BY timestamp_utc DESC LIMIT 1", ())
    row = db.query_one(f"SELECT * FROM telemetry WHERE mission_id=? AND {where}", (mission_id, *params))
    if not row:
        raise ReforecastError(409, "NO_TELEMETRY", "No valid telemetry position is available to re-forecast from.")
    if row["superseded_by"] is not None or row["quality"] not in ("VALID", "DEGRADED") or row["latitude"] is None \
            or row["gps_altitude"] is None or "OUT_OF_ORDER" in (row["quality_flags"] or ""):
        raise ReforecastError(409, "TELEMETRY_NOT_USABLE",
                              "That telemetry record is invalid, out of order, superseded or has no position.")
    later = db.query_one("SELECT 1 FROM telemetry WHERE mission_id=? AND timestamp_utc>? AND quality IN ('VALID','DEGRADED') "
                         "AND superseded_by IS NULL", (mission_id, row["timestamp_utc"]))
    existing = db.query_one("SELECT prediction_set, version FROM prediction_sets WHERE mission_id=? AND kind='REVISED' "
                            "AND anchor_telemetry_id=?", (mission_id, row["telemetry_id"]))
    if existing:
        return {"submitted": False, "reason": "A revised prediction already exists for this telemetry record.",
                "prediction_set": existing["prediction_set"], "version": existing["version"]}
    st = hub.state(mission_id)
    vz = row["vertical_velocity"]
    if phase in (None, "", "AUTO"):
        det = detect_phase(vz, row["gps_altitude"], st.launch_alt, st.phase, st.max_alt)
        phase = det["phase"] or (st.phase if st.phase in FLIGHT_PHASES else None)
        if not phase:
            raise ReforecastError(422, "PHASE_UNDETERMINED", det["reason"])
    phase = phase.upper()
    if phase not in FLIGHT_PHASES:
        raise ReforecastError(422, "INVALID_INPUT", f"Cannot re-forecast from phase {phase}.")
    validate_phase_vs_velocity(phase, vz)
    ctx = resolve_context(mission_id, baseline_simulation_id)
    model, params, orig = ctx["model"], ctx["parameters"], ctx["original"]
    base_track = predictions.track(orig["prediction_set"], max_points=100000)
    t_tel = parse_iso(row["timestamp_utc"])
    if phase == "ASCENT" and model == "burst" and row["gps_altitude"] >= float(params["burst_altitude"]):
        raise ReforecastError(422, "INVALID_INPUT", "Observed altitude is at/above the commanded burst altitude; "
                                                    "this is not an ASCENT state of the planned flight.")
    hold = [p for p in base_track if p["phase"] == "altitude_hold"]
    float_end = float_end_datetime or (hold[-1]["t"] if hold else None)
    if phase == "FLOAT" and not float_end:
        raise ReforecastError(422, "FLOAT_END_REQUIRED",
                              "Planned end of float is unknown (the original prediction has no altitude hold). "
                              "Provide float_end_datetime.")
    end = max(parse_iso(base_track[-1]["t"]), t_tel, parse_iso(float_end) if float_end else t_tel) + timedelta(hours=3)
    start = parse_iso(params["launch_datetime"]) if (phase == "ASCENT" and model == "burst") else t_tel
    start = min(start, t_tel)
    cycle = weather.select_cycle(start, end, forecast_cycle or orig.get("forecast_cycle") or ctx["forecast_cycle"])
    tel = {"datetime_utc": row["timestamp_utc"], "latitude": row["latitude"], "longitude": row["longitude"],
           "altitude_m": row["gps_altitude"], "vertical_velocity_mps": vz, "phase": phase,
           "ground_speed": row["ground_speed"]}
    request = {"mission_id": mission_id, "model": model, "parameters": params, "telemetry": tel,
               "baseline_trajectory": base_track, "float_end_datetime": float_end,
               "hold_duration_hours": hold_duration_hours, "use_measured_ascent_rate": use_measured_ascent_rate,
               "forecast_cycle": cycle.cycle}
    cctx = {"mission_id": mission_id, "baseline_simulation_id": ctx["simulation_id"],
            "anchor": {"telemetry_id": row["telemetry_id"], "timestamp_utc": row["timestamp_utc"]}}
    job = get_manager().submit_worker("reforecast", "telemetry_reforecast_worker.py", request, weather.worker_env(cycle),
                                      mission_id=mission_id, on_complete=lambda t, r: _store_version(t, r, cctx))
    return {"submitted": True, "phase": phase, "telemetry_id": row["telemetry_id"],
            "superseded_newer_telemetry_exists": bool(later), "job": job}
