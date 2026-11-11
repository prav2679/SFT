"""Synthetic stand-in for the preserved ``wind_model_time_dependent`` module (TEST USE ONLY).

The real adapter needs the compiled Tawhiri engine and a 12.7 GB forecast dataset, neither of which exists in
CI. This module exposes the same ``get_wind`` interface with a deterministic, altitude-sheared wind and the same
ISA atmosphere formulas, so the REAL SFT scientific models (ascent / descent / hold / backtrack) can be executed
end-to-end. Results are therefore NOT meteorologically meaningful - they validate plumbing, phase handling and
coordinate propagation, not forecast accuracy.

Every call is appended to $SFT_FAKE_WIND_LOG (JSON lines) so tests can prove which coordinates reached the model.
"""
from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone

R_AIR, G0 = 287.05, 9.80665
ISA_LAYERS = ((0.0, 288.15, -0.0065, 101325.0), (11000.0, 216.65, 0.0, 22632.040095),
              (20000.0, 216.65, 0.001, 5474.877424), (32000.0, 228.65, 0.0028, 868.015776),
              (47000.0, 270.65, 0.0, 110.905773))


def isa_atmosphere(altitude_m):
    z = max(-500.0, min(float(altitude_m), 47000.0))
    layer = ISA_LAYERS[0]
    for cand in ISA_LAYERS:
        if z >= cand[0]:
            layer = cand
        else:
            break
    z0, t0, lapse, p0 = layer
    dz = z - z0
    if abs(lapse) < 1e-12:
        temp, pressure = t0, p0 * math.exp(-G0 * dz / (R_AIR * t0))
    else:
        temp = max(t0 + lapse * dz, 1.0)
        pressure = p0 * (temp / t0) ** (-G0 / (R_AIR * lapse))
    return temp, pressure / 100.0, pressure / (R_AIR * temp)


def get_wind(latitude, longitude, altitude_m, simulation_time):
    if isinstance(simulation_time, str):
        simulation_time = datetime.fromisoformat(simulation_time.replace("Z", "+00:00"))
    if simulation_time.tzinfo is None:
        simulation_time = simulation_time.replace(tzinfo=timezone.utc)
    log = os.environ.get("SFT_FAKE_WIND_LOG")
    if log:
        with open(log, "a", encoding="utf-8") as f:
            f.write(json.dumps({"lat": float(latitude), "lon": float(longitude), "alt": float(altitude_m),
                                "t": simulation_time.isoformat()}) + "\n")
    u0 = float(os.environ.get("SFT_FAKE_WIND_U", "4.0"))
    v0 = float(os.environ.get("SFT_FAKE_WIND_V", "2.0"))
    u = u0 + 0.0004 * float(altitude_m)          # eastward component grows with height (shear)
    v = v0 - 0.0001 * float(altitude_m)
    temp_k, p_hpa, rho = isa_atmosphere(altitude_m)
    speed = math.hypot(u, v)
    frm = (math.degrees(math.atan2(-u, -v)) + 360.0) % 360.0
    return {"latitude": float(latitude), "longitude": float(longitude), "altitude_m": float(altitude_m),
            "simulation_time": simulation_time.isoformat(), "U": u, "V": v, "wind_speed_mps": speed,
            "wind_from_degrees": frm, "wind_toward_degrees": (frm + 180.0) % 360.0,
            "temperature_K": temp_k, "temperature_C": temp_k - 273.15, "pressure_hpa": p_hpa, "air_density": rho,
            "gfs_time_0": simulation_time.isoformat(), "gfs_time_1": simulation_time.isoformat(),
            "time_interpolation_factor": 0.0, "atmosphere_source": "SYNTHETIC TEST WIND (not a forecast)"}


def close_wind_dataset():
    return None
