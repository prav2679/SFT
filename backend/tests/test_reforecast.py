"""TEST 2 / TEST 3 - telemetry-driven re-forecast, prediction versions and flight-phase handling."""
import hashlib
import json

import pytest

from conftest import SYDNEY, burst_params, forward_params
from helpers import make_mission, manual, run_burst, run_forward, wait_job


def digest(track):
    return hashlib.sha256(json.dumps(track, sort_keys=True).encode()).hexdigest()


def point_at(traj, phase, alt_lo=0, alt_hi=1e9):
    return next(p for p in traj if p["phase"] == phase and alt_lo < p["alt"] < alt_hi)


def setup_burst_mission(env, mid="M-R"):
    c = env.client
    sim_id, res = run_burst(c, burst_params(*SYDNEY, env.launch), env.cycle)
    make_mission(c, mid, *SYDNEY)
    assert c.post(f"/api/missions/{mid}/predictions", json={"simulation_id": sim_id}).status_code == 200
    return sim_id, res["trajectory"]


def finish(env, r):
    assert r.status_code == 200, r.text
    rf = r.json()["reforecast"]
    assert rf["submitted"], rf
    return wait_job(env.client, rf["job"]["simulation_id"])


def test_ascent_reforecast_creates_versions_and_preserves_original(env):
    c = env.client
    _, traj = setup_burst_mission(env)
    v1 = c.get("/api/telemetry/flight-view/M-R").json()
    assert v1["versions"][0]["kind"] == "ORIGINAL" and v1["versions"][0]["version"] == 1
    original_digest = digest(v1["original"]["track"])

    a = point_at(traj, "ascent", 9000, 11000)
    r = manual(c, "M-R", timestamp_utc=a["t"], latitude=a["lat"] + .02, longitude=a["lon"] + .03,
               altitude_m=a["alt"] - 300, vertical_velocity=6.2, horizontal_velocity=9.1, wind_speed=11, wind_direction=250,
               reforecast=True)
    assert r.json()["phase"]["used"] == "ASCENT" and r.json()["phase"]["source"] == "AUTO"
    st = finish(env, r)
    assert st["post_process"]["status"] == "OK" and st["post_process"]["version"] == 2

    view = c.get("/api/telemetry/flight-view/M-R").json()
    assert [v["version"] for v in view["versions"]] == [1, 2]
    rev = view["revised"]["track"]
    assert view["revised"]["summary"]["kind"] == "REVISED"
    # revised trajectory begins at the ACTUAL telemetry position (not the launch point)
    assert abs(rev[0]["lat"] - (a["lat"] + .02)) < 1e-6 and abs(rev[0]["lon"] - (a["lon"] + .03)) < 1e-6
    assert abs(rev[0]["alt"] - (a["alt"] - 300)) < 1e-6
    assert abs(rev[0]["lat"] - SYDNEY[0]) > 0.01 or abs(rev[0]["alt"] - 20) > 1000
    # ORIGINAL unchanged
    assert digest(view["original"]["track"]) == original_digest
    # actual layer + comparison block
    assert len(view["actual"]["points"]) == 1 and view["actual"]["latest"]["entry_method"] == "MANUAL"
    comp = view["comparison"]
    assert comp["landing_shift_m"] >= 0 and comp["revised_landing"] and comp["original_landing"]
    assert comp["revised_remaining_duration_s"] > 0 and comp["trajectory_displacement"]["max_m"] >= 0

    # second update -> V3; V2 still stored and untouched
    b = point_at(traj, "ascent", 18000, 20000)
    v2_before = digest(c.get("/api/telemetry/flight-view/M-R", params={"version": 2}).json()["revised"]["track"])
    st = finish(env, manual(c, "M-R", timestamp_utc=b["t"], latitude=b["lat"] + .04, longitude=b["lon"] + .05,
                            altitude_m=b["alt"] - 500, vertical_velocity=6.0, reforecast=True))
    assert st["post_process"]["version"] == 3
    view = c.get("/api/telemetry/flight-view/M-R").json()
    assert [v["version"] for v in view["versions"]] == [1, 2, 3] and view["selected_version"] == 3
    assert digest(c.get("/api/telemetry/flight-view/M-R", params={"version": 2}).json()["revised"]["track"]) == v2_before
    assert digest(view["original"]["track"]) == original_digest
    assert view["versions"][2]["parent_set"] == view["versions"][1]["prediction_set"]
    # error series (geodesic) needs >= 2 samples
    assert view["error_series"]["sufficient"] and all(e["horizontal_error_m"] >= 0 for e in view["error_series"]["original"])
    # re-submitting the same telemetry does not create a duplicate version
    tid = view["actual"]["latest"]["telemetry_id"]
    again = c.post("/api/telemetry/reforecast/M-R", json={"telemetry_id": tid}).json()
    assert again["submitted"] is False and again["version"] == 3


