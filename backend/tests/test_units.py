"""Unit tests: geodesic maths, descent-model compatibility, database migration."""
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))


def dms(d, m, s, neg=False):
    v = d + m / 60 + s / 3600
    return -v if neg else v


def test_geodesic_matches_vincenty_reference_and_is_not_a_degree_difference():
    from core.geo import geodesic_m, haversine_m
    flinders = (dms(37, 57, 3.72030, True), dms(144, 25, 29.52440))
    buninyong = (dms(37, 39, 10.15610, True), dms(143, 55, 35.38390))
    assert geodesic_m(*flinders, *buninyong) == pytest.approx(54972.271, abs=0.01)
    assert geodesic_m(0, 0, 0, 1) == pytest.approx(111319.491, abs=0.01)
    # 1 deg of longitude shrinks with latitude: a lat/lon subtraction would give the same number everywhere
    assert geodesic_m(60, 10, 60, 11) == pytest.approx(55800, rel=0.01)
    assert geodesic_m(1, 1, 1, 1) == 0.0
    assert abs(geodesic_m(10, 10, 20, 30) - haversine_m(10, 10, 20, 30)) / geodesic_m(10, 10, 20, 30) < 0.006


def _descent(pkg, **kw):
    code = (
        "import sys, json, io, contextlib; sys.path.insert(0, %r); import fake_tawhiri_wind; "
        "sys.modules['wind_model_time_dependent'] = fake_tawhiri_wind; sys.path.insert(0, %r); "
        "import descent_model_time_dependent as dm\n"
        "with contextlib.redirect_stdout(io.StringIO()):\n"
        "    t = dm.simulate_descent(burst_latitude=-33.8688, burst_longitude=151.2093, burst_altitude=%s, ground_altitude=50.0,"
        " payload_mass=5.0, parachute_diameter=2.4, parachute_cd=1.0, dt=10.0, burst_datetime='2026-11-07T04:00:00Z' %s)\n"
        "print(json.dumps([{k: p[k] for k in ('time_s','datetime_utc','latitude','longitude','altitude_m','vertical_velocity_mps','phase')} for p in t]))"
    )
    dirs = {"burst": BACKEND / "simulations/burst_calculator/codes",
            "forward": BACKEND / "simulations/trajectory_forward_reverse/simulation"}
    alt = kw.pop("alt", 26000.0)
    extra = "".join(f", {k}={v!r}" for k, v in kw.items())
    out = subprocess.run([sys.executable, "-c", code % (str(BACKEND / "tests/support"), str(dirs[pkg]), alt, extra)],
                         capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


@pytest.mark.parametrize("pkg", ["burst", "forward"])
def test_descent_model_default_behaviour_identical_to_pristine_original(pkg):
    golden = json.loads((BACKEND / "tests/golden/descent_default_golden.json").read_text())   # produced BEFORE the change
    assert _descent(pkg) == golden
    assert _descent(pkg, initial_vertical_velocity=0.0) == golden


def test_descent_initial_velocity_is_used_and_validated():
    rest = _descent("burst", alt=3000.0)
    fast = _descent("burst", alt=3000.0, initial_vertical_velocity=25.0)
    assert rest[0]["vertical_velocity_mps"] == 0.0 and fast[0]["vertical_velocity_mps"] == 25.0
    assert fast[-1]["time_s"] < rest[-1]["time_s"]                       # starting fast reaches the ground sooner
    with pytest.raises(subprocess.CalledProcessError):
        _descent("burst", initial_vertical_velocity=-3.0)


def test_preserved_originals_verification_script_passes():
    r = subprocess.run([sys.executable, str(BACKEND.parent / "scripts/verify_originals.py")], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout


def test_migration_is_idempotent_and_backfills_old_database(tmp_path, monkeypatch):
    from core import db
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.executescript(db.SCHEMA)                                     # database as shipped before this change
    conn.execute("INSERT INTO missions (mission_id,balloon_id,mission_name,mode,created_at) VALUES ('M','b','n','LIVE','2026-01-01T00:00:00Z')")
    for i, sid in enumerate(("PS-1", "PS-2")):
        conn.execute("INSERT INTO prediction_sets (prediction_set,mission_id,created_utc,source) VALUES (?,?,?,?)",
                     (sid, "M", f"2026-01-01T00:00:0{i}Z", "x"))
    conn.commit(); conn.close()
    monkeypatch.setattr(db, "DB_PATH", path)
    db.init_db(); db.init_db()
    assert db.query_one("PRAGMA user_version")["user_version"] == len(db.MIGRATIONS)
    rows = db.query("SELECT prediction_set, version, kind FROM prediction_sets ORDER BY version")
    assert rows == [{"prediction_set": "PS-1", "version": 1, "kind": "ORIGINAL"},
                    {"prediction_set": "PS-2", "version": 2, "kind": "ATTACHED"}]
    assert db.query_one("SELECT updated_at FROM missions")["updated_at"] == "2026-01-01T00:00:00Z"
