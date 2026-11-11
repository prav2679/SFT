"""Worker: phase-aware re-forecast from ONE observed telemetry state.

The remaining trajectory is recomputed with the EXISTING SFT scientific models, starting from the observed
position / altitude / time (never from the launch point). Which model runs depends on the flight phase and on the
mission's original model:

  phase    mission model   what is run
  -------  --------------  ----------------------------------------------------------------------------------
  ASCENT   burst           LiveTrajectoryManager.update()  (remaining ascent -> burst -> parachute descent)
  ASCENT   forward (hold)  flight_forward.simulate_mission() launched from the observed state
                           (remaining ascent -> hold -> parachute descent)
  FLOAT    forward / burst flight_forward.simulate_mission() launched from the observed float state with the
                           remaining hold time (hold -> parachute descent)
  DESCENT  either          descent_model_time_dependent.simulate_descent() started at the observed altitude,
                           position AND downward speed (``initial_vertical_velocity``)

Descent telemetry is NEVER fed into an ascent model, and ascent telemetry is never fed into a descent model.
The two model packages contain same-named modules with different contents, so each job imports exactly one
package (workers run in their own process).
"""
from __future__ import annotations

import math
import os
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import BACKEND_DIR, as_utc, normalise_point, prepare_paths, run  # noqa: E402

BURST_DIR = BACKEND_DIR / "simulations" / "burst_calculator" / "codes"
FORWARD_DIR = BACKEND_DIR / "simulations" / "trajectory_forward_reverse" / "simulation"
MODEL_VERSION = "SFT telemetry re-forecast (existing ascent / hold / descent models, observed initial state)"
FLOAT_EPSILON_M = 0.5          # model requires target altitude > launch altitude; see _forecast_float()


def _norm_params(model: str, p: dict) -> dict:
    """Common names for the two parameter sets. Raises KeyError naming a missing required key."""
    if model == "burst":
        return {"payload_mass": p["payload_mass"], "parachute_diameter": p["parachute_diameter"],
                "parachute_cd": p["parachute_cd"], "ground_altitude": p["ground_altitude"],
                "ascent_rate": p["ascent_rate"], "descent_dt": p["descent_time_step"],
                "hold_step": p["ascent_time_step"], "target_altitude": p["burst_altitude"],
                "hold_hours": None}
    return {"payload_mass": p["payload_mass_kg"], "parachute_diameter": p["parachute_diameter_m"],
            "parachute_cd": p.get("parachute_cd", 1.5), "ground_altitude": p.get("ground_altitude_m", 0.0),
            "ascent_rate": p["ascent_rate_mps"], "descent_dt": p.get("descent_output_step_s", 10.0),
            "hold_step": p.get("ascent_hold_step_s", 60.0), "target_altitude": p["target_altitude_m"],
            "hold_hours": p["hold_duration_hours"]}


def _point(p: dict, vz_fn=None) -> dict:
    n = normalise_point(p)
    phase = n.get("phase")
    if phase in ("descent", "landing") and p.get("vertical_velocity_mps") is not None:
        n["vz"] = -float(p["vertical_velocity_mps"])            # model reports downward speed
    elif p.get("ascent_rate") is not None and phase in ("ascent", "telemetry"):
        n["vz"] = float(p["ascent_rate"])
    elif phase == "altitude_hold":
        n["vz"] = 0.0
    return n


def _anchor_point(tel: dict) -> dict:
    return {"t": as_utc(tel["datetime_utc"]).isoformat(), "lat": float(tel["latitude"]),
            "lon": float(tel["longitude"]), "alt": float(tel["altitude_m"]), "phase": "telemetry",
            "vz": tel.get("vertical_velocity_mps")}


