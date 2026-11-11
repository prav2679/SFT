"""Health, aggregated system status (top navigation) and simulation registry."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

import config
from core import tawhiri_downloader, tawhiri_engine, weather
from core.db import iso, utcnow
from core.tasks import get_manager

router = APIRouter(tags=["health"])


@router.get("/api/health")
def health():
    return {"status": "ok", "version": config.APP_VERSION, "time_utc": iso(utcnow())}


@router.get("/api/system/status")
async def system_status():
    wx = weather.status()
    eng = await tawhiri_engine.engine_status()
    dl = tawhiri_downloader.status()
    return {
        "time_utc": iso(utcnow()), "version": config.APP_VERSION,
        "weather": {"overall": wx["overall"], "latest_valid_cycle": wx["latest_valid_cycle"],
                    "covers_now": wx["covers_now"], "downloads_in_progress": wx["downloads_in_progress"]},
        "tawhiri_engine": eng,
        "tawhiri_downloader": {k: dl[k] for k in ("status", "cycle", "message", "executable_present")},
        "simulations": {"active": get_manager().active_count(), "recent": get_manager().list(limit=8)},
        "model_python": config.SFT_MODEL_PYTHON,
        "control_capability": "NONE - monitoring, prediction and analysis only",
    }


@router.get("/api/simulations")
def simulations(kind: str | None = None, limit: int = 50):
    return get_manager().list(kind, limit)


@router.post("/api/simulations/{simulation_id}/cancel")
def cancel(simulation_id: str):
    try:
        return get_manager().cancel(simulation_id)
    except KeyError:
        raise HTTPException(404, "Simulation not running in this backend process")


@router.delete("/api/simulations/{simulation_id}")
def delete(simulation_id: str):
    get_manager().delete(simulation_id)
    return {"deleted": simulation_id}
