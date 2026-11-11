"""TEST 4 - user-supplied coordinates reach the scientific models; nothing falls back to Chennai."""
import json

from conftest import CHENNAI, SYDNEY, burst_params, forward_params
from helpers import run_burst, run_forward, wait_job


def wind_calls(path):
    return [json.loads(l) for l in open(path)] if path.exists() else []


def test_missing_coordinates_are_rejected_not_defaulted(env):
    c = env.client
    p = burst_params(*SYDNEY, env.launch)
    del p["latitude"]
    r = c.post("/api/burst/run", json={"parameters": p, "forecast_cycle": env.cycle})
    assert r.status_code == 422 and "latitude" in json.dumps(r.json())
    r = c.post("/api/diurnal/run", json={"balloon": {"initial_longitude_deg": 10.0}, "mission": {}})
    assert r.status_code == 422 and "latitude" in r.json()["detail"]["message"].lower()
    r = c.post("/api/diurnal/run", json={"balloon": {"initial_latitude_deg": 91, "initial_longitude_deg": 10}, "mission": {}})
    assert r.status_code == 422
    r = c.post("/api/missions", json={"mission_name": "x", "mode": "LIVE"})
    assert r.status_code == 422
    f = forward_params(*SYDNEY, env.launch)
    f["launch_longitude"] = 181
    assert c.post("/api/trajectory/forward", json={"engine": "sft", "forward": f}).status_code == 422
    assert c.get("/api/diurnal/defaults").json()["balloon"].get("initial_latitude_deg") is None


def test_chennai_and_other_coordinates_each_reach_the_model(env, monkeypatch, tmp_path):
    c = env.client
    results = {}
    for name, (lat, lon) in (("chennai", CHENNAI), ("sydney", SYDNEY), ("reykjavik", (64.1466, -21.9426))):
        log = tmp_path / f"{name}.log"
        monkeypatch.setenv("SFT_FAKE_WIND_LOG", str(log))
        _, res = run_burst(c, burst_params(lat, lon, env.launch), env.cycle)
        calls = wind_calls(log)
        first = res["trajectory"][0]
        assert abs(first["lat"] - lat) < 0.01 and abs(first["lon"] - lon) < 0.01, (name, first)
        assert calls[0]["lat"] == lat and calls[0]["lon"] == lon           # very first atmosphere query = user input
        # the whole flight stays near the user's launch point (<3 deg of a ~1 h balloon drift)
        assert all(abs(q["lat"] - lat) < 3 and abs(q["lon"] - lon) < 3 for q in calls), name
        results[name] = (lat, lon, res["trajectory"][-1])
    assert results["chennai"][2]["lat"] > 10 and results["sydney"][2]["lat"] < -30        # no cross-contamination
    assert abs(results["reykjavik"][2]["lon"] + 22) < 3


def test_forward_hold_uses_supplied_launch(env, monkeypatch, tmp_path):
    log = tmp_path / "fwd.log"
    monkeypatch.setenv("SFT_FAKE_WIND_LOG", str(log))
    _, res = run_forward(env.client, forward_params(*SYDNEY, env.launch), env.cycle)
    assert abs(res["trajectory"][0]["lat"] - SYDNEY[0]) < 1e-6
    assert all(abs(q["lat"] - SYDNEY[0]) < 3 for q in wind_calls(log))


def test_reverse_target_coordinates_reach_the_model(env, monkeypatch, tmp_path):
    log = tmp_path / "rev.log"
    monkeypatch.setenv("SFT_FAKE_WIND_LOG", str(log))
    body = {"engine": "sft", "forecast_cycle": env.cycle, "reverse": {
        "target_latitude": SYDNEY[0], "target_longitude": SYDNEY[1],
        "target_landing_datetime": f"{env.day.isoformat()}T09:00:00Z", "target_altitude_m": 20000,
        "hold_duration_hours": 1.0, "ascent_rate_mps": 5.0, "payload_mass_kg": 5.0}}
    r = env.client.post("/api/trajectory/reverse", json=body)
    assert r.status_code == 200, r.text
    st = wait_job(env.client, r.json()["simulation_id"])
    assert st["status"] == "COMPLETED", st
    res = env.client.get(f"/api/burst/{st['simulation_id']}/results").json()
    assert res["target"]["latitude"] == SYDNEY[0] and res["target"]["longitude"] == SYDNEY[1]
    assert all(abs(q["lat"] - SYDNEY[0]) < 3 for q in wind_calls(log))


def test_simulation_refuses_source_from_another_location(env):
    """The recorded (Chennai) trajectory must not silently drive a mission launched elsewhere."""
    from conftest import SYDNEY
    from helpers import make_mission
    make_mission(env.client, "M-SYD", *SYDNEY, mode="SIMULATION")
    r = env.client.post("/api/missions/M-SYD/simulation/start", json={"source": "recorded", "speed": 500})
    assert r.status_code == 409 and "km from this mission's launch point" in r.text
