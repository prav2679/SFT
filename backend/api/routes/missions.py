"""Mission management, prediction attachment and simulation-mode control."""
from __future__ import annotations

import json
import shutil
import uuid

from fastapi import APIRouter, HTTPException, Query

import config

from api.schemas import AttachPrediction, MissionCreate, MissionUpdate, SimulationStart
from core import db, lifecycle, predictions, simulator
from core.comparison import store_prediction
from core.db import iso, utcnow
from core.tasks import get_manager
from core.telemetry import DEFAULT_CONFIG, FIELDS, PHASES, hub, merge_config

router = APIRouter(prefix="/api/missions", tags=["missions"])


def _mission(mission_id: str) -> dict:
    m = db.query_one("SELECT * FROM missions WHERE mission_id=?", (mission_id,))
    if not m:
        raise HTTPException(404, f"Unknown mission {mission_id}")
    m["config"] = merge_config(json.loads(m.pop("config_json") or "{}"))
    return m


@router.get("")
def list_missions():
    rows = db.query("SELECT * FROM missions ORDER BY created_at DESC")
    for r in rows:
        raw_cfg = json.loads(r["config_json"] or "{}")
        lifecycle.decorate(r, raw_cfg)
        r.pop("config_json")
        r["config"] = merge_config(raw_cfg)
        r["telemetry"] = {k: v for k, v in hub.snapshot(r["mission_id"]).items() if k != "latest"}
        r["packet_count"] = r["telemetry"].get("packet_count", 0)
        r["prediction_versions"] = db.query_one("SELECT COUNT(*) AS n FROM prediction_sets WHERE mission_id=?",
                                                (r["mission_id"],))["n"]
    return rows


@router.get("/catalogue")
def catalogue():
    return {"fields": {k: {"group": g, "unit": u, "label": l} for k, (g, u, l) in FIELDS.items()},
            "phases": PHASES, "default_config": DEFAULT_CONFIG, "scenarios": simulator.SCENARIOS}


@router.post("")
def create(m: MissionCreate):
    mission_id = m.mission_id or f"SFT-{utcnow():%Y%m%d}-{uuid.uuid4().hex[:4].upper()}"
    if db.query_one("SELECT 1 FROM missions WHERE mission_id=?", (mission_id,)):
        raise HTTPException(409, "Mission ID already exists")
    cfg = merge_config(m.config)
    if m.mode == "SIMULATION":
        cfg["simulation_note"] = ("Payload-health values (battery, payload temperature, uptime) in this mission are "
                                  "produced by a synthetic generator, not an SFT model.")
    db.execute("INSERT INTO missions (mission_id, balloon_id, mission_name, mode, launch_time, launch_latitude, "
               "launch_longitude, launch_altitude, config_json, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
               (mission_id, m.balloon_id, m.mission_name, m.mode, m.launch_time, m.launch_latitude,
                m.launch_longitude, m.launch_altitude, json.dumps(cfg), iso(utcnow()), iso(utcnow())))
    return _mission(mission_id)


@router.get("/{mission_id}")
def get(mission_id: str):
    m = _mission(mission_id)
    lifecycle.decorate(m, m["config"])
    m["telemetry"] = hub.snapshot(mission_id)
    m["simulation"] = simulator.status(mission_id)
    m["prediction_sets"] = db.query("SELECT * FROM prediction_sets WHERE mission_id=? ORDER BY created_utc DESC",
                                    (mission_id,))
    return m


@router.patch("/{mission_id}")
def update(mission_id: str, u: MissionUpdate):
    m = _mission(mission_id)
    fields = {k: v for k, v in u.model_dump().items() if v is not None and k != "config"}
    if u.config is not None:
        cfg = m["config"]
        for k, v in u.config.items():
            if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                cfg[k].update(v)
            else:
                cfg[k] = v
        fields["config_json"] = json.dumps(cfg)
    if fields:
        fields["updated_at"] = iso(utcnow())
        sets = ", ".join(f"{k}=?" for k in fields)
        db.execute(f"UPDATE missions SET {sets} WHERE mission_id=?", (*fields.values(), mission_id))
        hub.reload(mission_id)
    return get(mission_id)


