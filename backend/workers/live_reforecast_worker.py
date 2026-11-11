"""Worker: telemetry-driven re-forecast with the ORIGINAL LiveTrajectoryManager.

Given the baseline burst-calculator prediction and one observed ASCENT state,
predicts the remaining ascent, burst, descent and landing. The manager's own
validation is retained (it refuses descent-phase telemetry, out-of-range
timestamps, etc.).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import BACKEND_DIR, as_utc, normalise_point, prepare_paths, run  # noqa: E402

MODEL_DIR = BACKEND_DIR / "simulations" / "burst_calculator" / "codes"


def main(job):
    req = job.request
    prepare_paths(MODEL_DIR)
    from live_trajectory_manager import LiveTrajectoryManager

    params = dict(req["parameters"])
    params["launch_datetime"] = as_utc(params["launch_datetime"])
    baseline = {
        "success": True,
        "trajectory": [{"datetime_utc": p["t"], "latitude": p["lat"], "longitude": p["lon"],
                        "altitude_m": p["alt"], "phase": p.get("phase")} for p in req["baseline_trajectory"]],
    }
    job.progress(0.1, "Initialising LiveTrajectoryManager", force=True)
    manager = LiveTrajectoryManager(params, baseline, output_dir=job.dir)
    job.progress(0.3, "Re-forecasting from telemetry state", force=True)
    result = manager.update(req["telemetry"])
    traj = [normalise_point(p) for p in result.pop("revised_trajectory", [])]
    for key in ("revised_ascent", "revised_descent"):
        result.pop(key, None)
    return {"model": "live_trajectory_manager_v2", "forecast_cycle": os.environ.get("TAWHIRI_CYCLE"),
            **result, "trajectory": traj}


if __name__ == "__main__":
    run(main)
