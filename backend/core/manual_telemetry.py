"""Manual telemetry update (operator-entered observed state) -> validation -> storage -> re-forecast job."""
from __future__ import annotations

import math
import uuid

from core import db, reforecast
from core.db import iso, parse_iso
from core.telemetry import ALTITUDE_MAX_M, ALTITUDE_MIN_M, detect_phase, hub

PHASES = ("ASCENT", "FLOAT", "DESCENT", "LANDED")


class ManualRejected(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code = status, code


def _num(v, name, lo=None, hi=None, required=True):
    if v is None or v == "":
        if required:
            raise ManualRejected(422, "INVALID_INPUT", f"{name} is required")
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise ManualRejected(422, "INVALID_INPUT", f"{name} must be a number")
    if not math.isfinite(f):
        raise ManualRejected(422, "INVALID_INPUT", f"{name} must be finite")
    if lo is not None and f < lo or hi is not None and f > hi:
        raise ManualRejected(422, "INVALID_INPUT", f"{name} {f:g} is outside the valid range {lo:g} to {hi:g}")
    return f


def preview_phase(mission_id: str, vertical_velocity, altitude) -> dict:
    st = hub.state(mission_id)
    vz = _num(vertical_velocity, "vertical_velocity", required=False)
    alt = _num(altitude, "altitude", required=False)
    return detect_phase(vz, alt, st.launch_alt, st.phase, st.max_alt)


async def submit(mission_id: str, e: dict) -> dict:
    st = hub.state(mission_id)                      # KeyError -> 404 in the route
    cfg = st.config
    try:
        ts = parse_iso(e.get("timestamp_utc"))
    except (TypeError, ValueError):
        raise ManualRejected(422, "BAD_TIMESTAMP", "Invalid timestamp (ISO-8601 date and time required)")
    lat = _num(e.get("latitude"), "latitude", -90, 90)
    lon = _num(e.get("longitude"), "longitude", -180, 180)
    alt = _num(e.get("altitude_m"), "altitude", ALTITUDE_MIN_M, ALTITUDE_MAX_M)
    vmax = float(cfg["thresholds"]["max_vertical_speed_ms"])
    vz = _num(e.get("vertical_velocity"), "vertical velocity", -vmax, vmax)
    hv = _num(e.get("horizontal_velocity"), "horizontal velocity", 0, float(cfg["thresholds"]["max_horizontal_speed_ms"]), False)
    ws = _num(e.get("wind_speed"), "wind speed", 0, 200, False)
    wd = _num(e.get("wind_direction"), "wind direction", 0, 360, False)
    m = db.query_one("SELECT launch_time FROM missions WHERE mission_id=?", (mission_id,))
    if m and m["launch_time"] and ts < parse_iso(m["launch_time"]):
        raise ManualRejected(422, "BAD_TIMESTAMP", f"Timestamp {iso(ts)} is earlier than the mission launch time {m['launch_time']}")

    requested = str(e.get("flight_phase") or "AUTO").upper()
    det = detect_phase(vz, alt, st.launch_alt, st.phase, st.max_alt)
    if requested == "AUTO":
        if not det["phase"]:
            raise ManualRejected(422, "PHASE_UNDETERMINED", det["reason"] + ". Select the flight phase manually.")
        used, source = det["phase"], "AUTO"
    elif requested in PHASES:
        used, source = requested, "OVERRIDE"
        if used != "LANDED":
            try:
                reforecast.validate_phase_vs_velocity(used, vz)
            except reforecast.ReforecastError as exc:
                raise ManualRejected(exc.status, exc.code, str(exc))
    else:
        raise ManualRejected(422, "INVALID_INPUT", f"Unknown flight phase {requested}")

    payload = {"latitude": lat, "longitude": lon, "gps_altitude": alt, "vertical_velocity": vz, "gps_fix": True}
    if hv is not None:
        payload["ground_speed"] = hv
    if ws is not None:
        payload["wind_speed"] = ws
    if wd is not None:
        payload["wind_direction_from"] = wd
    packet = {"mission_id": mission_id, "packet_id": f"MAN-{uuid.uuid4().hex[:10].upper()}", "timestamp_utc": iso(ts),
              "data_source": "SIMULATED" if st.mode == "SIMULATION" else "MEASURED", "payload": payload,
              "entry_method": "MANUAL", "correction_of": e.get("correction_of"),
              "correction_reason": e.get("correction_reason")}
    res = await hub.ingest(packet)
    if not res.get("accepted"):
        raise ManualRejected(409 if res.get("code") in ("DUPLICATE", "BAD_CORRECTION") else 422, res["code"], res["reason"])
    if res["quality"] == "INVALID":
        raise ManualRejected(422, "INVALID_INPUT", "Telemetry rejected as invalid: " + ", ".join(res["quality_flags"]))
    out = {"accepted": True, "telemetry_id": res["telemetry_id"], "packet_id": res["packet_id"], "quality": res["quality"],
           "quality_flags": res["quality_flags"], "live": res["live"],
           "phase": {"detected": det["phase"], "detection_reason": det["reason"], "requested": requested, "used": used,
                     "source": source}, "warnings": [], "reforecast": {"submitted": False}}
    if "OUT_OF_ORDER" in res["quality_flags"]:
        out["warnings"].append("Out-of-order telemetry: stored for audit but not used as the live state or as a "
                               "re-forecast starting point. Historical observations are never rewritten.")
        return out
    if res["live"] and used != st.phase and st.phase not in ("ABORTED",):
        ev = hub.set_phase(st, used, iso(ts), packet["data_source"])
        await hub.broadcast(mission_id, {"type": "alert", "alert": ev})
    if used == "LANDED":
        out["reforecast"] = {"submitted": False, "reason": "Landing recorded; no remaining trajectory to forecast."}
        return out
    if not res["live"]:
        return out
    if e.get("reforecast", True):
        try:
            out["reforecast"] = reforecast.submit(
                mission_id, telemetry_id=res["telemetry_id"], phase=used,
                baseline_simulation_id=e.get("baseline_simulation_id"), float_end_datetime=e.get("float_end_datetime"),
                hold_duration_hours=e.get("hold_duration_hours"),
                use_measured_ascent_rate=bool(e.get("use_measured_ascent_rate", True)),
                forecast_cycle=e.get("forecast_cycle"))
        except reforecast.ReforecastError as exc:
            out["reforecast"] = {"submitted": False, "error": {"error_type": exc.code, "message": str(exc)}}
        except Exception as exc:  # noqa: BLE001  (e.g. WeatherDataError) - telemetry stays stored
            out["reforecast"] = {"submitted": False, "error": {"error_type": getattr(exc, "code", "ERROR"), "message": str(exc),
                                                               **getattr(exc, "details", {})}}
    return out
