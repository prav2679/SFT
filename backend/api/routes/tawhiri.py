"""Tawhiri pipeline API. Downloader, data validation and engine are reported separately."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from api.schemas import DownloadRequest
from core import tawhiri_downloader, tawhiri_engine, weather
from core.tasks import get_manager

router = APIRouter(prefix="/api/tawhiri", tags=["tawhiri"])


@router.get("/status")
async def status():
    return {"downloader": tawhiri_downloader.status(), "weather_data": weather.status(),
            "engine": await tawhiri_engine.engine_status()}


@router.post("/download")
async def download(req: DownloadRequest):
    try:
        return await tawhiri_downloader.start(req.cycle, req.force)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    except RuntimeError as exc:
        raise HTTPException(409, str(exc))


@router.post("/download/cancel")
async def cancel():
    return await tawhiri_downloader.cancel()


@router.post("/predict")
async def predict(params: dict):
    async def job(task):
        return await tawhiri_engine.predict(params)
    return get_manager().submit_coroutine("tawhiri", params, job, force=bool(params.get("force")))