def test_database_enforces_immutability(env):
    from core import db
    _, traj = setup_burst_mission(env)
    ps = db.query_one("SELECT prediction_set FROM prediction_sets WHERE kind='ORIGINAL'")["prediction_set"]
    for sql in (f"UPDATE predictions SET predicted_latitude=0 WHERE prediction_set='{ps}'",
                f"DELETE FROM predictions WHERE prediction_set='{ps}'",
                f"UPDATE prediction_sets SET source='x' WHERE prediction_set='{ps}'",
                f"DELETE FROM prediction_sets WHERE prediction_set='{ps}'"):
        with pytest.raises(Exception, match="IMMUTABLE"):
            db.execute(sql)
    a = point_at(traj, "ascent", 5000, 6000)
    manual(env.client, "M-R", timestamp_utc=a["t"], latitude=a["lat"], longitude=a["lon"], altitude_m=a["alt"], vertical_velocity=6.5)
    with pytest.raises(Exception, match="IMMUTABLE"):
        db.execute("UPDATE telemetry SET latitude=1 WHERE mission_id='M-R'")
    with pytest.raises(ValueError, match="already has an original"):
        from core import predictions
        predictions.store_prediction("M-R", traj[:5], "x", None, None, kind="ORIGINAL")


def test_descent_reforecast_uses_observed_state_and_descent_model(env):
    c = env.client
    _, traj = setup_burst_mission(env)
    d = point_at(traj, "descent", 5000, 15000)
    r = manual(c, "M-R", timestamp_utc=d["t"], latitude=d["lat"] + .01, longitude=d["lon"] - .02, altitude_m=d["alt"] + 120,
               vertical_velocity=-18.0, reforecast=True)
    assert r.json()["phase"]["used"] == "DESCENT"
    st = finish(env, r)
    res = c.get(f"/api/burst/{st['simulation_id']}/results").json()
    assert res["phase"] == "DESCENT" and res["engine"].startswith("simulate_descent")
    assert res["initial_descent_speed_mps"] == 18.0
    t = res["trajectory"]
    assert t[0]["alt"] == d["alt"] + 120 and t[-1]["phase"] == "landing" and t[-1]["alt"] <= 21
    assert {p["phase"] for p in t} <= {"telemetry", "descent", "landing"}            # no ascent/burst rows
    assert all(p["alt"] <= d["alt"] + 120 + 1e-6 for p in t)                          # monotonically below the observed altitude
    assert c.get("/api/telemetry/flight-view/M-R").json()["revised"]["summary"]["anchor_phase"] == "DESCENT"


