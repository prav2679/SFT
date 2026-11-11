"""Telemetry API: ingestion gateway, history, status, alerts, comparison, re-forecast.

Hardware/ground-station receivers POST packets to /api/telemetry/ingest; the
frontend only reads (REST + WebSocket). Nothing here sends commands to a balloon.
"""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse

from api.common import select
from api.schemas import ManualTelemetry, ReforecastRequest, TelemetryPacket
from core import db, exports, flight_view, manual_telemetry, predictions, reforecast as rf, weather
from core.comparison import compare, store_prediction
from core.db import iso, parse_iso, utcnow
from core.tasks import get_manager
from core.telemetry import hub

router = APIRouter(prefix="/api/telemetry", tags=["telemetry"])


def _st(mission_id):
    try:
        return hub.state(mission_id)
    except KeyError:
        raise HTTPException(404, f"Unknown mission {mission_id}")


@router.post("/ingest")
async def ingest(packet: TelemetryPacket | list[TelemetryPacket]):
    packets = packet if isinstance(packet, list) else [packet]
    results = [await hub.ingest(p.model_dump()) for p in packets]
    return results if isinstance(packet, list) else results[0]


@router.get("/latest/{mission_id}")
def latest(mission_id: str):
    _st(mission_id)
    return hub.snapshot(mission_id)["latest"]


@router.get("/status/{mission_id}")
def status(mission_id: str):
    _st(mission_id)
    return hub.snapshot(mission_id)


@router.get("/history/{mission_id}")
def history(mission_id: str, start: str | None = None, end: str | None = None,
            limit: int = Query(2000, ge=1, le=20000), offset: int = Query(0, ge=0)):
    _st(mission_id)
    return hub.history(mission_id, start, end, limit, offset)


@router.get("/history/{mission_id}/export.csv")
def history_csv(mission_id: str, start: str | None = None, end: str | None = None):
    _st(mission_id)
    items = hub.history(mission_id, start, end, 200000, 0)["items"]
    return PlainTextResponse(exports.telemetry_csv(items), media_type="text/csv",
                             headers={"Content-Disposition": f"attachment; filename={mission_id}_telemetry.csv"})


@router.get("/alerts/{mission_id}")
def alerts(mission_id: str, severity: str | None = None, unacknowledged: bool = False,
           limit: int = Query(500, le=5000)):
    _st(mission_id)
    sql, params = "SELECT * FROM alerts WHERE mission_id=?", [mission_id]
    if severity:
        sql += " AND severity=?"
        params.append(severity.upper())
    if unacknowledged:
        sql += " AND acknowledged=0"
    return db.query(sql + " ORDER BY timestamp_utc DESC LIMIT ?", params + [limit])


@router.post("/alerts/{mission_id}/{alert_id}/acknowledge")
async def acknowledge(mission_id: str, alert_id: str, operator: str = "operator"):
    db.execute("UPDATE alerts SET acknowledged=1, acknowledged_at=?, acknowledged_by=? WHERE alert_id=? AND mission_id=?",
               (iso(utcnow()), operator, alert_id, mission_id))
    row = db.query_one("SELECT * FROM alerts WHERE alert_id=?", (alert_id,))
    if not row:
        raise HTTPException(404, "Unknown alert")
    await hub.broadcast(mission_id, {"type": "alert_ack", "alert": row})
    return row


@router.get("/predictions/{mission_id}")
def predictions(mission_id: str):
    _st(mission_id)
    return db.query("SELECT * FROM prediction_sets WHERE mission_id=? ORDER BY created_utc DESC", (mission_id,))


@router.get("/comparison/{mission_id}")
def comparison(mission_id: str, prediction_set: str | None = None):
    _st(mission_id)
    return compare(mission_id, prediction_set)


@router.post("/manual/{mission_id}")
async def manual_update(mission_id: str, body: ManualTelemetry):
    """Operator-entered telemetry. Validated, stored immutably, and (by default) triggers a background re-forecast
    from this observed state that becomes a NEW prediction version. The original prediction is never changed."""
    _st(mission_id)
    try:
        return await manual_telemetry.submit(mission_id, body.model_dump())
    except manual_telemetry.ManualRejected as exc:
        raise HTTPException(exc.status, {"error_type": exc.code, "message": str(exc)})


@router.get("/phase-preview/{mission_id}")
def phase_preview(mission_id: str, vertical_velocity: float | None = None, altitude: float | None = None):
    _st(mission_id)
    return manual_telemetry.preview_phase(mission_id, vertical_velocity, altitude)


@router.post("/reforecast/{mission_id}")
async def reforecast(mission_id: str, body: ReforecastRequest):
    """Re-forecast the remaining flight from observed telemetry (ASCENT / FLOAT / DESCENT aware).

    Default: phase-aware worker, result stored server-side as a new REVISED prediction version.
    Legacy: when ``telemetry`` is supplied the original ascent-only LiveTrajectoryManager job is run unchanged
    (result attached afterwards with the /attach endpoint).
    """
    st = _st(mission_id)
    if body.telemetry is None:
        try:
            return rf.submit(mission_id, telemetry_id=body.telemetry_id, phase=body.phase,
                             baseline_simulation_id=body.simulation_id, float_end_datetime=body.float_end_datetime,
                             hold_duration_hours=body.hold_duration_hours,
                             use_measured_ascent_rate=body.use_measured_ascent_rate, forecast_cycle=body.forecast_cycle)
        except rf.ReforecastError as exc:
            raise HTTPException(exc.status, {"error_type": exc.code, "message": str(exc)})
    if not body.simulation_id:
        raise HTTPException(422, {"error_type": "INVALID_INPUT", "message": "simulation_id is required with a telemetry override"})
    base = get_manager().result(body.simulation_id)
    if not base or base.get("model") != "burst_calculator":
        raise HTTPException(409, "simulation_id must be a completed burst-calculator job")
    req = json.loads(db.query_one("SELECT request_json FROM simulations WHERE simulation_id=?",
                                  (body.simulation_id,))["request_json"])
    tel = body.telemetry
    t = parse_iso(tel["datetime_utc"])
    cycle = select(t, t, req.get("forecast_cycle"))
    request = {"mission_id": mission_id, "parameters": req["parameters"], "telemetry": tel,
               "baseline_trajectory": base["trajectory"], "forecast_cycle": cycle.cycle}
    return get_manager().submit_worker("reforecast", "live_reforecast_worker.py", request, weather.worker_env(cycle),
                                       mission_id=mission_id)


@router.get("/versions/{mission_id}")
def versions(mission_id: str):
    _st(mission_id)
    return predictions.list_versions(mission_id)


@router.get("/flight-view/{mission_id}")
def flight_view_(mission_id: str, version: str | None = None):
    """Original / actual / revised layers + landing comparison + error series in one consistent payload."""
    _st(mission_id)
    return flight_view.build(mission_id, version)


@router.post("/reforecast/{mission_id}/{simulation_id}/attach")
def attach_reforecast(mission_id: str, simulation_id: str):
    res = get_manager().result(simulation_id)
    if not res or not res.get("trajectory"):
        raise HTTPException(409, "Re-forecast not complete")
    set_id = store_prediction(mission_id, res["trajectory"], source=f"Live re-forecast {simulation_id}",
                              model_version="LiveTrajectoryManager V2", forecast_cycle=res.get("forecast_cycle"))
    hub.reload(mission_id)
    return {"prediction_set": set_id}
