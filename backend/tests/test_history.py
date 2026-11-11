"""TEST 1 - mission history management."""
import json
from datetime import datetime, timedelta, timezone

from conftest import SYDNEY, burst_params
from helpers import make_mission, manual, run_burst


def ts(env, minutes):
    return f"{env.day.isoformat()}T{minutes // 60:02d}:{minutes % 60:02d}:00Z"


def counts(mission_id):
    from core import db
    return {t: db.query_one(f"SELECT COUNT(*) n FROM {t} WHERE mission_id=?", (mission_id,))["n"]
            for t in ("telemetry", "alerts", "predictions", "prediction_sets", "simulations", "missions")}


def fly(env, mid, land=False):
    """Active ascent (and optionally landing) via manual telemetry."""
    c = env.client
    assert manual(c, mid, timestamp_utc=ts(env, 10), latitude=SYDNEY[0], longitude=SYDNEY[1], altitude_m=6000,
                  vertical_velocity=5.5).status_code == 200
    if land:
        r = manual(c, mid, timestamp_utc=ts(env, 130), latitude=SYDNEY[0] + .1, longitude=SYDNEY[1] + .1, altitude_m=22,
                   vertical_velocity=0.0, flight_phase="LANDED")
        assert r.status_code == 200, r.text


def land(env, mid):
    r = manual(env.client, mid, timestamp_utc=ts(env, 130), latitude=SYDNEY[0] + .1, longitude=SYDNEY[1] + .1,
               altitude_m=22, vertical_velocity=0.0, flight_phase="LANDED")
    assert r.status_code == 200, r.text


def test_delete_one_keeps_other_and_removes_all_associated_records(env):
    c = env.client
    sim_id, _ = run_burst(c, burst_params(*SYDNEY, env.launch), env.cycle)
    for mid in ("M-A", "M-B"):
        make_mission(c, mid, *SYDNEY)
        assert c.post(f"/api/missions/{mid}/predictions", json={"simulation_id": sim_id}).status_code == 200
        fly(env, mid)
    # a per-mission re-forecast job (telemetry-triggered) belongs to the mission and must be deleted with it
    r = manual(c, "M-A", timestamp_utc=ts(env, 40), latitude=SYDNEY[0], longitude=SYDNEY[1] + .2, altitude_m=12000,
               vertical_velocity=5.0, reforecast=True)
    assert r.status_code == 200 and r.json()["reforecast"]["submitted"], r.text
    from helpers import wait_job
    job = r.json()["reforecast"]["job"]["simulation_id"]
    assert wait_job(c, job)["status"] == "COMPLETED"
    for mid in ("M-A", "M-B"):
        land(env, mid)
    before_b = counts("M-B")
    assert before_b["telemetry"] >= 2 and before_b["prediction_sets"] == 1 and before_b["predictions"] > 10
    job_dir = env.results / job
    assert job_dir.exists()
    (env.wx / "marker").write_text("shared weather must survive")

    r = c.delete("/api/missions/M-A")
    assert r.status_code == 200, r.text
    assert all(v == 0 for v in counts("M-A").values()), counts("M-A")
    assert not job_dir.exists()                                            # re-forecast result files removed
    assert counts("M-B") == before_b                                       # other mission intact
    assert (env.wx / "marker").exists() and (env.wx / env.cycle).exists()  # shared weather untouched
    assert c.get("/api/simulations").status_code in (200, 404)
    assert c.get(f"/api/burst/{sim_id}").json()["status"] == "COMPLETED"   # shared calculator job untouched
    assert c.get("/api/missions/M-A").status_code == 404
    assert [m["mission_id"] for m in c.get("/api/missions").json()] == ["M-B"]


def test_active_mission_cannot_be_deleted_until_terminated(env):
    c = env.client
    make_mission(c, "M-LIVE", *SYDNEY)
    fly(env, "M-LIVE")
    m = c.get("/api/missions/M-LIVE").json()
    assert m["lifecycle_status"] == "ACTIVE" and m["active"]
    r = c.delete("/api/missions/M-LIVE")
    assert r.status_code == 409 and r.json()["detail"]["error_type"] == "MISSION_ACTIVE"
    # bulk operations skip active missions as well
    r = c.delete("/api/missions", params={"scope": "all", "confirm": True})
    assert r.json()["skipped_active"] == ["M-LIVE"] and r.json()["deleted"] == []
    assert c.post("/api/missions/M-LIVE/abort").status_code == 200
    assert c.get("/api/missions/M-LIVE").json()["lifecycle_status"] == "ABORTED"
    assert c.delete("/api/missions/M-LIVE").status_code == 200


def test_clear_completed_and_clear_all_confirmation(env):
    c = env.client
    make_mission(c, "M-DONE", *SYDNEY); fly(env, "M-DONE", land=True)          # COMPLETED (landed)
    make_mission(c, "M-ACT", *SYDNEY); fly(env, "M-ACT")                      # ACTIVE
    make_mission(c, "M-NEW", *SYDNEY)                                         # PRE-LAUNCH
    status = {m["mission_id"]: m["lifecycle_status"] for m in c.get("/api/missions").json()}
    assert status == {"M-DONE": "COMPLETED", "M-ACT": "ACTIVE", "M-NEW": "PRE-LAUNCH"}
    r = c.delete("/api/missions", params={"scope": "completed"}).json()
    assert r["deleted"] == ["M-DONE"] and r["skipped_active"] == ["M-ACT"]
    assert all(v == 0 for v in counts("M-DONE").values())
    assert c.delete("/api/missions", params={"scope": "all"}).status_code == 422          # needs explicit confirmation
    r = c.delete("/api/missions", params={"scope": "all", "confirm": True}).json()
    assert r["deleted"] == ["M-NEW"] and r["skipped_active"] == ["M-ACT"]
    listing = c.get("/api/missions").json()
    assert [m["mission_id"] for m in listing] == ["M-ACT"]
    row = listing[0]
    for key in ("mission_id", "mission_name", "launch_latitude", "launch_longitude", "created_at", "lifecycle_status",
                "mission_type", "last_updated"):
        assert row[key] is not None, key