# ------------------------------------------------------------------------------------------ ASCENT (burst)
def _forecast_ascent_burst(job, tel, params, req, warnings):
    prepare_paths(BURST_DIR)
    from live_trajectory_manager import LiveTrajectoryManager

    p = dict(params)
    p["launch_datetime"] = as_utc(p["launch_datetime"])
    baseline = {"success": True, "trajectory": [
        {"datetime_utc": q["t"], "latitude": q["lat"], "longitude": q["lon"], "altitude_m": q["alt"],
         "phase": q.get("phase")} for q in req["baseline_trajectory"]]}
    used_rate = float(p["ascent_rate"])
    vz = tel.get("vertical_velocity_mps")
    if req.get("use_measured_ascent_rate", True) and vz is not None and 0.5 <= float(vz) <= 15.0:
        used_rate = float(vz)
        p["ascent_rate"] = used_rate                      # parameter value only; model code untouched
    elif vz is not None:
        warnings.append({"severity": "WARNING", "code": "MEASURED_RATE_NOT_USED",
                         "message": f"Measured vertical velocity {vz:.2f} m/s is outside 0.5-15 m/s; the planned "
                                    f"ascent rate {used_rate:.2f} m/s was used for the remaining ascent."})
    job.progress(0.1, "Initialising LiveTrajectoryManager", force=True)
    manager = LiveTrajectoryManager(p, baseline, output_dir=job.dir)
    job.progress(0.3, "Re-forecasting remaining ascent, burst and descent", force=True)
    result = manager.update({"datetime_utc": as_utc(tel["datetime_utc"]).isoformat(), "latitude": tel["latitude"],
                             "longitude": tel["longitude"], "altitude_m": tel["altitude_m"], "phase": "ascent"})
    traj = [_point(q) for q in result["revised_trajectory"]]
    traj[0]["phase"] = "telemetry"
    return traj, {"engine": "LiveTrajectoryManager.update", "ascent_rate_used_mps": used_rate,
                  "forecast_status": result.get("forecast_status")}


# ------------------------------------------------------------------------------- hold missions (forward pkg)
def _forecast_hold(job, tel, np_, req, warnings, phase):
    prepare_paths(FORWARD_DIR)
    import flight_forward

    t0 = as_utc(tel["datetime_utc"])
    alt = float(tel["altitude_m"])
    used_rate = float(np_["ascent_rate"])
    vz = tel.get("vertical_velocity_mps")
    if phase == "ASCENT":
        if req.get("use_measured_ascent_rate", True) and vz is not None and 0.5 <= float(vz) <= 15.0:
            used_rate = float(vz)
        launch_alt, target_alt = alt, float(np_["target_altitude"])
        if target_alt <= alt:
            raise ValueError("Observed altitude is at or above the planned float altitude; this is not an ASCENT state.")
        hold_h = float(req["hold_duration_hours"] if req.get("hold_duration_hours") is not None else np_["hold_hours"])
    else:  # FLOAT: hold at the OBSERVED altitude until the planned end of float
        end = req.get("float_end_datetime")
        if not end:
            raise ValueError("float_end_datetime (planned end of float) is required to re-forecast a FLOAT state.")
        remaining_s = (as_utc(end) - t0).total_seconds()
        if remaining_s <= 60:
            raise ValueError("The planned end of float is not later than the telemetry time; submit the state as "
                             "DESCENT or extend the planned float end.")
        # simulate_mission() requires target > launch altitude: start FLOAT_EPSILON_M below the observed float
        # altitude and hold AT the observed altitude. The first row is then replaced by the exact observed state.
        launch_alt, target_alt = alt - FLOAT_EPSILON_M, alt
        hold_h = remaining_s / 3600.0
        warnings.append({"severity": "INFO", "code": "FLOAT_STATE_INITIALISATION",
                         "message": "Float is modelled by the existing ascent->hold model started "
                                    f"{FLOAT_EPSILON_M} m below the observed altitude (model needs target > launch); "
                                    "the first row is replaced by the observed state."})
    job.progress(0.2, f"Running ascent/hold/descent model from observed {phase} state", force=True)
    raw = flight_forward.simulate_mission(
        launch_latitude=float(tel["latitude"]), launch_longitude=float(tel["longitude"]),
        launch_altitude_m=launch_alt, launch_datetime=t0, hold_duration_hours=hold_h,
        payload_mass_kg=float(np_["payload_mass"]), parachute_diameter_m=float(np_["parachute_diameter"]),
        parachute_cd=float(np_["parachute_cd"]), target_altitude_m=target_alt, ascent_rate_mps=used_rate,
        ascent_hold_step_s=float(np_["hold_step"]), descent_output_step_s=float(np_["descent_dt"]),
        ground_altitude_m=float(np_["ground_altitude"]))
    traj = [_point(q) for q in raw]
    if phase == "FLOAT":
        traj = [q for q in traj[1:] if q["phase"] != "ascent"]          # drop the epsilon ascent artefact
    else:
        traj = traj[1:]
    anchor = _anchor_point(tel)
    return [anchor] + traj, {"engine": "flight_forward.simulate_mission", "ascent_rate_used_mps": used_rate,
                             "remaining_hold_hours": hold_h}


