"""Shared fixtures. New-feature tests run the REAL SFT worker processes against a synthetic wind adapter
(tests/support/fake_tawhiri_wind.py) because the Tawhiri engine and the 12.7 GB forecast dataset are not
available in CI. A sparse file of the exact dataset size stands in for a valid forecast cycle."""
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("SFT_DATA_DIR", tempfile.mkdtemp())
os.environ.setdefault("TAWHIRI_DATA_DIR", tempfile.mkdtemp())
os.environ.setdefault("TAWHIRI_API_URL", "http://127.0.0.1:9")

SYDNEY = (-33.8688, 151.2093)
CHENNAI = (13.0827, 80.2707)


def burst_params(lat, lon, launch_iso):
    return {"latitude": lat, "longitude": lon, "launch_altitude": 20.0, "launch_datetime": launch_iso,
            "payload_mass": 5.0, "envelope_mass": 3.0, "helium_mass": 2.0, "initial_volume": 12.05,
            "burst_diameter": 13.02, "balloon_cd": 0.47, "parachute_diameter": 2.4, "parachute_cd": 1.0,
            "ascent_rate": 6.69, "descent_rate": 5.0, "ascent_time_step": 10.0, "descent_time_step": 10.0,
            "burst_altitude": 30000.0, "maximum_altitude": 35000.0, "ground_altitude": 20.0}


def forward_params(lat, lon, launch_iso):
    return {"launch_latitude": lat, "launch_longitude": lon, "launch_altitude_m": 20.0, "launch_datetime": launch_iso,
            "hold_duration_hours": 2.0, "payload_mass_kg": 5.0, "parachute_diameter_m": 2.4, "parachute_cd": 1.0,
            "target_altitude_m": 25000.0, "ascent_rate_mps": 5.0, "ascent_hold_step_s": 60.0,
            "descent_output_step_s": 10.0, "ground_altitude_m": 20.0}


@pytest.fixture()
def env(tmp_path, monkeypatch):
    import config
    from core import db, tasks
    from core.telemetry import hub
    from fastapi.testclient import TestClient
    from main import app

    day = (datetime.now(timezone.utc) - timedelta(days=2)).date()
    cycle, launch = day.strftime("%Y%m%d") + "00", f"{day.isoformat()}T00:00:00Z"
    wx, data = tmp_path / "wx", tmp_path / "data"
    wx.mkdir(); data.mkdir()
    (wx / cycle).touch()
    os.truncate(wx / cycle, config.DATASET_SIZE_BYTES)                       # sparse: valid size, no disk use
    monkeypatch.setattr(config, "TAWHIRI_DATA_DIR", wx)
    monkeypatch.setattr(config, "RESULTS_DIR", data / "results")
    monkeypatch.setattr(config, "SFT_MODEL_PYTHON", str(BACKEND / "tests" / "support" / "python_fake_wind.sh"))
    monkeypatch.setattr(db, "DB_PATH", data / "test.db")
    hub.states.clear()
    tasks.manager = None
    log = tmp_path / "wind.log"
    monkeypatch.setenv("SFT_FAKE_WIND_LOG", str(log))
    with TestClient(app) as client:
        yield SimpleNamespace(client=client, cycle=cycle, launch=launch, wx=wx, results=data / "results", log=log,
                              day=day)
    hub.states.clear()
    tasks.manager = None
