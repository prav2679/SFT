import json
import time


def wait_job(client, sim_id, timeout=240):
    t0 = time.time()
    while time.time() - t0 < timeout:
        st = client.get(f"/api/burst/{sim_id}").json()
        if st["status"] in ("COMPLETED", "FAILED", "CANCELLED", "INTERRUPTED"):
            return st
        time.sleep(0.4)
    raise AssertionError(f"job {sim_id} did not finish")


def run_burst(client, params, cycle):
    r = client.post("/api/burst/run", json={"parameters": params, "forecast_cycle": cycle})
    assert r.status_code == 200, r.text
    st = wait_job(client, r.json()["simulation_id"])
    assert st["status"] == "COMPLETED", st
    return st["simulation_id"], client.get(f"/api/burst/{st['simulation_id']}/results").json()


def run_forward(client, params, cycle):
    r = client.post("/api/trajectory/forward", json={"engine": "sft", "sft_model": "hold_mission", "forward": params,
                                                     "forecast_cycle": cycle})
    assert r.status_code == 200, r.text
    st = wait_job(client, r.json()["simulation_id"])
    assert st["status"] == "COMPLETED", st
    return st["simulation_id"], client.get(f"/api/burst/{st['simulation_id']}/results").json()


def make_mission(client, mission_id, lat, lon, mode="LIVE", burst=True):
    r = client.post("/api/missions", json={"mission_id": mission_id, "mission_name": mission_id, "mode": mode,
                                           "launch_latitude": lat, "launch_longitude": lon, "launch_altitude": 20.0,
                                           "config": {"burst_expected": burst}})
    assert r.status_code == 200, r.text
    return r.json()


def manual(client, mission_id, **kw):
    body = {"timestamp_utc": None, "latitude": 0, "longitude": 0, "altitude_m": 0, "vertical_velocity": 0, "reforecast": False}
    body.update(kw)
    return client.post(f"/api/telemetry/manual/{mission_id}", json=body)


def wait_version(client, mission_id, sim_id):
    st = wait_job(client, sim_id)
    assert st["status"] == "COMPLETED", st
    return st["post_process"]
