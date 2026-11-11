"""Backend tests that run WITHOUT the Tawhiri engine or a dataset.

    cd backend && python -m pytest -q tests
"""
import os, sys, tempfile, time
from datetime import datetime, timezone
from pathlib import Path

os.environ["SFT_DATA_DIR"] = tempfile.mkdtemp()
os.environ["TAWHIRI_DATA_DIR"] = tempfile.mkdtemp()
os.environ["TAWHIRI_API_URL"] = "http://127.0.0.1:9"      # unreachable on purpose
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402
from main import app  # noqa: E402

now = lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731


def client():
    return TestClient(app)


def test_status_reports_subsystems_separately():
    with client() as c:
        s = c.get("/api/tawhiri/status").json()
        assert s["weather_data"]["overall"] == "NO_VALID_DATA"
        assert s["engine"]["status"] == "UNREACHABLE"
        assert s["downloader"]["status"] == "IDLE"


def test_simulation_refuses_without_weather_data():
    with client() as c:
        p = c.get("/api/burst/defaults").json()["parameters"]
        assert "latitude" not in p and "longitude" not in p          # coordinates are never defaulted
        p.update(latitude=-33.8688, longitude=151.2093)              # supplied by the user
        r = c.post("/api/burst/run", json={"parameters": p})
        assert r.status_code == 409 and r.json()["detail"]["error_type"] == "WEATHER_DATA_UNAVAILABLE"


def test_invalid_burst_parameters_rejected():
    with client() as c:
        p = c.get("/api/burst/defaults").json()["parameters"]
        p.update(latitude=13.0827, longitude=80.2707)
        p["burst_altitude"] = 40000          # above safety ceiling
        assert c.post("/api/burst/run", json={"parameters": p}).status_code == 422


def test_telemetry_validation_pipeline():
    with client() as c:
        c.post("/api/missions", json={"mission_id": "T-LIVE", "mission_name": "t", "mode": "LIVE",
                                     "launch_latitude": 13.08, "launch_longitude": 80.27, "launch_altitude": 87})
        ok = c.post("/api/telemetry/ingest", json={"mission_id": "T-LIVE", "packet_id": 1, "timestamp_utc": now(),
                    "data_source": "MEASURED", "payload": {"latitude": 13.08, "longitude": 80.27, "gps_altitude": 90,
                    "ambient_temperature": 300.15}, "units": {"ambient_temperature": "K"}}).json()
        assert ok["accepted"] and ok["quality"] == "VALID"
        latest = c.get("/api/telemetry/latest/T-LIVE").json()
        assert abs(latest["payload"]["ambient_temperature"] - 27.0) < 1e-6        # K -> degC
        assert latest["payload"]["relative_humidity"] if "relative_humidity" in latest["payload"] else True
        dup = c.post("/api/telemetry/ingest", json={"mission_id": "T-LIVE", "packet_id": 1, "timestamp_utc": now(),
                     "data_source": "MEASURED", "payload": {}}).json()
        assert dup["code"] == "DUPLICATE"
        fut = c.post("/api/telemetry/ingest", json={"mission_id": "T-LIVE", "packet_id": 2,
                     "timestamp_utc": "2099-01-01T00:00:00Z", "data_source": "MEASURED", "payload": {}}).json()
        assert fut["code"] == "BAD_TIMESTAMP"
        mix = c.post("/api/telemetry/ingest", json={"mission_id": "T-LIVE", "packet_id": 3, "timestamp_utc": now(),
                     "data_source": "SIMULATED", "payload": {}}).json()
        assert mix["code"] == "SOURCE_MISMATCH"
        time.sleep(1.1)
        bad = c.post("/api/telemetry/ingest", json={"mission_id": "T-LIVE", "packet_id": 4, "timestamp_utc": now(),
                     "data_source": "MEASURED", "payload": {"latitude": 95, "longitude": 80, "battery_voltage": 6.0}}).json()
        assert bad["quality"] == "INVALID" and not bad["live"]
        time.sleep(1.1)
        c.post("/api/telemetry/ingest", json={"mission_id": "T-LIVE", "packet_id": 5, "timestamp_utc": now(),
               "data_source": "MEASURED", "payload": {"latitude": 13.08, "longitude": 80.27, "battery_voltage": 6.0,
               "gps_fix": True}})
        alerts = c.get("/api/telemetry/alerts/T-LIVE").json()
        assert any(a["parameter"] == "battery_voltage" and a["severity"] == "CRITICAL" for a in alerts)


def test_simulation_mode_and_comparison():
    with client() as c:
        c.post("/api/missions", json={"mission_id": "T-SIM", "mission_name": "s", "mode": "SIMULATION",
                                     "launch_latitude": 13.0827, "launch_longitude": 80.2707, "launch_altitude": 87})
        r = c.post("/api/missions/T-SIM/simulation/start", json={"speed": 500, "interval_s": 60,
                   "scenarios": [{"type": "altitude_deviation", "start": 0.2, "end": 0.4, "magnitude": -1500}]})
        assert r.status_code == 200
        for _ in range(60):
            time.sleep(0.5)
            if c.get("/api/missions/T-SIM/simulation").json()["state"].startswith("COMPLETED"):
                break
        st = c.get("/api/telemetry/status/T-SIM").json()
        assert st["packet_count"] > 50 and st["flight_phase"] == "DESCENT"
        cmp = c.get("/api/telemetry/comparison/T-SIM").json()
        assert cmp["available"] and cmp["statistics"]["max_abs_altitude_error_m"] > 500
        alerts = c.get("/api/telemetry/alerts/T-SIM").json()
        assert any(a["parameter"] == "altitude_deviation" for a in alerts)
        assert not any(a["parameter"] == "vertical_velocity" for a in alerts)   # burst is expected for latex