def test_float_reforecast_holds_at_observed_altitude_then_descends(env):
    c = env.client
    sim_id, res = run_forward(c, forward_params(*SYDNEY, env.launch), env.cycle)
    traj = res["trajectory"]
    make_mission(c, "M-F", *SYDNEY, burst=False)
    assert c.post("/api/missions/M-F/predictions", json={"simulation_id": sim_id}).status_code == 200
    hold = [p for p in traj if p["phase"] == "altitude_hold"]
    h = hold[len(hold) // 3]
    r = manual(c, "M-F", timestamp_utc=h["t"], latitude=h["lat"] + .05, longitude=h["lon"] + .05, altitude_m=24700,
               vertical_velocity=0.2, reforecast=True)
    assert r.json()["phase"]["used"] == "FLOAT", r.text
    st = finish(env, r)
    out = c.get(f"/api/burst/{st['simulation_id']}/results").json()
    t = out["trajectory"]
    assert out["phase"] == "FLOAT" and out["engine"] == "flight_forward.simulate_mission"
    assert t[0]["alt"] == 24700 and abs(t[0]["lat"] - (h["lat"] + .05)) < 1e-6
    held = [p for p in t if p["phase"] == "altitude_hold"]
    assert held and {round(p["alt"]) for p in held} == {24700}
    assert held[-1]["t"][:19] == hold[-1]["t"][:19]                                   # planned end of float retained
    assert t[-1]["phase"] == "landing"
    # float telemetry never goes through the ascent/burst model
    assert not any(p["phase"] in ("burst",) for p in t)


def test_phase_and_velocity_must_agree_and_override_is_validated(env):
    c = env.client
    make_mission(c, "M-V", *SYDNEY)
    base = dict(timestamp_utc=f"{env.day.isoformat()}T01:00:00Z", latitude=-33.5, longitude=151.5, altitude_m=9000)
    r = manual(c, "M-V", **base, vertical_velocity=-8.0, flight_phase="ASCENT")
    assert r.status_code == 422 and "contradicts" in r.json()["detail"]["message"]
    r = manual(c, "M-V", **base, vertical_velocity=7.0, flight_phase="DESCENT")
    assert r.status_code == 422
    r = manual(c, "M-V", **base, vertical_velocity=0.4)       # ambiguous at 9 km (not float: < 5 km above launch is false -> FLOAT)
    assert r.status_code == 200 and r.json()["phase"]["used"] == "FLOAT"
    r = manual(c, "M-V", timestamp_utc=f"{env.day.isoformat()}T01:05:00Z", latitude=-33.5, longitude=151.5,
               altitude_m=900, vertical_velocity=-1.5)       # ambiguous low altitude, slow sink
    assert r.status_code == 422 and r.json()["detail"]["error_type"] == "PHASE_UNDETERMINED"
    r = manual(c, "M-V", timestamp_utc=f"{env.day.isoformat()}T01:05:00Z", latitude=-33.5, longitude=151.5,
               altitude_m=900, vertical_velocity=-1.5, flight_phase="DESCENT")
    assert r.status_code == 200 and r.json()["phase"]["source"] == "OVERRIDE"
    prev = c.get("/api/telemetry/phase-preview/M-V", params={"vertical_velocity": 6, "altitude": 3000}).json()
    assert prev["phase"] == "ASCENT"


def test_validation_duplicates_out_of_order_and_correction_workflow(env):
    from core import db
    c = env.client
    make_mission(c, "M-X", *SYDNEY)
    t = lambda m: f"{env.day.isoformat()}T{m // 60:02d}:{m % 60:02d}:00Z"          # noqa: E731
    ok = dict(latitude=-33.5, longitude=151.5, altitude_m=3000, vertical_velocity=5.0)
    assert manual(c, "M-X", timestamp_utc=t(10), **{**ok, "latitude": 91}).status_code == 422
    assert manual(c, "M-X", timestamp_utc=t(10), **{**ok, "longitude": -181}).status_code == 422
    assert manual(c, "M-X", timestamp_utc=t(10), **{**ok, "altitude_m": 70000}).status_code == 422
    assert manual(c, "M-X", timestamp_utc=t(10), **{**ok, "altitude_m": -900}).status_code == 422
    assert manual(c, "M-X", timestamp_utc="not-a-time", **ok).status_code in (422,)
    assert manual(c, "M-X", timestamp_utc="2099-01-01T00:00:00Z", **ok).status_code == 422       # future (MEASURED)
    assert manual(c, "M-X", timestamp_utc=t(10), **{**ok, "wind_direction": 400}).status_code == 422
    first = manual(c, "M-X", timestamp_utc=t(20), **ok)
    assert first.status_code == 200
    tid = first.json()["telemetry_id"]
    # same timestamp, different values -> conflict, nothing overwritten
    clash = manual(c, "M-X", timestamp_utc=t(20), **{**ok, "altitude_m": 3500})
    assert clash.status_code == 409 and "correction workflow" in clash.json()["detail"]["message"]
    assert db.query_one("SELECT gps_altitude FROM telemetry WHERE telemetry_id=?", (tid,))["gps_altitude"] == 3000
    # earlier than the latest -> stored for audit, flagged, never live, no re-forecast
    late = manual(c, "M-X", timestamp_utc=t(30), **{**ok, "altitude_m": 4000})
    early = manual(c, "M-X", timestamp_utc=t(25), **{**ok, "altitude_m": 3600}, reforecast=True)
    assert early.json()["live"] is False and "OUT_OF_ORDER" in early.json()["quality_flags"]
    assert early.json()["reforecast"]["submitted"] is False
    pts = c.get("/api/telemetry/flight-view/M-X").json()["actual"]["points"]
    assert [p["t"][11:16] for p in pts] == ["00:20", "00:30"]                # out-of-order record is not on the track
    # explicit correction: requires a reason, supersedes (never edits) the old record
    assert manual(c, "M-X", timestamp_utc=t(20), **{**ok, "altitude_m": 3100}, correction_of=tid).status_code == 409
    fixed = manual(c, "M-X", timestamp_utc=t(20), **{**ok, "altitude_m": 3100}, correction_of=tid,
                   correction_reason="GPS altitude typed incorrectly")
    assert fixed.status_code == 200, fixed.text
    old = db.query_one("SELECT gps_altitude, superseded_by FROM telemetry WHERE telemetry_id=?", (tid,))
    assert old["gps_altitude"] == 3000 and old["superseded_by"] == fixed.json()["telemetry_id"]
    pts = c.get("/api/telemetry/flight-view/M-X").json()["actual"]["points"]
    assert [round(p["alt"]) for p in pts] == [3100, 4000]
    assert manual(c, "M-X", timestamp_utc=t(20), **ok, correction_of=tid,
                  correction_reason="again").status_code == 409            # already corrected


def test_reforecast_without_context_keeps_telemetry_and_explains(env):
    c = env.client
    make_mission(c, "M-N", *SYDNEY)
    r = manual(c, "M-N", timestamp_utc=f"{env.day.isoformat()}T01:00:00Z", latitude=-33.5, longitude=151.5,
               altitude_m=9000, vertical_velocity=6.0, reforecast=True)
    assert r.status_code == 200 and r.json()["reforecast"]["submitted"] is False
    assert r.json()["reforecast"]["error"]["error_type"] == "NO_ORIGINAL_PREDICTION"


def test_actual_landing_comparison(env):
    c = env.client
    _, traj = setup_burst_mission(env)
    a = point_at(traj, "ascent", 9000, 11000)
    finish(env, manual(c, "M-R", timestamp_utc=a["t"], latitude=a["lat"] + .02, longitude=a["lon"] + .03,
                       altitude_m=a["alt"] - 300, vertical_velocity=6.2, reforecast=True))
    land = traj[-1]
    r = manual(c, "M-R", timestamp_utc=land["t"], latitude=land["lat"] + .03, longitude=land["lon"] + .04, altitude_m=25,
               vertical_velocity=0.0, flight_phase="LANDED")
    assert r.status_code == 200, r.text
    comp = c.get("/api/telemetry/flight-view/M-R").json()["comparison"]
    assert comp["actual_landing"] and comp["actual_vs_original_landing_error_m"] > 0 and comp["actual_vs_revised_landing_error_m"] > 0
