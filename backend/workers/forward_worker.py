"""Worker: SFT forward trajectory (ascent -> altitude hold -> parachute descent).

Runs the ORIGINAL ``simulation/flight_forward.simulate_mission`` and its KML
exporter from SFT_forward_reverse_CUSF without modification.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import BACKEND_DIR, as_utc, normalise_point, prepare_paths, run, wrap_get_wind  # noqa: E402

MODEL_DIR = BACKEND_DIR / "simulations" / "trajectory_forward_reverse" / "simulation"
MODEL_VERSION = "SFT flight_forward.simulate_mission (CUSF/Tawhiri wind backend)"


def main(job):
    req = job.request["parameters"]
    prepare_paths(MODEL_DIR)
    import ascent_model_time_dependent as ascent_mod
    import descent_model_time_dependent as descent_mod
    import flight_forward

    launch = as_utc(req["launch_datetime"])
    ascent_h = (float(req["target_altitude_m"]) - float(req["launch_altitude_m"])) / float(req["ascent_rate_mps"]) / 3600
    total_s = (ascent_h + float(req["hold_duration_hours"]) + 1.0) * 3600

    def on_wind(alt, sim_time):
        elapsed = (as_utc(sim_time) - launch).total_seconds()
        job.progress(elapsed / total_s, f"T+{elapsed/3600:.2f} h, {alt:,.0f} m", altitude_m=alt)

    wrap_get_wind([ascent_mod, descent_mod], job, on_wind)

    traj_raw = flight_forward.simulate_mission(
        launch_latitude=float(req["launch_latitude"]),
        launch_longitude=float(req["launch_longitude"]),
        launch_altitude_m=float(req["launch_altitude_m"]),
        launch_datetime=launch,
        hold_duration_hours=float(req["hold_duration_hours"]),
        payload_mass_kg=float(req["payload_mass_kg"]),
        parachute_diameter_m=float(req["parachute_diameter_m"]),
        parachute_cd=float(req.get("parachute_cd", 1.5)),
        target_altitude_m=float(req["target_altitude_m"]),
        ascent_rate_mps=float(req["ascent_rate_mps"]),
        ascent_hold_step_s=float(req.get("ascent_hold_step_s", 60.0)),
        descent_output_step_s=float(req.get("descent_output_step_s", 10.0)),
        ground_altitude_m=float(req.get("ground_altitude_m", 0.0)),
    )
    flight_forward.export_trajectory_kml(traj_raw, job.dir / "forward_trajectory.kml")

    traj = []
    for p in traj_raw:
        n = normalise_point(p)
        if n["phase"] in ("descent", "landing") and p.get("vertical_velocity_mps") is not None:
            n["vz"] = -float(p["vertical_velocity_mps"])
        elif n["phase"] == "ascent":
            n["vz"] = float(req["ascent_rate_mps"])
        elif n["phase"] == "altitude_hold":
            n["vz"] = 0.0
        traj.append(n)

    return {
        "model": "sft_forward",
        "model_version": MODEL_VERSION,
        "forecast_cycle": os.environ.get("TAWHIRI_CYCLE"),
        "atmosphere_source": "Winds: Tawhiri CUSF binary (FORECAST). T/P/rho: ISA (MODEL ESTIMATE).",
        "assumptions": [
            "Constant-rate ascent to target altitude.",
            "Idealised altitude hold for the requested duration (no balloon thermodynamics).",
            "Physics-based parachute descent (payload mass, diameter, Cd).",
        ],
        "files": {"kml": "forward_trajectory.kml"},
        "trajectory": traj,
    }


if __name__ == "__main__":
    run(main)
