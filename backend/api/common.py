"""Helpers shared by the simulation routes."""
from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import FileResponse, PlainTextResponse

import config
from core import exports, weather
from core.db import parse_iso
from core.tasks import get_manager


def weather_http(exc: weather.WeatherDataError) -> HTTPException:
    return HTTPException(status_code=409, detail={"error_type": exc.code, "message": str(exc), **exc.details})


def burst_window(p: dict):
    start = parse_iso(p["launch_datetime"])
    ascent_s = (p["burst_altitude"] - p["launch_altitude"]) / p["ascent_rate"]
    # Descent duration is not known before running; 3 h bounds the model's
    # parachute descent for the supported configurations.
    return start, start + timedelta(seconds=ascent_s + 3 * 3600)


def forward_window(p: dict):
    start = parse_iso(p["launch_datetime"])
    ascent_s = (p["target_altitude_m"] - p["launch_altitude_m"]) / p["ascent_rate_mps"]
    return start, start + timedelta(seconds=ascent_s + p["hold_duration_hours"] * 3600 + 3 * 3600)


def reverse_window(p: dict):
    end = parse_iso(p["target_landing_datetime"])
    ascent_s = (p["target_altitude_m"] - p.get("launch_altitude_m", 0)) / p["ascent_rate_mps"]
    return end - timedelta(seconds=ascent_s + p["hold_duration_hours"] * 3600 + 3 * 3600), end


def select(start, end, cycle):
    try:
        return weather.select_cycle(start, end, cycle)
    except weather.WeatherDataError as exc:
        raise weather_http(exc)


def sim_status(sim_id: str) -> dict:
    try:
        return get_manager().status(sim_id)
    except KeyError:
        raise HTTPException(404, f"Unknown simulation {sim_id}")


def sim_result(sim_id: str) -> dict:
    st = sim_status(sim_id)
    if st["status"] != "COMPLETED":
        raise HTTPException(409, {"message": f"Simulation is {st['status']}", "status": st})
    return get_manager().result(sim_id)


def sim_file(sim_id: str, name: str):
    p = get_manager().file(sim_id, name)
    if not p:
        raise HTTPException(404, "File not found")
    return FileResponse(p, filename=f"{sim_id}_{name}")


def sim_export(sim_id: str, fmt: str):
    res = sim_result(sim_id)
    files = res.get("files", {})
    if fmt in files:                       # model-native export, served unchanged
        return sim_file(sim_id, files[fmt])
    traj = res.get("trajectory")
    if not traj and res.get("rows"):          # diurnal model rows -> shared format
        traj = [{"t": r["time_utc"], "lat": r["latitude_deg"], "lon": r["longitude_deg"], "alt": r["altitude_m"],
                 "phase": r["phase"]} for r in res["rows"]]
    if not traj:
        raise HTTPException(404, f"No {fmt} export available")
    if fmt == "csv":
        return PlainTextResponse(exports.trajectory_csv(traj), media_type="text/csv",
                                 headers={"Content-Disposition": f"attachment; filename={sim_id}.csv"})
    if fmt == "kml":
        return PlainTextResponse(exports.trajectory_kml(traj, sim_id, res.get("model_version", "")),
                                 media_type="application/vnd.google-earth.kml+xml",
                                 headers={"Content-Disposition": f"attachment; filename={sim_id}.kml"})
    raise HTTPException(400, "fmt must be csv or kml")


async def run_worker_inline(worker: str, request: dict, env: dict, job_dir: Path, timeout: float) -> dict:
    """Run a model worker to completion inside a composite (compare) job."""
    job_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / "request.json").write_text(json.dumps(request, default=str), encoding="utf-8")
    proc = await asyncio.create_subprocess_exec(
        config.SFT_MODEL_PYTHON, str(config.BACKEND_DIR / "workers" / worker), str(job_dir),
        env=env, cwd=str(job_dir), stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
    try:
        _, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise RuntimeError(f"{worker} timed out")
    if proc.returncode != 0:
        e = job_dir / "error.json"
        detail = json.loads(e.read_text()) if e.exists() else {"message": err.decode(errors='replace')[-1500:]}
        ex = RuntimeError(f"SFT model failed: {detail.get('message')}")
        ex.code = detail.get("error_type", "MODEL_ERROR")
        ex.details = detail
        raise ex
    return json.loads((job_dir / "result.json").read_text(encoding="utf-8"))
