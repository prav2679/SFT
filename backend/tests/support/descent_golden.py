"""Produce a deterministic descent trajectory with the production descent model + synthetic wind."""
import contextlib, io, json, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parents[1]
sys.path.insert(0, str(HERE))
import fake_tawhiri_wind  # noqa: E402

sys.modules["wind_model_time_dependent"] = fake_tawhiri_wind
pkg = sys.argv[1]                     # "burst" or "forward"
dirs = {"burst": BACKEND / "simulations/burst_calculator/codes",
        "forward": BACKEND / "simulations/trajectory_forward_reverse/simulation"}
sys.path.insert(0, str(dirs[pkg]))
import descent_model_time_dependent as dm  # noqa: E402

with contextlib.redirect_stdout(io.StringIO()):
    traj = dm.simulate_descent(burst_latitude=-33.8688, burst_longitude=151.2093, burst_altitude=26000.0,
                               ground_altitude=50.0, payload_mass=5.0, parachute_diameter=2.4, parachute_cd=1.0,
                               dt=10.0, burst_datetime="2026-11-07T04:00:00Z")
print(json.dumps([{k: p[k] for k in ("time_s", "datetime_utc", "latitude", "longitude", "altitude_m",
                                     "vertical_velocity_mps", "phase")} for p in traj]))
