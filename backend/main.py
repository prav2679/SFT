"""SFT Balloon GNC Mission Control - FastAPI application entry point.

Run:  cd backend && uvicorn main:app --host 127.0.0.1 --port 8000
"""
from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import config
from api.routes import burst, diurnal, health, missions, tawhiri, telemetry, trajectory
from core import db
from core.tasks import get_manager
from core.telemetry import hub
from core.weather import WeatherDataError


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    get_manager().recover()
    monitor = asyncio.create_task(hub.monitor())
    yield
    monitor.cancel()


app = FastAPI(title="SFT Balloon GNC Mission Control", version=config.APP_VERSION, lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_methods=["*"], allow_headers=["*"])
for r in (health, burst, trajectory, diurnal, telemetry, missions, tawhiri):
    app.include_router(r.router)


@app.exception_handler(WeatherDataError)
async def weather_error(_: Request, exc: WeatherDataError):
    return JSONResponse(status_code=409, content={"detail": {"error_type": exc.code, "message": str(exc), **exc.details}})


@app.exception_handler(ValueError)
async def value_error(_: Request, exc: ValueError):
    return JSONResponse(status_code=422, content={"detail": {"error_type": "INVALID_INPUT", "message": str(exc)}})


@app.websocket("/ws/telemetry/{mission_id}")
async def ws_telemetry(ws: WebSocket, mission_id: str):
    await ws.accept()
    try:
        st = hub.state(mission_id)
    except KeyError:
        await ws.send_text(json.dumps({"type": "error", "message": f"Unknown mission {mission_id}"}))
        await ws.close()
        return
    st.subscribers.add(ws)
    await ws.send_text(json.dumps({"type": "status", **hub.snapshot(mission_id)}, default=str))
    try:
        while True:
            msg = await ws.receive_text()      # client heartbeats; no commands accepted
            if msg == "ping":
                await ws.send_text('{"type":"pong"}')
    except WebSocketDisconnect:
        pass
    finally:
        st.subscribers.discard(ws)


if config.LEGACY_PREDICTOR_DIR.exists():
    app.mount("/legacy-predictor", StaticFiles(directory=config.LEGACY_PREDICTOR_DIR, html=True), name="legacy")

if config.FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=config.FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str):
        f = config.FRONTEND_DIST / path
        if path and f.is_file() and config.FRONTEND_DIST in f.resolve().parents:
            return FileResponse(f)
        return FileResponse(config.FRONTEND_DIST / "index.html")
