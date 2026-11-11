"""One consistent payload for the map and the comparison panels.

layers: original (V1, immutable) | actual (observed telemetry) | revised (selected / latest version).
Every distance is a WGS-84 geodesic distance.
"""
from __future__ import annotations

from core import db, predictions
from core.comparison import compare
from core.db import parse_iso
from core.geo import geodesic_m, initial_bearing_deg


def _pt(p):
    return None if not p else {"t": p["t"], "lat": p["lat"], "lon": p["lon"], "alt": p.get("alt"), "phase": p.get("phase")}


def _err_series(cmp: dict | None):
    if not cmp or not cmp.get("available") or not cmp.get("series"):
        return []
    return [{"t": s["t"], "horizontal_error_m": s["horizontal_error_m"], "altitude_error_m": s["altitude_error_m"]}
            for s in cmp["series"] if s["horizontal_error_m"] is not None]


def build(mission_id: str, version: str | None = None) -> dict:
    mission = db.query_one("SELECT mission_id, launch_latitude, launch_longitude, flight_phase FROM missions WHERE mission_id=?",
                           (mission_id,))
    versions = predictions.list_versions(mission_id)
    orig = predictions.original_set(mission_id)
    revised_sets = [v for v in versions if v["kind"] == "REVISED"]
    if version not in (None, "", "latest"):
        sel = predictions.get_set(mission_id, version)
    else:   # latest by anchor time (not by completion order)
        sel = max(revised_sets, key=lambda v: (v["anchor_timestamp"] or "", v["version"]), default=None)
        sel = predictions.get_set(mission_id, sel["prediction_set"]) if sel else None
    actual = predictions.actual_track(mission_id)
    otrack = predictions.track(orig["prediction_set"]) if orig else []
    osum = predictions.summarise(orig, otrack) if orig else None
    rtrack = predictions.track(sel["prediction_set"]) if sel else []
    rsum = predictions.summarise(sel, rtrack) if sel else None
    actual_landing = None
    if mission and mission["flight_phase"] == "LANDED" and actual:
        actual_landing = _pt(actual[-1])

    comp: dict = {"original_landing": _pt(osum["landing"]) if osum else None,
                  "revised_landing": _pt(rsum["landing"]) if rsum else None, "actual_landing": actual_landing}
    if osum and rsum:
        a, b = osum["landing"], rsum["landing"]
        comp["landing_shift_m"] = geodesic_m(a["lat"], a["lon"], b["lat"], b["lon"])
        comp["landing_shift_bearing_deg"] = initial_bearing_deg(a["lat"], a["lon"], b["lat"], b["lon"])
        comp["landing_shift_dlat_deg"], comp["landing_shift_dlon_deg"] = b["lat"] - a["lat"], b["lon"] - a["lon"]
        comp["landing_time_shift_s"] = (parse_iso(b["t"]) - parse_iso(a["t"])).total_seconds()
        comp["revised_landing_time"] = b["t"]
        comp["revised_remaining_duration_s"] = rsum["remaining_duration_s"]
        comp["original_remaining_duration_s_from_anchor"] = (
            parse_iso(a["t"]) - parse_iso(rsum["anchor_timestamp"] or rtrack[0]["t"])).total_seconds()
        comp["trajectory_displacement"] = predictions.displacement(otrack, rtrack)
    if actual_landing and osum:
        comp["actual_vs_original_landing_error_m"] = geodesic_m(
            actual_landing["lat"], actual_landing["lon"], osum["landing"]["lat"], osum["landing"]["lon"])
    if actual_landing and rsum:
        comp["actual_vs_revised_landing_error_m"] = geodesic_m(
            actual_landing["lat"], actual_landing["lon"], rsum["landing"]["lat"], rsum["landing"]["lon"])
    o_err = _err_series(compare(mission_id, orig["prediction_set"], 3000)) if orig else []
    r_err = _err_series(compare(mission_id, sel["prediction_set"], 3000)) if sel else []
    return {
        "mission_id": mission_id,
        "launch": ({"lat": mission["launch_latitude"], "lon": mission["launch_longitude"]} if mission else None),
        "versions": versions, "selected_version": rsum["version"] if rsum else None,
        "original": {"summary": osum, "track": otrack},
        "actual": {"points": actual, "latest": actual[-1] if actual else None, "landing": actual_landing},
        "revised": {"summary": rsum, "track": rtrack},
        "comparison": comp,
        "error_series": {"original": o_err, "revised": r_err,
                         "sufficient": len(o_err) >= 2 or len(r_err) >= 2,
                         "metric": "WGS-84 geodesic horizontal distance between observed and predicted position at the same UTC time"},
    }
