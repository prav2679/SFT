"""Worker: SFT reverse trajectory (landing-target backtracking).

Runs the ORIGINAL ``simulation/flight_backtrack.backtrack_landing``: backward
integration of descent -> hold -> ascent, followed by forward validation with
``flight_forward.simulate_mission``. Not modified, not re-implemented.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import BACKEND_DIR, as_utc, norm_lon, normalise_point, prepare_paths, run, wrap_get_wind  # noqa: E402

MODEL_DIR = BACKEND_DIR / "simulations" / "trajectory_forward_reverse" / "simulation"
MODEL_VERSION = "SFT flight_backtrack.backtrack_landing (backward integration + forward validation)"


def main(job):
    req = job.request["parameters"]
    prepare_paths(MODEL_DIR)
    import ascent_model_time_dependent as ascent_mod
    import descent_model_time_dependent as descent_mod
    import flight_backtrack

    calls = {"n": 0, "stage": "backward integration"}

    def on_wind(alt, sim_time):
        calls["n"] += 1
        job.progress(None, f"{calls['stage']}: {alt:,.0f} m @ {str(sim_time)[:19]}Z", wind_calls=calls["n"])

    wrap_get_wind([flight_backtrack], job, on_wind)

    def on_forward(alt, sim_time):
        calls["stage"] = "forward validation"
        on_wind(alt, sim_time)

    wrap_get_wind([ascent_mod, descent_mod], job, on_forward)

    out = flight_backtrack.backtrack_landing(
        target_latitude=float(req["target_latitude"]),
        target_longitude=float(req["target_longitude"]),
        target_landing_datetime=as_utc(req["target_landing_datetime"]),
        target_altitude_m=float(req["target_altitude_m"]),
        hold_duration_hours=float(req["hold_duration_hours"]),
        launch_altitude_m=float(req.get("launch_altitude_m", 0.0)),
        ascent_rate_mps=float(req["ascent_rate_mps"]),
        payload_mass_kg=float(req["payload_mass_kg"]),
        parachute_diameter_m=float(req["parachute_diameter_m"]),
        parachute_cd=float(req.get("parachute_cd", 1.0)),
        ground_altitude_m=float(req.get("ground_altitude_m", 0.0)),
        backtrack_step_s=float(req.get("backtrack_step_s", 60.0)),
        ascent_hold_step_s=float(req.get("ascent_hold_step_s", 60.0)),
        descent_output_step_s=float(req.get("descent_output_step_s", 10.0)),
        kml_path=str(job.dir / "reverse_validated_trajectory.kml"),
    )
    traj = [normalise_point(p) for p in out.pop("trajectory")]
    for key in ("estimated_launch_longitude", "estimated_descent_start_longitude", "predicted_landing_longitude"):
        if out.get(key) is not None:
            out[key] = norm_lon(out[key])
    hold_start = next((p for p in traj if p["phase"] == "altitude_hold"), None)
    return {
        "model": "sft_reverse",
        "model_version": MODEL_VERSION,
        "forecast_cycle": os.environ.get("TAWHIRI_CYCLE"),
        **out,
        "target": {"latitude": float(req["target_latitude"]), "longitude": float(req["target_longitude"]),
                   "datetime_utc": as_utc(req["target_landing_datetime"]).isoformat()},
        "forward_validation_hold_start": hold_start,
        "convergence": {"method": "single backward pass + one forward validation run",
                        "iterations": 1,
                        "note": "The existing algorithm does not iterate; landing error is reported, not minimised."},
        "assumptions": [
            "Backward descent uses parachute terminal velocity from ISA density (max 3 h).",
            "Hold is backtracked at constant target altitude.",
            "Ascent is backtracked at the configured constant ascent rate.",
            "Result is a CANDIDATE launch point/time; forward validation determines actual landing error.",
            "Launch-time search windows are not supported by the existing algorithm.",
        ],
        "files": {"kml": "reverse_validated_trajectory.kml"},
        "trajectory": traj,
    }


if __name__ == "__main__":
    run(main)
