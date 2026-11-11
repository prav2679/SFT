"""Prediction versions: immutable ORIGINAL (V1) + one REVISED version per telemetry-triggered re-forecast.

* A prediction set is written once and never changed (enforced by database triggers, see core/db.py).
* V1 is the ORIGINAL prediction made at mission initialisation. It is never replaced by telemetry updates.
* Every re-forecast appends a new version (V2, V3, ...) with its anchor telemetry record and parent set.
* All horizontal differences use WGS-84 geodesic distance (core/geo.py).
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

from core import db
from core.db import iso, parse_iso, utcnow
from core.geo import geodesic_m, initial_bearing_deg

KINDS = ("ORIGINAL", "REVISED", "ATTACHED")


def store_prediction(mission_id: str, trajectory: list[dict], source: str, model_version: str | None,
                     forecast_cycle: str | None, metadata: dict | None = None, kind: str | None = None,
                     parent_set: str | None = None, anchor_telemetry_id: int | None = None,
                     anchor_timestamp: str | None = None, anchor_phase: str | None = None) -> str:
    """Persist a new prediction version atomically and return its prediction_set id."""
    pts = [p for p in trajectory if p.get("t") and p.get("lat") is not None and p.get("alt") is not None]
    if len(pts) < 2:
        raise ValueError("Prediction must contain at least two timed points")
    pts.sort(key=lambda p: parse_iso(p["t"]))
    if kind is not None and kind not in KINDS:
        raise ValueError(f"Unknown prediction kind {kind}")
    set_id = f"PS-{uuid.uuid4().hex[:8].upper()}"
    valid_from = valid_to = None
    if forecast_cycle:
        from core.weather import cycle_to_datetime
        valid_from = cycle_to_datetime(forecast_cycle)
        valid_to = valid_from + timedelta(hours=192)
    with db.tx() as c:
        nxt = c.execute("SELECT COALESCE(MAX(version), 0) + 1 FROM prediction_sets WHERE mission_id=?",
                        (mission_id,)).fetchone()[0]
        has_original = c.execute("SELECT 1 FROM prediction_sets WHERE mission_id=? AND kind='ORIGINAL'",
                                 (mission_id,)).fetchone()
        kind = kind or ("ATTACHED" if has_original else "ORIGINAL")
        if kind == "ORIGINAL" and has_original:
            raise ValueError("This mission already has an original prediction; it is immutable and cannot be replaced.")
        c.execute("INSERT INTO prediction_sets (prediction_set, mission_id, created_utc, source, model_version, "
                  "forecast_cycle, forecast_valid_from, forecast_valid_to, metadata_json, version, kind, parent_set, "
                  "anchor_telemetry_id, anchor_timestamp, anchor_phase) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (set_id, mission_id, iso(utcnow()), source, model_version, forecast_cycle, iso(valid_from),
                   iso(valid_to), json.dumps(metadata or {}, default=str), nxt, kind, parent_set,
                   anchor_telemetry_id, anchor_timestamp, anchor_phase))
        c.executemany(
            "INSERT INTO predictions (mission_id, prediction_set, timestamp_utc, predicted_latitude, "
            "predicted_longitude, predicted_altitude, predicted_vertical_velocity, predicted_wind_speed, "
            "predicted_temperature, phase, model_version, forecast_cycle) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            [(mission_id, set_id, iso(parse_iso(p["t"])), p["lat"], p["lon"], p["alt"], p.get("vz"),
              p.get("wind_speed"), p.get("temperature_c"), p.get("phase"), model_version, forecast_cycle)
             for p in pts])
    return set_id


# --------------------------------------------------------------------------------------------------- reads
def original_set(mission_id: str) -> dict | None:
    return (db.query_one("SELECT * FROM prediction_sets WHERE mission_id=? AND kind='ORIGINAL'", (mission_id,))
            or db.query_one("SELECT * FROM prediction_sets WHERE mission_id=? ORDER BY version ASC LIMIT 1",
                            (mission_id,)))


def get_set(mission_id: str, ref: str | int | None) -> dict | None:
    """Resolve a prediction set by id (PS-...) or by version number (2 / 'V2' / 'v2')."""
    if ref in (None, ""):
        return None
    s = str(ref)
    if s.upper().startswith("PS-"):
        return db.query_one("SELECT * FROM prediction_sets WHERE prediction_set=? AND mission_id=?", (s, mission_id))
    digits = s.lstrip("vV")
    if digits.isdigit():
        return db.query_one("SELECT * FROM prediction_sets WHERE mission_id=? AND version=?", (mission_id, int(digits)))
    return None


def track(set_id: str, max_points: int = 4000) -> list[dict]:
    rows = db.query("SELECT timestamp_utc, predicted_latitude, predicted_longitude, predicted_altitude, "
                    "predicted_vertical_velocity, phase FROM predictions WHERE prediction_set=? "
                    "ORDER BY timestamp_utc", (set_id,))
    keep = set(range(0, len(rows), max(1, len(rows) // max_points)))
    keep.add(len(rows) - 1)
    for i, r in enumerate(rows):                       # never thin out phase transitions (burst, landing...)
        if i and rows[i - 1]["phase"] != r["phase"]:
            keep.update({i - 1, i})
    return [{"t": r["timestamp_utc"], "lat": r["predicted_latitude"], "lon": r["predicted_longitude"],
             "alt": r["predicted_altitude"], "vz": r["predicted_vertical_velocity"], "phase": r["phase"]}
            for i, r in enumerate(rows) if i in keep]


def _point_of(trk: list[dict], phase: str):
    return next((p for p in trk if p["phase"] == phase), None)


def summarise(ps: dict, trk: list[dict] | None = None) -> dict:
    trk = trk if trk is not None else track(ps["prediction_set"])
    if not trk:
        return {"prediction_set": ps["prediction_set"], "version": ps.get("version"), "points": 0}
    start = ps.get("anchor_timestamp") or trk[0]["t"]
    landing = trk[-1]
    burst = _point_of(trk, "burst")
    hold = [p for p in trk if p["phase"] == "altitude_hold"]
    return {
        "prediction_set": ps["prediction_set"], "version": ps.get("version"), "kind": ps.get("kind"),
        "label": ("V%s %s" % (ps.get("version"), {"ORIGINAL": "Original", "REVISED": "Revised"}.get(ps.get("kind"), "Attached"))),
        "created_utc": ps["created_utc"], "source": ps["source"], "model_version": ps["model_version"],
        "forecast_cycle": ps["forecast_cycle"], "parent_set": ps.get("parent_set"),
        "anchor_telemetry_id": ps.get("anchor_telemetry_id"), "anchor_timestamp": ps.get("anchor_timestamp"),
        "anchor_phase": ps.get("anchor_phase"), "span_utc": [trk[0]["t"], landing["t"]],
        "burst": burst, "float": ({"start": hold[0], "end": hold[-1]} if hold else None),
        "landing": landing,
        "remaining_duration_s": (parse_iso(landing["t"]) - parse_iso(start)).total_seconds(),
        "metadata": json.loads(ps.get("metadata_json") or "{}"),
    }


def list_versions(mission_id: str) -> list[dict]:
    sets = db.query("SELECT * FROM prediction_sets WHERE mission_id=? ORDER BY version ASC, created_utc ASC", (mission_id,))
    out = []
    orig = original_set(mission_id)
    orig_land = None
    for ps in sets:
        s = summarise(ps)
        if orig and ps["prediction_set"] == orig["prediction_set"]:
            orig_land = s.get("landing")
        out.append(s)
    for s in out:
        if orig_land and s.get("landing"):
            s["landing_shift_from_original_m"] = geodesic_m(orig_land["lat"], orig_land["lon"],
                                                           s["landing"]["lat"], s["landing"]["lon"])
    return out


def _at(trk: list[dict], t: float):
    """Linear time interpolation of lat/lon inside a track (no extrapolation)."""
    if not trk or t < trk[0]["_t"] or t > trk[-1]["_t"]:
        return None
    lo, hi = 0, len(trk) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if trk[mid]["_t"] <= t:
            lo = mid
        else:
            hi = mid
    a, b = trk[lo], trk[hi]
    if b["_t"] == a["_t"]:
        return a["lat"], a["lon"]
    f = (t - a["_t"]) / (b["_t"] - a["_t"])
    dlon = b["lon"] - a["lon"]
    if abs(dlon) > 180:
        dlon += -360 if dlon > 0 else 360
    return a["lat"] + f * (b["lat"] - a["lat"]), a["lon"] + f * dlon


def displacement(original: list[dict], revised: list[dict], step_s: float = 60.0) -> dict | None:
    """Time-aligned horizontal displacement between two tracks over their common time window."""
    o = [{**p, "_t": parse_iso(p["t"]).timestamp()} for p in original]
    r = [{**p, "_t": parse_iso(p["t"]).timestamp()} for p in revised]
    if not o or not r:
        return None
    t0, t1 = max(o[0]["_t"], r[0]["_t"]), min(o[-1]["_t"], r[-1]["_t"])
    if t1 <= t0:
        return None
    vals, t = [], t0
    while t <= t1:
        po, pr = _at(o, t), _at(r, t)
        if po and pr:
            vals.append(geodesic_m(po[0], po[1], pr[0], pr[1]))
        t += step_s
    if not vals:
        return None
    return {"mean_m": sum(vals) / len(vals), "max_m": max(vals), "final_m": vals[-1], "samples": len(vals),
            "window_utc": [iso(datetime.fromtimestamp(t0, timezone.utc)), iso(datetime.fromtimestamp(t1, timezone.utc))]}


def actual_track(mission_id: str, max_points: int = 6000) -> list[dict]:
    """Chronological observed positions: live, valid/degraded, not superseded by a correction."""
    rows = db.query("SELECT telemetry_id, timestamp_utc, latitude, longitude, gps_altitude, vertical_velocity, "
                    "entry_method, quality, quality_flags FROM telemetry WHERE mission_id=? "
                    "AND quality IN ('VALID','DEGRADED') AND superseded_by IS NULL AND latitude IS NOT NULL "
                    "AND gps_altitude IS NOT NULL ORDER BY timestamp_utc", (mission_id,))
    rows = [r for r in rows if "OUT_OF_ORDER" not in (r["quality_flags"] or "")]
    step = max(1, len(rows) // max_points)
    keep = [r for i, r in enumerate(rows) if i % step == 0 or i == len(rows) - 1]
    return [{"t": r["timestamp_utc"], "lat": r["latitude"], "lon": r["longitude"], "alt": r["gps_altitude"],
             "vz": r["vertical_velocity"], "telemetry_id": r["telemetry_id"], "entry_method": r["entry_method"],
             "quality": r["quality"]} for r in keep]
