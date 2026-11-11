"""Tawhiri binary-backed weather adapter for Balloon Burst Calculator.

The wind components come from Tawhiri's CUSF binary dataset through its native
interpolator. Tawhiri's dataset contains height, U and V only; temperature and
pressure are therefore estimated with the International Standard Atmosphere
(ISA) in this adapter. These estimates are suitable for wiring/testing but must
be considered when validating balloon expansion and burst altitude.

Environment variables:
  TAWHIRI_DATA_DIR  directory containing binary files named YYYYMMDDHH
  TAWHIRI_CYCLE     default forecast cycle YYYYMMDDHH (optional)
"""
from __future__ import annotations

import math
import os
from datetime import datetime, timezone
from pathlib import Path

from tawhiri.dataset import Dataset
from tawhiri.interpolate import make_interpolator
from tawhiri.warnings import WarningCounts

R_AIR = 287.05
G0 = 9.80665
ISA_LAYERS = (
    # base altitude m, base temp K, lapse K/m, base pressure Pa
    (0.0, 288.15, -0.0065, 101325.0),
    (11000.0, 216.65, 0.0, 22632.040095),
    (20000.0, 216.65, 0.001, 5474.877424),
    (32000.0, 228.65, 0.0028, 868.015776),
    (47000.0, 270.65, 0.0, 110.905773),
)


def isa_atmosphere(altitude_m: float) -> tuple[float, float, float]:
    """Return (temperature_K, pressure_hPa, density_kg_m3) from ISA layers."""
    z = max(-500.0, min(float(altitude_m), 47000.0))
    layer = ISA_LAYERS[0]
    for candidate in ISA_LAYERS:
        if z >= candidate[0]:
            layer = candidate
        else:
            break
    z0, t0, lapse, p0 = layer
    dz = z - z0
    if abs(lapse) < 1e-12:
        temp = t0
        pressure = p0 * math.exp(-G0 * dz / (R_AIR * temp))
    else:
        temp = t0 + lapse * dz
        temp = max(temp, 1.0)
        pressure = p0 * (temp / t0) ** (-G0 / (R_AIR * lapse))
    pressure_hpa = pressure / 100.0
    density = pressure / (R_AIR * temp)
    return temp, pressure_hpa, density


class TawhiriWind:
    """Lazy-open Tawhiri binary dataset and interpolate winds at a flight state."""
    def __init__(self, cycle: str | None = None, dataset_dir: str | Path | None = None):
        self.dataset_dir = Path(dataset_dir or os.environ.get("TAWHIRI_DATA_DIR", "data/tawhiri"))
        selected_cycle = cycle or os.environ.get("TAWHIRI_CYCLE")
        if not selected_cycle:
            candidates = sorted(
                p.name for p in self.dataset_dir.iterdir()
                if p.is_file() and len(p.name) == 10 and p.name.isdigit()
            ) if self.dataset_dir.exists() else []
            if not candidates:
                raise FileNotFoundError(
                    f"No Tawhiri binary dataset found in {self.dataset_dir}. "
                    "Run download_tawhiri_dataset.py first or set TAWHIRI_CYCLE."
                )
            selected_cycle = candidates[-1]
        self.cycle_text = selected_cycle
        self.cycle = datetime.strptime(selected_cycle, "%Y%m%d%H").replace(tzinfo=timezone.utc)
        self.dataset = Dataset(self.cycle.replace(tzinfo=None), directory=str(self.dataset_dir))
        self.warning_counts = WarningCounts()
        self.interpolate = make_interpolator(self.dataset, self.warning_counts)

    def wind(self, latitude: float, longitude: float, altitude_m: float, valid_time: datetime) -> dict:
        if valid_time.tzinfo is None:
            valid_time = valid_time.replace(tzinfo=timezone.utc)
        else:
            valid_time = valid_time.astimezone(timezone.utc)
        forecast_hours = (valid_time - self.cycle).total_seconds() / 3600.0
        if forecast_hours < 0 or forecast_hours >= 192:
            raise ValueError(
                f"Requested time is {forecast_hours:.2f} h from cycle {self.cycle_text}; "
                "Tawhiri dataset supports forecast hours from 0 up to, but not including, 192 hours."
            )
        lat = float(latitude)
        if not -90.0 <= lat <= 90.0:
            raise ValueError("Latitude must be between -90 and 90 degrees.")
        lon = float(longitude) % 360.0
        u, v = self.interpolate(float(forecast_hours), lat, lon, float(altitude_m))
        temp_k, pressure_hpa, density = isa_atmosphere(altitude_m)
        speed = math.hypot(float(u), float(v))
        from_deg = (math.degrees(math.atan2(-float(u), -float(v))) + 360.0) % 360.0
        toward_deg = (from_deg + 180.0) % 360.0
        return {
            "latitude": lat, "longitude": lon, "altitude_m": float(altitude_m),
            "simulation_time": valid_time.isoformat(),
            "U": float(u), "V": float(v), "wind_speed_mps": speed,
            "wind_from_degrees": from_deg, "wind_toward_degrees": toward_deg,
            "temperature_K": temp_k, "temperature_C": temp_k - 273.15,
            "pressure_hpa": pressure_hpa, "air_density": density,
            "gfs_time_0": self.cycle.isoformat(),
            "gfs_time_1": self.cycle.isoformat(),
            "time_interpolation_factor": float(forecast_hours),
            "atmosphere_source": "ISA estimate (Tawhiri binary has no temperature/pressure fields)",
        }

    def close(self):
        self.dataset.close()


_WIND = None

def get_wind(latitude, longitude, altitude_m, simulation_time):
    """Drop-in replacement for the old xarray-based get_wind function."""
    global _WIND
    if isinstance(simulation_time, str):
        simulation_time = datetime.fromisoformat(simulation_time.replace("Z", "+00:00"))
    if not isinstance(simulation_time, datetime):
        raise TypeError("simulation_time must be datetime or ISO-8601 string")
    if simulation_time.tzinfo is None:
        simulation_time = simulation_time.replace(tzinfo=timezone.utc)
    if _WIND is None:
        _WIND = TawhiriWind()
    return _WIND.wind(latitude, longitude, altitude_m, simulation_time)


def close_wind_dataset():
    global _WIND
    if _WIND is not None:
        _WIND.close()
        _WIND = None
