"""Prediction-versus-actual comparison.

Alignment rule: each telemetry sample is compared with the prediction
evaluated AT THE SAME UTC TIMESTAMP, by linear time interpolation between the
two bracketing model output steps. Telemetry outside the prediction's time
span is excluded (never extrapolated) and counted. The forecast cycle and its
valid window are reported with the statistics; samples outside the forecast
window are flagged.
"""
from __future__ import annotations

import json
import math
import statistics
import uuid
from datetime import timedelta

from core import db, predictions
from core.db import iso, parse_iso, utcnow  # noqa: F401
from core.geo import geodesic_m
from core.predictions import store_prediction  # noqa: F401  (re-exported; historical import path)


def _interp(pred: list[dict], t: float, key: str):
    lo, hi = 0, len(pred) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if pred[mid]["_t"] <= t:
            lo = mid
        else:
            hi = mid
    a, b = pred[lo], pred[hi]
    va, vb = a.get(key), b.get(key)
    if va is None or vb is None:
        return None
    if b["_t"] == a["_t"]:
        return va
    f = (t - a["_t"]) / (b["_t"] - a["_t"])
    if key == "predicted_longitude" and abs(vb - va) > 180:
        vb += -360 if vb > va else 360
        return ((va + f * (vb - va)) + 180) % 360 - 180
    return va + f * (vb - va)


def compare(mission_id: str, prediction_set: str | None = None, max_points: int = 5000) -> dict:
    # Default = the immutable ORIGINAL prediction (V1). Any other version is compared only when asked for.
    ps = (predictions.get_set(mission_id, prediction_set) if prediction_set else predictions.original_set(mission_id))
    if not ps:
        return {"available": False, "reason": "No prediction attached to this mission."}
    pred = db.query("SELECT * FROM predictions WHERE prediction_set=? ORDER BY timestamp_utc", (ps["prediction_set"],))
    for p in pred:
        p["_t"] = parse_iso(p["timestamp_utc"]).timestamp()
    t0, t1 = pred[0]["_t"], pred[-1]["_t"]
    tel = db.query("SELECT timestamp_utc, latitude, longitude, gps_altitude, vertical_velocity, ambient_temperature, "
                   "payload_json, quality FROM telemetry WHERE mission_id=? AND quality IN ('VALID','DEGRADED') "
                   "AND superseded_by IS NULL ORDER BY timestamp_utc", (mission_id,))
    fv_from = parse_iso(ps["forecast_valid_from"]).timestamp() if ps["forecast_valid_from"] else None
    fv_to = parse_iso(ps["forecast_valid_to"]).timestamp() if ps["forecast_valid_to"] else None
    series, excluded, outside_forecast = [], 0, 0
    for r in tel:
        t = parse_iso(r["timestamp_utc"]).timestamp()
        if t < t0 or t > t1 or r["latitude"] is None or r["gps_altitude"] is None:
            excluded += 1
            continue
        if fv_from is not None and not (fv_from <= t < fv_to):
            outside_forecast += 1
        plat, plon = _interp(pred, t, "predicted_latitude"), _interp(pred, t, "predicted_longitude")
        palt = _interp(pred, t, "predicted_altitude")
        pvz = _interp(pred, t, "predicted_vertical_velocity")
        pws = _interp(pred, t, "predicted_wind_speed")
        ptemp = _interp(pred, t, "predicted_temperature")
        payload = json.loads(r["payload_json"]).get("payload", {})
        series.append({
            "t": r["timestamp_utc"],
            "actual": {"lat": r["latitude"], "lon": r["longitude"], "alt": r["gps_altitude"],
                       "vz": r["vertical_velocity"], "wind_speed": payload.get("wind_speed"),
                       "temperature_c": r["ambient_temperature"]},
            "predicted": {"lat": plat, "lon": plon, "alt": palt, "vz": pvz, "wind_speed": pws,
                          "temperature_c": ptemp},
            "altitude_error_m": r["gps_altitude"] - palt,
            "horizontal_error_m": geodesic_m(r["latitude"], r["longitude"], plat, plon) if plat is not None else None,
            "quality": r["quality"],
        })
    stats = None
    if series:
        ae = [abs(s["altitude_error_m"]) for s in series]
        he = [s["horizontal_error_m"] for s in series if s["horizontal_error_m"] is not None]
        stats = {"samples": len(series), "mean_abs_altitude_error_m": statistics.fmean(ae),
                 "max_abs_altitude_error_m": max(ae), "mean_horizontal_error_m": statistics.fmean(he),
                 "max_horizontal_error_m": max(he),
                 "rms_altitude_error_m": math.sqrt(statistics.fmean([a * a for a in ae]))}
    step = max(1, len(series) // max_points)
    return {
        "available": True,
        "prediction_set": ps["prediction_set"], "version": ps.get("version"), "kind": ps.get("kind"),
        "anchor_timestamp": ps.get("anchor_timestamp"), "source": ps["source"],
        "prediction_generated_utc": ps["created_utc"], "model_version": ps["model_version"],
        "forecast_cycle": ps["forecast_cycle"], "forecast_valid_from_utc": ps["forecast_valid_from"],
        "forecast_valid_to_utc_exclusive": ps["forecast_valid_to"],
        "prediction_span_utc": [pred[0]["timestamp_utc"], pred[-1]["timestamp_utc"]],
        "alignment": "Prediction linearly interpolated in time to each telemetry timestamp; no extrapolation.",
        "excluded_samples_outside_prediction_span": excluded,
        "samples_outside_forecast_valid_window": outside_forecast,
        "statistics": stats,
        "series": series[::step],
        "prediction_track": [{"t": p["timestamp_utc"], "lat": p["predicted_latitude"], "lon": p["predicted_longitude"],
                              "alt": p["predicted_altitude"], "phase": p["phase"]}
                             for p in pred[:: max(1, len(pred) // 3000)]],
        "metadata": json.loads(ps["metadata_json"] or "{}"),
    }
