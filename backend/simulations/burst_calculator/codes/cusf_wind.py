"""
CUSF/Tawhiri memory-mapped wind accessor.

Run in the Python environment where Tawhiri's Cython extensions are installed.
It opens the preprocessed CUSF binary via memory mapping and uses Tawhiri's
compiled four-dimensional interpolation (time, latitude, longitude, altitude).
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Tuple

from tawhiri.dataset import Dataset
from tawhiri.interpolate import make_interpolator
from tawhiri.warnings import WarningCounts


class CUSFWind:
    """Memory-mapped CUSF wind data with Tawhiri's Cython interpolator."""

    def __init__(self, cycle: str, dataset_dir: str | Path):
        """
        Args:
            cycle: Dataset cycle as YYYYMMDDHH, e.g. '2026102800'.
            dataset_dir: Directory containing a file named exactly YYYYMMDDHH.
        """
        self.cycle = datetime.strptime(cycle, "%Y%m%d%H").replace(tzinfo=timezone.utc)
        self.dataset_dir = str(dataset_dir)
        self.warnings = WarningCounts()
        self.dataset = Dataset(
            self.cycle.replace(tzinfo=None),
            directory=self.dataset_dir,
        )
        self._interpolate = make_interpolator(self.dataset, self.warnings)
        self.closed = False

    def wind(
        self,
        valid_time: datetime,
        latitude: float,
        longitude: float,
        altitude_m: float,
    ) -> Tuple[float, float]:
        """Return (u, v) in m/s for UTC time, latitude/longitude and ASL altitude."""
        if self.closed:
            raise RuntimeError("CUSFWind is closed")

        if valid_time.tzinfo is None:
            valid_time = valid_time.replace(tzinfo=timezone.utc)
        else:
            valid_time = valid_time.astimezone(timezone.utc)

        hours = (valid_time - self.cycle).total_seconds() / 3600.0
        lon = float(longitude) % 360.0

        u, v = self._interpolate(
            float(hours),
            float(latitude),
            lon,
            float(altitude_m),
        )
        return float(u), float(v)

    def warning_summary(self) -> dict:
        return self.warnings.to_dict()

    def close(self) -> None:
        if not self.closed:
            self.dataset.close()
            self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Test CUSF memory-mapped 4D wind interpolation."
    )
    parser.add_argument("--cycle", required=True, help="YYYYMMDDHH")
    parser.add_argument("--dataset-dir", required=True)
    parser.add_argument(
        "--time", required=True,
        help="UTC ISO time, e.g. 2026-10-28T06:00:00Z",
    )
    parser.add_argument("--lat", type=float, required=True)
    parser.add_argument("--lon", type=float, required=True)
    parser.add_argument("--alt", type=float, required=True, help="Altitude in metres ASL")
    args = parser.parse_args()

    dt = datetime.fromisoformat(args.time.replace("Z", "+00:00"))
    with CUSFWind(args.cycle, args.dataset_dir) as winds:
        u, v = winds.wind(dt, args.lat, args.lon, args.alt)
        print(f"u={u:.3f} m/s, v={v:.3f} m/s")
        print(f"warnings={winds.warning_summary()}")
