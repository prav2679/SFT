"""Forward / reverse trajectory and engine comparison API.

Engines:
  sft      - preserved SFT models (flight_forward / flight_backtrack /
             flight_model_paramaterized) run in isolated workers
  tawhiri  - preserved Tawhiri engine via its HTTP API (core.tawhiri_engine)
  compare  - both, ONLY over segments where the physical assumptions are
             comparable (see ENGINE_DIFFERENCES and docs/ENGINE_DIFFERENCES.md)
"""
from __future__ import annotations

import math
from datetime import timedelta

from fastapi import APIRouter, HTTPException

import config
from api.common import (burst_window, forward_window, reverse_window, run_worker_inline, select, sim_export,
                        sim_file, sim_result, sim_status)
from api.schemas import TrajectoryRequest
from core import tawhiri_engine, weather
from core.db import iso, parse_iso
from core.tasks import get_manager
from core.telemetry import haversine

router = APIRouter(prefix="/api/trajectory", tags=["trajectory"])

ENGINE_DIFFERENCES = [
    {"aspect": "Weather input", "sft": "Tawhiri CUSF binary via tawhiri.interpolate.make_interpolator (U/V only)",
     "tawhiri": "Same CUSF binary through the engine's own wind model"},
    {"aspect": "Atmospheric interpolation", "sft": "Native 4-D Cython interpolation for wind; T/P/rho from ISA layers",
     "tawhiri": "Native 4-D Cython interpolation for wind; density model inside the engine for descent"},
    {"aspect": "Vertical motion", "sft": "Constant ascent rate; parachute descent from drag physics (mass, diameter, Cd)",
     "tawhiri": "Constant ascent rate; descent from sea-level descent rate scaled with density"},
    {"aspect": "Balloon physics", "sft": "Burst model tracks gas-law volume/diameter (burst by commanded altitude); hold model idealised",
     "tawhiri": "None (kinematic profiles only)"},
    {"aspect": "Ascent/descent assumptions", "sft": "Hold mission: ascent -> hold -> descent. Burst flight: ascent -> burst -> descent",
     "tawhiri": "standard_profile: ascent -> burst -> descent. float_profile: ascent -> float (no descent)"},
    {"aspect": "Time resolution", "sft": "User time steps (ascent/hold 10-60 s, descent 1-10 s)",
     "tawhiri": "Engine RK4 solver, 60 s output steps"},
    {"aspect": "Forecast coverage", "sft": "0 <= lead < 192 h from cycle (exclusive upper bound)",
     "tawhiri": "Same dataset; engine dataset chosen by RFC3339 'dataset' parameter"},
    {"aspect": "Reverse mode", "sft": "Landing-target backtrack (descent, hold, ascent) + forward validation",
     "tawhiri": "reverse_profile: backward ascent from an observed ascending state to ground (launch-site estimate)"},
]


@router.get("/engines")
async def engines():
    eng = await tawhiri_engine.engine_status()
    wx = weather.status()
    return {
        "sft": {"available": wx["overall"] in ("AVAILABLE", "STALE"), "requires": "valid Tawhiri dataset + model interpreter",
                "model_python": config.SFT_MODEL_PYTHON},
        "tawhiri": {"available": eng["status"] == "OK", **eng},
        "compare": {"available": eng["status"] == "OK" and wx["overall"] in ("AVAILABLE", "STALE")},
        "differences": ENGINE_DIFFERENCES,
        "weather": wx["overall"],
    }


def _hold_params(req: TrajectoryRequest) -> dict:
    if not req.forward:
        raise HTTPException(422, "forward parameters required for the hold-mission model")
    return req.forward.model_dump()


def _burst_params(req: TrajectoryRequest) -> dict:
    if not req.burst:
        raise HTTPException(422, "burst parameters required for the burst-flight model")
    return req.burst.model_dump()


def _tawhiri_forward(req: TrajectoryRequest, cycle: str | None) -> dict:
    if req.sft_model == "burst_flight":
        p = _burst_params(req)
        return {"profile": "standard_profile", "launch_latitude": p["latitude"], "launch_longitude": p["longitude"],
                "launch_altitude": p["launch_altitude"], "launch_datetime": p["launch_datetime"],
                "ascent_rate": p["ascent_rate"], "burst_altitude": p["burst_altitude"],
                "descent_rate": req.tawhiri_descent_rate or p["descent_rate"], "forecast_cycle": cycle}
    p = _hold_params(req)
    stop = parse_iso(p["launch_datetime"]) + timedelta(
        seconds=(p["target_altitude_m"] - p["launch_altitude_m"]) / p["ascent_rate_mps"] + p["hold_duration_hours"] * 3600)
    return {"profile": "float_profile", "launch_latitude": p["launch_latitude"], "launch_longitude": p["launch_longitude"],
            "launch_altitude": p["launch_altitude_m"], "launch_datetime": p["launch_datetime"],
            "ascent_rate": p["ascent_rate_mps"], "float_altitude": p["target_altitude_m"],
            "stop_datetime": iso(stop), "forecast_cycle": cycle}


