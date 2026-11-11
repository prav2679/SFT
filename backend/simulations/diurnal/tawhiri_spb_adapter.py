"""Tawhiri atmosphere adapter for the SPB diurnal model.

Requires the temperature-enabled Tawhiri engine and a four-variable CUSF
binary dataset: height, U wind, V wind, TMP (Kelvin).

The engine's make_environment_interpolator must return:
    (u_ms, v_ms, temperature_K, pressure_hPa)

No ISA fallback is used by default: a silent ISA substitution would make the
thermal/pressure simulation look forecast-driven when it is not.
"""
from __future__ import annotations

import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


class TawhiriAtmosphere:
    def __init__(
        self,
        cycle: Optional[str] = None,
        dataset_dir: Optional[str | Path] = None,
        allow_isa_fallback: bool = False,
    ):
        try:
            from tawhiri.dataset import Dataset
            from tawhiri.interpolate import make_environment_interpolator
            from tawhiri.warnings import WarningCounts
        except ImportError as exc:
            raise RuntimeError(
                "Temperature-enabled Tawhiri engine is not installed. "
                "Rebuild/reinstall the modified engine before running this model."
            ) from exc

        self.dataset_dir = Path(
            dataset_dir or os.environ.get("TAWHIRI_DATA_DIR", "tawhiri-data")
        )
        selected_cycle = cycle or os.environ.get("TAWHIRI_CYCLE")
        if not selected_cycle:
            candidates = sorted(
                p.name for p in self.dataset_dir.iterdir()
                if p.is_file() and len(p.name) == 10 and p.name.isdigit()
            ) if self.dataset_dir.exists() else []
            if not candidates:
                raise FileNotFoundError(
                    f"No Tawhiri binary cycle found in {self.dataset_dir}. "
                    "Set TAWHIRI_DATA_DIR and TAWHIRI_CYCLE."
                )
            selected_cycle = candidates[-1]

        self.cycle_text = selected_cycle
        self.cycle = datetime.strptime(
            selected_cycle, "%Y%m%d%H"
        ).replace(tzinfo=timezone.utc)

        self.dataset = Dataset(
            self.cycle.replace(tzinfo=None), directory=str(self.dataset_dir)
        )
        self.warning_counts = WarningCounts()
        self.interpolate_environment = make_environment_interpolator(
            self.dataset, self.warning_counts
        )
        self.allow_isa_fallback = allow_isa_fallback

    def __call__(self, latitude_deg: float, longitude_deg: float,
                 altitude_m: float, valid_time: datetime) -> dict:
        if valid_time.tzinfo is None:
            valid_time = valid_time.replace(tzinfo=timezone.utc)
        else:
            valid_time = valid_time.astimezone(timezone.utc)

        forecast_hour = (valid_time - self.cycle).total_seconds() / 3600.0
        if not 0.0 <= forecast_hour <= 192.0:
            raise ValueError(
                f"Forecast hour {forecast_hour:.2f} is outside Tawhiri's 0..192 h range."
            )
        if not -90.0 <= float(latitude_deg) <= 90.0:
            raise ValueError("Latitude must be between -90 and 90 degrees.")

        longitude_360 = float(longitude_deg) % 360.0
        try:
            u, v, temp_k, pressure_hpa = self.interpolate_environment(
                float(forecast_hour), float(latitude_deg),
                longitude_360, float(altitude_m)
            )
        except Exception as exc:
            raise RuntimeError(
                "Tawhiri environment interpolation failed. Confirm that the "
                "binary dataset has four variables (height, U, V, TMP) and that "
                "the temperature-enabled engine is installed."
            ) from exc

        temp_k = float(temp_k)
        pressure_hpa = float(pressure_hpa)
        if not (math.isfinite(temp_k) and temp_k > 0):
            raise ValueError(f"Invalid interpolated temperature: {temp_k}")
        if not (math.isfinite(pressure_hpa) and pressure_hpa > 0):
            raise ValueError(f"Invalid interpolated pressure: {pressure_hpa}")

        pressure_pa = pressure_hpa * 100.0
        density = pressure_pa / (287.05 * temp_k)
        return {
            "u_ms": float(u),
            "v_ms": float(v),
            "temperature_K": temp_k,
            "pressure_Pa": pressure_pa,
            "pressure_hPa": pressure_hpa,
            "air_density_kgm3": density,
            "forecast_hour": float(forecast_hour),
            "atmosphere_source": "Tawhiri TMP + native pressure-level axis",
        }

    def close(self):
        self.dataset.close()


def get_wind(latitude, longitude, altitude_m, simulation_time):
    """Backward-compatible wind-only helper using the temperature dataset."""
    if isinstance(simulation_time, str):
        simulation_time = datetime.fromisoformat(
            simulation_time.replace("Z", "+00:00")
        )
    provider = TawhiriAtmosphere()
    try:
        return provider(latitude, longitude, altitude_m, simulation_time)
    finally:
        provider.close()