# ------------------------------------------------------------------------------------------------- DESCENT
def _forecast_descent(job, tel, np_, model, warnings):
    prepare_paths(BURST_DIR if model == "burst" else FORWARD_DIR)
    from descent_model_time_dependent import simulate_descent

    vz = tel.get("vertical_velocity_mps")
    if vz is None:
        raise ValueError("vertical_velocity is required to re-forecast a DESCENT state "
                         "(the descent model needs the observed downward speed).")
    if float(vz) > 0.5:
        raise ValueError(f"Observed vertical velocity {float(vz):+.2f} m/s is upward; this is not a DESCENT state.")
    down = max(0.0, -float(vz))
    if float(tel["altitude_m"]) <= float(np_["ground_altitude"]):
        raise ValueError("Observed altitude is at or below the ground altitude; nothing left to forecast.")
    job.progress(0.2, "Running parachute descent model from observed state", force=True)
    raw = simulate_descent(
        burst_latitude=float(tel["latitude"]), burst_longitude=float(tel["longitude"]),
        burst_altitude=float(tel["altitude_m"]), ground_altitude=float(np_["ground_altitude"]),
        payload_mass=float(np_["payload_mass"]), parachute_diameter=float(np_["parachute_diameter"]),
        parachute_cd=float(np_["parachute_cd"]), dt=float(np_["descent_dt"]),
        burst_datetime=as_utc(tel["datetime_utc"]), descent_rate=None, initial_vertical_velocity=down)
    traj = [_point(q) for q in raw]
    traj[0]["phase"] = "telemetry"
    return traj, {"engine": "simulate_descent(initial_vertical_velocity=observed)", "initial_descent_speed_mps": down}


def main(job):
    req = job.request
    model, tel, params = req["model"], dict(req["telemetry"]), req["parameters"]
    phase = str(tel["phase"]).upper()
    np_ = _norm_params(model, params)
    warnings: list[dict] = []
    t0 = as_utc(tel["datetime_utc"])

    if phase == "ASCENT" and model == "burst":
        traj, info = _forecast_ascent_burst(job, tel, params, req, warnings)
    elif phase in ("ASCENT", "FLOAT"):
        traj, info = _forecast_hold(job, tel, np_, req, warnings, phase)
    elif phase == "DESCENT":
        traj, info = _forecast_descent(job, tel, np_, model, warnings)
    else:
        raise ValueError(f"Unsupported flight phase for re-forecast: {phase}")

    traj = [q for q in traj if q.get("t") and q.get("lat") is not None]
    traj.sort(key=lambda q: as_utc(q["t"]))
    burst = next((q for q in traj if q["phase"] == "burst"), None)
    landing = traj[-1]
    if landing["alt"] > float(np_["ground_altitude"]) + 1.0:
        warnings.append({"severity": "WARNING", "code": "NO_LANDING_REACHED",
                         "message": f"Final model point is at {landing['alt']:.0f} m - the model stopped before "
                                    "touchdown (safety ceiling or no burst)."})
    warnings.append({"severity": "INFO", "code": "ISA_ATMOSPHERE",
                     "message": "Winds are Tawhiri forecast values; temperature/pressure/density are ISA estimates."})
    return {
        "model": "telemetry_reforecast", "model_version": MODEL_VERSION, "mission_model": model, "phase": phase,
        "forecast_cycle": os.environ.get("TAWHIRI_CYCLE"), **info,
        "anchor": _anchor_point(tel), "burst": burst, "landing": landing,
        "remaining_duration_s": (as_utc(landing["t"]) - t0).total_seconds(),
        "warnings": warnings, "trajectory": traj,
    }


if __name__ == "__main__":
    run(main)
