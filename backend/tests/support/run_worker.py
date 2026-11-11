"""Run a REAL model worker in a subprocess with the synthetic wind adapter substituted for the Tawhiri one.

    python run_worker.py <worker.py> <job_dir>

Only ``wind_model_time_dependent`` is replaced (it is the sole module that needs the Tawhiri engine); every other
model module - ascent, descent, balloon physics, LiveTrajectoryManager, flight_forward, backtrack - is the
unmodified production code.
"""
import runpy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fake_tawhiri_wind  # noqa: E402

sys.modules["wind_model_time_dependent"] = fake_tawhiri_wind
worker, job_dir = sys.argv[1], sys.argv[2]
sys.argv = [worker, job_dir]
runpy.run_path(worker, run_name="__main__")
