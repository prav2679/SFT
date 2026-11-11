"""Balloon Burst Calculator API (wraps flight_model_paramaterized.run_flight)."""
from __future__ import annotations

from fastapi import APIRouter

from api.common import burst_window, select, sim_export, sim_file, sim_result, sim_status
from api.schemas import BurstRequest
from core import weather
from core.tasks import get_manager

router = APIRouter(prefix="/api/burst", tags=["burst"])

# Prefill values for the form (balloon / flight parameters from the V4 validation baseline).
# Launch LATITUDE / LONGITUDE are deliberately absent: they are never defaulted anywhere in the application;
# the request schema rejects a run that does not carry them.
DEFAULTS = {
    "launch_altitude": 87.0,
    "launch_datetime": "2026-10-31T00:00:00Z",
    "payload_mass": 5.0, "envelope_mass": 3.0, "helium_mass": 2.0, "initial_volume": 12.05,
    "burst_diameter": 13.02, "balloon_cd": 0.47, "parachute_diameter": 2.4, "parachute_cd": 1.0,
    "ascent_rate": 6.69, "descent_rate": 5.0, "ascent_time_step": 10.0, "descent_time_step": 1.0,
    "burst_altitude": 32000.0, "maximum_altitude": 35000.0, "ground_altitude": 87.0,
}

MODEL_NOTES = {
    "balloon_type": "Latex sounding balloon (ascent -> burst -> parachute). The only type supported by this model.",
    "burst_trigger": "Burst is triggered by the commanded burst_altitude; diameter is recorded for monitoring only.",
    "descent_rate": "Accepted by the model interface; descent velocity is computed from parachute physics.",
    "descent_mass": "Model uses payload_mass as the descending mass (parachute mass is not modelled).",
    "atmosphere": "Winds from Tawhiri forecast; temperature/pressure/density from ISA in the wind adapter.",
    "unsupported_inputs": ["parachute_mass", "max_differential_pressure", "float_duration",
                           "thermal parameters"],
}


@router.get("/defaults")
def defaults():
    return {"parameters": DEFAULTS, "notes": MODEL_NOTES}


@router.post("/run")
async def run(req: BurstRequest):
    p = req.parameters.model_dump()
    cycle = select(*burst_window(p), req.forecast_cycle)
    request = {"parameters": p, "forecast_cycle": cycle.cycle}
    return get_manager().submit_worker("burst", "burst_worker.py", request, weather.worker_env(cycle), force=req.force)


@router.get("/{simulation_id}")
def status(simulation_id: str):
    return sim_status(simulation_id)


@router.get("/{simulation_id}/results")
def results(simulation_id: str):
    return sim_result(simulation_id)


@router.get("/{simulation_id}/files/{name}")
def file(simulation_id: str, name: str):
    return sim_file(simulation_id, name)


@router.get("/{simulation_id}/export/{fmt}")
def export(simulation_id: str, fmt: str):
    return sim_export(simulation_id, fmt)
