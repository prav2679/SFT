"""Worker: SFT Balloon Burst Calculator.

Runs the ORIGINAL ``codes/flight_model_paramaterized.run_flight`` (ascent ->
burst -> parachute descent) without modifying it. Only its module-level
output paths (hard-coded Windows paths in the original) are redirected to the
job directory at runtime so the CSV/KML it writes land beside the result.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (BACKEND_DIR, as_utc, normalise_point, prepare_paths, run,  # noqa: E402
                     wrap_get_wind)

MODEL_DIR = BACKEND_DIR / "simulations" / "burst_calculator" / "codes"
MODEL_VERSION = "SFT flight_model_paramaterized (V4 validated baseline)"


def main(job):
    req = job.request
    prepare_paths(MODEL_DIR)

    import ascent_model_time_dependent as ascent_mod
    import descent_model_time_dependent as descent_mod
    import flight_model_paramaterized as flight

    # Redirect the original hard-coded output files into the job directory.
    flight.OUTPUT_DIR = job.dir
    flight.OUTPUT_FILE = "complete_flight_trajectory.csv"
    flight.KML_FILE = "complete_flight_trajectory.kml"

    p = dict(req["parameters"])
    p["launch_datetime"] = as_utc(p["launch_datetime"])
    for key in list(p):
        if key != "launch_datetime" and isinstance(p[key], (int, float)) and not isinstance(p[key], bool):
            p[key] = float(p[key])

    burst_alt = p["burst_altitude"]
    launch_alt = p["launch_altitude"]
    state = {"descending": False}

    def on_wind(alt, sim_time):
        if not state["descending"] and alt >= burst_alt - 1e-6:
            state["descending"] = True
        if state["descending"]:
            frac = 0.5 + 0.5 * (burst_alt - alt) / max(burst_alt - p["ground_altitude"], 1.0)
            phase = "descent"
        else:
            frac = 0.5 * (alt - launch_alt) / max(burst_alt - launch_alt, 1.0)
            phase = "ascent"
        job.progress(frac, f"{phase}: {alt:,.0f} m", sim_time=str(sim_time), altitude_m=alt)

    wrap_get_wind([ascent_mod, descent_mod], job, on_wind)

    result = flight.run_flight(p)

    traj = []
    for point in result.get("trajectory", []):
        n = normalise_point(point)
        if n["phase"] == "descent" and point.get("vertical_velocity_mps") is not None:
            n["vz"] = -float(point["vertical_velocity_mps"])   # model reports downward speed
        elif point.get("ascent_rate") is not None:
            n["vz"] = float(point["ascent_rate"])
        traj.append(n)

    # ----- Engineering warnings derived strictly from model output ---------
    warnings = []
    exceeded = next((pt for pt in traj if pt.get("diameter_m") and pt["diameter_m"] >= p["burst_diameter"]), None)
    if exceeded:
        warnings.append({
            "severity": "WARNING",
            "code": "DIAMETER_EXCEEDS_BURST_DIAMETER",
            "message": (f"Model balloon diameter reached {exceeded['diameter_m']:.2f} m (configured burst "
                        f"diameter {p['burst_diameter']:.2f} m) at {exceeded['alt']:,.0f} m. The SFT model "
                        "triggers burst by commanded altitude only; diameter is informational."),
        })
    if not result.get("success"):
        warnings.append({"severity": "CRITICAL", "code": "ASCENT_TERMINATED",
                         "message": "Balloon did not reach the burst condition (safety ceiling reached first)."})
    if traj and traj[-1]["phase"] in ("descent", "landing") and traj[-1]["alt"] > p["ground_altitude"] + 1:
        warnings.append({"severity": "INFO", "code": "TERMINAL_STATE_ABOVE_GROUND",
                         "message": f"Final model record is at {traj[-1]['alt']:.1f} m - terminal state, not confirmed touchdown."})
    warnings.append({"severity": "INFO", "code": "ISA_ATMOSPHERE",
                     "message": "Temperature/pressure/density are ISA estimates supplied by the wind adapter; "
                                "winds are Tawhiri forecast values (see wind_model_time_dependent.py)."})

    return {
        "model": "burst_calculator",
        "model_version": MODEL_VERSION,
        "forecast_cycle": os.environ.get("TAWHIRI_CYCLE"),
        "atmosphere_source": "Winds: Tawhiri CUSF binary (FORECAST). T/P/rho: ISA (MODEL ESTIMATE).",
        "success": bool(result.get("success")),
        "phase": result.get("phase"),
        "burst": result.get("burst"),
        "landing": result.get("landing"),
        "ascent_time_s": result.get("ascent_time_s"),
        "descent_time_s": result.get("descent_time_s"),
        "total_flight_time_s": result.get("total_flight_time_s"),
        "launch_to_landing_distance_m": result.get("launch_to_landing_distance_m"),
        "burst_to_landing_distance_m": result.get("burst_to_landing_distance_m"),
        "warnings": warnings,
        "not_modelled": ["internal_pressure", "differential_pressure", "internal_gas_temperature",
                         "envelope_temperature"],
        "files": {"csv": "complete_flight_trajectory.csv", "kml": "complete_flight_trajectory.kml"},
        "trajectory": traj,
    }


if __name__ == "__main__":
    run(main)