@router.post("/{mission_id}/abort")
async def abort(mission_id: str):
    """Marks the mission ABORTED in the ground segment only. No command is sent to the balloon."""
    st = hub.state(mission_id)
    if simulator.status(mission_id) and simulator.status(mission_id).get("state") in ("RUNNING", "PAUSED"):
        simulator.stop(mission_id)                      # terminating also stops the simulated telemetry feed
    ev = hub.set_phase(st, "ABORTED", iso(utcnow()))
    await hub.broadcast(mission_id, {"type": "alert", "alert": ev})
    await hub.broadcast(mission_id, {"type": "status", **hub.snapshot(mission_id)})
    return get(mission_id)


def _purge_job_dirs(job_ids: list[str]):
    for jid in job_ids:                                  # per-mission re-forecast results only; never weather data
        shutil.rmtree(config.RESULTS_DIR / jid, ignore_errors=True)


def _delete_missions(ids: list[str]) -> dict:
    out = db.delete_mission_records(ids)                 # one transaction, explicit cascade
    _purge_job_dirs(out["job_ids"])
    for mid in ids:
        st = hub.states.pop(mid, None)
        if st:
            st.subscribers.clear()
    return out["counts"]


@router.delete("/{mission_id}")
def delete(mission_id: str):
    """Delete one mission and everything recorded for it. Active missions must be terminated first."""
    m = _mission(mission_id)
    lc = lifecycle.lifecycle(db.query_one("SELECT * FROM missions WHERE mission_id=?", (mission_id,)))
    if lc["active"]:
        raise HTTPException(409, {"error_type": "MISSION_ACTIVE", "message":
                                  f"Mission {mission_id} is active. Terminate it first (POST /api/missions/"
                                  f"{mission_id}/abort), then delete it."})
    counts = _delete_missions([mission_id])
    return {"deleted": mission_id, "counts": counts}


@router.delete("")
def clear(scope: str = Query(..., pattern="^(completed|all)$"), confirm: bool = False):
    """Clear mission history. scope=completed removes COMPLETED/ABORTED missions; scope=all removes every
    non-active mission and additionally requires confirm=true. Active missions are always skipped."""
    if scope == "all" and not confirm:
        raise HTTPException(422, {"error_type": "CONFIRMATION_REQUIRED",
                                  "message": "Clearing all mission history requires confirm=true."})
    rows = db.query("SELECT * FROM missions")
    targets, skipped = [], []
    for r in rows:
        lc = lifecycle.lifecycle(r)
        if lc["active"]:
            skipped.append(r["mission_id"])
        elif scope == "all" or lc["status"] in ("COMPLETED", "ABORTED"):
            targets.append(r["mission_id"])
    counts = _delete_missions(targets) if targets else {}
    return {"scope": scope, "deleted": targets, "skipped_active": skipped, "counts": counts}


@router.post("/{mission_id}/predictions")
def attach_prediction(mission_id: str, body: AttachPrediction):
    _mission(mission_id)
    res = get_manager().result(body.simulation_id)
    if not res or not res.get("trajectory"):
        raise HTTPException(409, "Simulation has no completed trajectory")
    set_id = store_prediction(mission_id, res["trajectory"], source=f"{res.get('model')} job {body.simulation_id}",
                              model_version=res.get("model_version"), forecast_cycle=res.get("forecast_cycle"),
                              metadata={"simulation_id": body.simulation_id, "model": res.get("model")})
    hub.reload(mission_id)
    return {"prediction_set": set_id}


# ------------------------------------------------------------ simulation mode
@router.post("/{mission_id}/simulation/start")
async def sim_start(mission_id: str, body: SimulationStart):
    _mission(mission_id)
    for s in body.scenarios:
        if s.get("type") not in simulator.SCENARIOS:
            raise HTTPException(422, f"Unknown scenario {s.get('type')}")
    try:
        return await simulator.start(mission_id, body.model_dump())
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(409, str(exc))


@router.post("/{mission_id}/simulation/pause")
def sim_pause(mission_id: str):
    return simulator.pause(mission_id, True)


@router.post("/{mission_id}/simulation/resume")
def sim_resume(mission_id: str):
    return simulator.pause(mission_id, False)


@router.post("/{mission_id}/simulation/stop")
def sim_stop(mission_id: str):
    if not simulator.status(mission_id):
        raise HTTPException(404, "No simulation for this mission")
    return simulator.stop(mission_id)


@router.get("/{mission_id}/simulation")
def sim_status(mission_id: str):
    return simulator.status(mission_id) or {"state": "NONE"}
