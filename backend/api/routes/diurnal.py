"""Diurnal Effect Analysis API (SPB Stage 5 model)."""
from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, HTTPException

from api.common import select, sim_export, sim_file, sim_result, sim_status
from api.schemas import DiurnalRequest
from core import weather
from core.db import parse_iso
from core.tasks import get_manager

router = APIRouter(prefix="/api/diurnal", tags=["diurnal"])

# Defaults are the Stage 5 dataclass defaults (spb_stage5_model.Balloon/Mission)
BALLOON_DEFAULTS = {
    "payload_mass_kg": 1.0, "helium_mass_kg": 1.2, "envelope_mass_kg": 3.7, "helium_cp_j_kgk": 5193.0,
    "envelope_heat_capacity_j_k": 7400.0, "initial_helium_temp_k": 301.0, "initial_envelope_temp_k": 301.0,
    "initial_volume_m3": 7.428, "max_volume_m3": 204.86, "max_differential_pressure_pa": 1500.0,
    "reference_differential_pressure_pa": 1000.0, "envelope_compliance_pa_inv": 2.0e-5,
    "max_expansion_fraction": 0.05, "solar_absorptivity": 0.12, "infrared_emissivity": 0.15,
    "internal_heat_transfer_w_m2k": 5.0, "external_h_ground_w_m2k": 15.0, "external_h_float_w_m2k": 2.0,
    "drag_coefficient": 0.45,
    "launch_elevation_m": 6.0, "envelope_mode": "compliant",
}
MISSION_DEFAULTS = {
    "launch_time_utc": "2026-10-31T12:30:00Z", "target_float_altitude_m": 27000.0,
    "prescribed_ascent_rate_ms": 5.4, "float_duration_h": 72.0, "outer_timestep_s": 30.0,
    "inner_timestep_s": 1.0, "solar_transmittance": 0.75, "sea_albedo": 0.06, "land_albedo": 0.15,
    "outgoing_longwave_w_m2": 250.0,
}
PARAMETER_STATUS = {
    "given": ["payload_mass_kg", "helium_mass_kg", "target_float_altitude_m", "prescribed_ascent_rate_ms"],
    "note": "Most thermal/envelope parameters are ASSUMED (spb_parameters.py SOURCE_STATUS) and must be "
            "calibrated before results are treated as validated.",
}


@router.get("/defaults")
def defaults():
    return {"balloon": BALLOON_DEFAULTS, "mission": MISSION_DEFAULTS, "parameter_status": PARAMETER_STATUS}


@router.post("/run")
async def run(req: DiurnalRequest):
    m = {**MISSION_DEFAULTS, **{k: v for k, v in req.mission.items() if v is not None}}
    b = {**BALLOON_DEFAULTS, **{k: v for k, v in req.balloon.items() if v is not None}}
    for key, lo, hi, label in (("initial_latitude_deg", -90, 90, "Initial latitude"),
                               ("initial_longitude_deg", -180, 180, "Initial longitude")):
        v = b.get(key)
        if v is None or v == "":
            raise HTTPException(422, {"error_type": "INVALID_INPUT", "message":
                                      f"{label} is required - the diurnal analysis never falls back to a default location."})
        try:
            v = float(v)
        except (TypeError, ValueError):
            raise HTTPException(422, {"error_type": "INVALID_INPUT", "message": f"{label} must be a number"})
        if not lo <= v <= hi:
            raise HTTPException(422, {"error_type": "INVALID_INPUT", "message": f"{label} must be between {lo} and {hi} degrees"})
        b[key] = v
    if b.get("envelope_mode") not in ("compliant", "rigid"):
        raise HTTPException(422, "envelope_mode must be 'compliant' or 'rigid'")
    start = parse_iso(m["launch_time_utc"])
    dur = ((float(m["target_float_altitude_m"]) - float(b["launch_elevation_m"])) / float(m["prescribed_ascent_rate_ms"])
           + float(m["float_duration_h"]) * 3600 + 1200)
    cycle = select(start, start + timedelta(seconds=dur), req.forecast_cycle)
    request = {"balloon": b, "mission": m, "forecast_cycle": cycle.cycle}
    return get_manager().submit_worker("diurnal", "diurnal_worker.py", request, weather.worker_env(cycle),
                                       force=req.force)


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