async def _tawhiri_job(task, params):
    try:
        return await tawhiri_engine.predict(params)
    except tawhiri_engine.TawhiriEngineError as exc:
        raise exc


@router.post("/forward")
async def forward(req: TrajectoryRequest):
    mgr = get_manager()
    if req.engine == "compare":
        return compare(req, "forward")
    if req.sft_model == "burst_flight":
        p = _burst_params(req)
        cycle = select(*burst_window(p), req.forecast_cycle)
    else:
        p = _hold_params(req)
        cycle = select(*forward_window(p), req.forecast_cycle)
    if req.engine == "tawhiri":
        tp = _tawhiri_forward(req, cycle.cycle)
        return mgr.submit_coroutine("tawhiri-forward", tp, lambda t: _tawhiri_job(t, tp), force=req.force)
    if req.sft_model == "burst_flight":
        return mgr.submit_worker("burst", "burst_worker.py", {"parameters": p, "forecast_cycle": cycle.cycle},
                                 weather.worker_env(cycle), force=req.force)
    return mgr.submit_worker("forward", "forward_worker.py", {"parameters": p, "forecast_cycle": cycle.cycle},
                             weather.worker_env(cycle), force=req.force)


@router.post("/reverse")
async def reverse(req: TrajectoryRequest):
    if req.engine == "compare":
        return compare(req, "reverse")
    if not req.reverse:
        raise HTTPException(422, "reverse parameters required")
    p = req.reverse.model_dump()
    if req.engine == "tawhiri":
        raise HTTPException(422, {"message": "Tawhiri's reverse_profile estimates a launch site from an ASCENDING "
                                             "balloon state; it does not solve landing-target problems. Use "
                                             "engine=compare (which feeds it the SFT hold-start state) or "
                                             "POST /api/tawhiri/predict with profile=reverse_profile."})
    cycle = select(*reverse_window(p), req.forecast_cycle)
    return get_manager().submit_worker("reverse", "reverse_worker.py", {"parameters": p, "forecast_cycle": cycle.cycle},
                                       weather.worker_env(cycle), force=req.force)


# ----------------------------------------------------------------- compare
def compare(req: TrajectoryRequest, mode: str):
    mgr = get_manager()
    if mode == "forward":
        if req.sft_model == "burst_flight":
            p = _burst_params(req)
            cycle = select(*burst_window(p), req.forecast_cycle)
            worker, sft_req = "burst_worker.py", {"parameters": p, "forecast_cycle": cycle.cycle}
        else:
            p = _hold_params(req)
            cycle = select(*forward_window(p), req.forecast_cycle)
            worker, sft_req = "forward_worker.py", {"parameters": p, "forecast_cycle": cycle.cycle}
        taw = _tawhiri_forward(req, cycle.cycle)
    else:
        if not req.reverse:
            raise HTTPException(422, "reverse parameters required")
        p = req.reverse.model_dump()
        cycle = select(*reverse_window(p), req.forecast_cycle)
        worker, sft_req, taw = "reverse_worker.py", {"parameters": p, "forecast_cycle": cycle.cycle}, None
    request = {"mode": mode, "sft_model": req.sft_model, "sft": sft_req, "tawhiri": taw}
    env = weather.worker_env(cycle)

    async def job(task):
        task_dir = task.dir
        sft = await run_worker_inline(worker, sft_req, env, task_dir / "sft", config.SIM_TIMEOUT_S)
        if mode == "forward":
            tw = await tawhiri_engine.predict(taw)
            segment = "full flight" if req.sft_model == "burst_flight" else "ascent + hold/float (descent excluded)"
            sft_cmp = sft["trajectory"] if req.sft_model == "burst_flight" else \
                [x for x in sft["trajectory"] if x["phase"] in ("ascent", "altitude_hold")]
            return {"mode": mode, "segment_compared": segment, "sft": sft, "tawhiri": tw,
                    "metrics": metrics(sft_cmp, tw["trajectory"], compare_landing=req.sft_model == "burst_flight"),
                    "differences": ENGINE_DIFFERENCES, "forecast_cycle": cycle.cycle}
        hs = sft.get("forward_validation_hold_start")
        if not hs:
            raise RuntimeError("SFT reverse result has no hold-start state to seed the Tawhiri reverse profile")
        tp = {"profile": "reverse_profile", "launch_latitude": hs["lat"], "launch_longitude": hs["lon"],
              "launch_altitude": hs["alt"], "launch_datetime": hs["t"], "ascent_rate": p["ascent_rate_mps"],
              "forecast_cycle": cycle.cycle}
        tw = await tawhiri_engine.predict(tp)
        le = tw.get("launch_estimate") or {}
        diff = None
        if le.get("latitude") is not None:
            diff = {"launch_position_difference_m": haversine(sft["estimated_launch_latitude"],
                                                              sft["estimated_launch_longitude"],
                                                              le["latitude"], le["longitude"]),
                    "launch_time_difference_s": (parse_iso(le["datetime"]) -
                                                 parse_iso(sft["estimated_launch_datetime_utc"])).total_seconds()
                    if le.get("datetime") else None}
        return {"mode": mode, "segment_compared": "ascent backtrack only (Tawhiri seeded with SFT forward-validation "
                                                  "hold-start state)", "sft": sft, "tawhiri": tw,
                "metrics": diff, "differences": ENGINE_DIFFERENCES, "forecast_cycle": cycle.cycle}

    return mgr.submit_coroutine(f"compare-{mode}", request, job, force=req.force)


def _interp_pos(track, t):
    lo, hi = 0, len(track) - 1
    if t < track[0]["_t"] or t > track[-1]["_t"]:
        return None
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if track[mid]["_t"] <= t:
            lo = mid
        else:
            hi = mid
    a, b = track[lo], track[hi]
    f = 0 if b["_t"] == a["_t"] else (t - a["_t"]) / (b["_t"] - a["_t"])
    return {k: a[k] + f * (b[k] - a[k]) for k in ("lat", "lon", "alt")}


def _drift_speeds(track):
    out = []
    for a, b in zip(track, track[1:]):
        dt = b["_t"] - a["_t"]
        if dt > 0:
            out.append({"t": b["t"], "alt": b["alt"], "speed": haversine(a["lat"], a["lon"], b["lat"], b["lon"]) / dt})
    return out


def metrics(sft: list[dict], taw: list[dict], compare_landing: bool) -> dict:
    for tr in (sft, taw):
        for p in tr:
            p["_t"] = parse_iso(p["t"]).timestamp()
    s0, s1, t0, t1 = sft[0], sft[-1], taw[0], taw[-1]
    sep = []
    step = max(1, len(sft) // 600)
    for p in sft[::step]:
        q = _interp_pos(taw, p["_t"])
        if q:
            sep.append({"t": p["t"], "horizontal_separation_m": haversine(p["lat"], p["lon"], q["lat"], q["lon"]),
                        "altitude_difference_m": p["alt"] - q["alt"]})
    sft_disp = haversine(s0["lat"], s0["lon"], s1["lat"], s1["lon"])
    taw_disp = haversine(t0["lat"], t0["lon"], t1["lat"], t1["lon"])
    out = {
        "flight_time_s": {"sft": s1["_t"] - s0["_t"], "tawhiri": t1["_t"] - t0["_t"],
                          "difference": (s1["_t"] - s0["_t"]) - (t1["_t"] - t0["_t"])},
        "max_altitude_m": {"sft": max(p["alt"] for p in sft), "tawhiri": max(p["alt"] for p in taw),
                           "difference": max(p["alt"] for p in sft) - max(p["alt"] for p in taw)},
        "horizontal_displacement_m": {"sft": sft_disp, "tawhiri": taw_disp, "difference": sft_disp - taw_disp},
        "end_point_difference_m": haversine(s1["lat"], s1["lon"], t1["lat"], t1["lon"]),
        "time_aligned_separation": sep,
        "max_time_aligned_separation_m": max((x["horizontal_separation_m"] for x in sep), default=None),
        "wind": {"note": "Tawhiri output contains no winds; its horizontal drift speed is derived from consecutive "
                         "output positions and compared with the wind speed sampled by the SFT model.",
                 "sft_wind_speed": [{"t": p["t"], "alt": p["alt"], "speed": p.get("wind_speed")}
                                    for p in sft[::step] if p.get("wind_speed") is not None],
                 "tawhiri_drift_speed": _drift_speeds(taw)[:: max(1, len(taw) // 600)]},
    }
    if compare_landing:
        out["landing_point_difference_m"] = out["end_point_difference_m"]
    for tr in (sft, taw):
        for p in tr:
            p.pop("_t", None)
    return out


@router.get("/{simulation_id}")
def status(simulation_id: str):
    return sim_status(simulation_id)


@router.get("/{simulation_id}/results")
def results(simulation_id: str):
    return sim_result(simulation_id)


@router.get("/{simulation_id}/files/{name:path}")
def file(simulation_id: str, name: str):
    return sim_file(simulation_id, name)


@router.get("/{simulation_id}/export/{fmt}")
def export(simulation_id: str, fmt: str):
    return sim_export(simulation_id, fmt)
