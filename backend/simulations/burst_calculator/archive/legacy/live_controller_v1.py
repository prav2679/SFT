
"""Live trajectory correction V1: telemetry updates during ascent only."""

from __future__ import annotations

import csv
import math
import sys
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CODES_DIR = PROJECT_ROOT / "codes"
if str(CODES_DIR) not in sys.path:
    sys.path.insert(0, str(CODES_DIR))

from ascent_model_time_dependent import simulate_ascent
from balloon_physics import Balloon
from descent_model_time_dependent import simulate_descent
from flight_model_paramaterized import combine_trajectories
from wind_model_time_dependent import get_wind


def _utc(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _distance_m(lat1, lon1, lat2, lon2):
    radius = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * radius * math.asin(min(1.0, math.sqrt(a)))


class LiveTrajectoryManager:
    """Manage original prediction, actual telemetry and revised remaining path."""

    def __init__(self, parameters, baseline_result, output_dir=None):
        if not baseline_result or not baseline_result.get("success"):
            raise ValueError("Pass a successful result returned by run_flight(parameters).")
        if not baseline_result.get("trajectory"):
            raise ValueError("Baseline result contains no trajectory.")

        self.parameters = deepcopy(parameters)
        self.original_prediction = deepcopy(baseline_result["trajectory"])
        self.actual_telemetry = []
        self.latest_revised_prediction = []
        self.latest_update = None

        self.launch_datetime = _utc(self.parameters["launch_datetime"])
        self.output_dir = Path(output_dir) if output_dir else PROJECT_ROOT / "live_trajectory" / "results"
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Capture launch pressure and temperature once. Never reset them at a telemetry point.
        launch_wind = get_wind(
            float(self.parameters["latitude"]),
            float(self.parameters["longitude"]),
            float(self.parameters["launch_altitude"]),
            self.launch_datetime,
        )
        self.launch_pressure_hpa = float(launch_wind["pressure_hpa"])
        self.launch_temperature_K = float(launch_wind["temperature_C"]) + 273.15

    def _nearest_original(self, telemetry_dt):
        valid = [p for p in self.original_prediction if p.get("datetime_utc")]
        if not valid:
            return None
        return min(valid, key=lambda p: abs((_utc(p["datetime_utc"]) - telemetry_dt).total_seconds()))

    def update(self, telemetry):
        """
        Required telemetry keys: datetime_utc, latitude, longitude, altitude_m.
        Optional: phase='ascent', wind_u, wind_v, wind_speed_mps, wind_direction_deg.
        """
        required = ("datetime_utc", "latitude", "longitude", "altitude_m")
        missing = [key for key in required if key not in telemetry]
        if missing:
            raise ValueError("Missing telemetry fields: " + ", ".join(missing))

        point = dict(telemetry)
        point["datetime_utc"] = _utc(point["datetime_utc"]).isoformat()
        point["latitude"] = float(point["latitude"])
        point["longitude"] = float(point["longitude"])
        point["altitude_m"] = float(point["altitude_m"])
        point["phase"] = str(point.get("phase", "ascent")).lower()

        current_dt = _utc(point["datetime_utc"])
        elapsed_s = (current_dt - self.launch_datetime).total_seconds()
        if elapsed_s < 0:
            raise ValueError("Telemetry timestamp is earlier than launch.")
        if self.actual_telemetry:
            previous_dt = _utc(self.actual_telemetry[-1]["datetime_utc"])
            if current_dt <= previous_dt:
                raise ValueError("Telemetry timestamps must be strictly increasing.")
        if point["phase"] != "ascent":
            raise NotImplementedError(
                "V1 supports ascent telemetry only. Descent continuation will be enabled "
                "after the descent model accepts measured vertical velocity."
            )

        original_point = self._nearest_original(current_dt)
        deviation_m = None
        if original_point:
            deviation_m = _distance_m(
                point["latitude"], point["longitude"],
                float(original_point["latitude"]), float(original_point["longitude"])
            )

        p = self.parameters
        balloon = Balloon(
            payload_mass=p["payload_mass"],
            envelope_mass=p["envelope_mass"],
            helium_mass=p["helium_mass"],
            initial_volume=p["initial_volume"],
            burst_diameter=p["burst_diameter"],
            drag_coefficient=p["balloon_cd"],
        )

        revised_ascent = simulate_ascent(
            launch_latitude=point["latitude"],
            launch_longitude=point["longitude"],
            launch_altitude=point["altitude_m"],
            balloon=balloon,
            launch_datetime=self.launch_datetime,
            maximum_altitude=p["maximum_altitude"],
            burst_altitude=p["burst_altitude"],
            time_step=p["ascent_time_step"],
            ascent_rate=p["ascent_rate"],
            start_time_s=elapsed_s,
            launch_pressure_hpa=self.launch_pressure_hpa,
            launch_temperature_K=self.launch_temperature_K,
        )
        if not revised_ascent:
            raise RuntimeError("Ascent reforecast returned no points.")

        measured_state = {
            "time_s": elapsed_s,
            "datetime_utc": point["datetime_utc"],
            "latitude": point["latitude"],
            "longitude": point["longitude"],
            "altitude_m": point["altitude_m"],
            "phase": "telemetry",
            "wind_u": point.get("wind_u"),
            "wind_v": point.get("wind_v"),
            "wind_speed": point.get("wind_speed_mps"),
        }
        revised_ascent = [measured_state] + revised_ascent

        revised_descent = []
        revised_burst = None
        revised_landing = None
        final_ascent = revised_ascent[-1]

        if final_ascent.get("phase") == "burst":
            revised_burst = {
                "time_s": final_ascent["time_s"],
                "latitude": final_ascent["latitude"],
                "longitude": final_ascent["longitude"],
                "altitude_m": final_ascent["altitude_m"],
            }
            revised_descent = simulate_descent(
                burst_latitude=final_ascent["latitude"],
                burst_longitude=final_ascent["longitude"],
                burst_altitude=final_ascent["altitude_m"],
                ground_altitude=p["ground_altitude"],
                payload_mass=p["payload_mass"],
                parachute_diameter=p["parachute_diameter"],
                parachute_cd=p["parachute_cd"],
                dt=p["descent_time_step"],
                burst_datetime=final_ascent["datetime_utc"],
                descent_rate=p.get("descent_rate"),
            )
            revised_landing = revised_descent[-1]

        revised_combined = combine_trajectories(
            revised_ascent,
            revised_descent,
            final_ascent["time_s"] if revised_descent else 0.0,
        )

        self.actual_telemetry.append(point)
        self.latest_revised_prediction = revised_combined
        self.latest_update = {
            "telemetry": point,
            "elapsed_s": elapsed_s,
            "deviation_from_original_m": deviation_m,
            "nearest_original_prediction": original_point,
            "revised_burst": revised_burst,
            "revised_landing": revised_landing,
            "revised_trajectory": revised_combined,
        }
        return self.latest_update

    def save(self):
        csv_path = self.output_dir / "trajectory_comparison.csv"
        rows = []
        for track_name, track in (
            ("original_prediction", self.original_prediction),
            ("actual_telemetry", self.actual_telemetry),
            ("latest_revised_prediction", self.latest_revised_prediction),
        ):
            for point in track:
                row = dict(point)
                row["track"] = track_name
                rows.append(row)

        if rows:
            fields = sorted({key for row in rows for key in row})
            preferred = ["track", "datetime_utc", "time_s", "phase",
                         "latitude", "longitude", "altitude_m"]
            fields = [k for k in preferred if k in fields] + [k for k in fields if k not in preferred]
            with csv_path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(rows)

        json_path = self.output_dir / "latest_live_update.json"
        import json
        json_path.write_text(json.dumps(self.latest_update, indent=2, default=str), encoding="utf-8")

        plot_path = self.output_dir / "trajectory_comparison.png"
        self.plot(plot_path)
        return {"csv": str(csv_path), "json": str(json_path), "plot": str(plot_path)}

    def plot(self, output_path=None):
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(10, 8))

        def draw(points, label, marker=None):
            if not points:
                return
            ax.plot(
                [float(p["longitude"]) for p in points],
                [float(p["latitude"]) for p in points],
                label=label, marker=marker, markersize=3,
            )

        draw(self.original_prediction, "Original prediction")
        draw(self.actual_telemetry, "Actual telemetry", "o")
        draw(self.latest_revised_prediction, "Updated remaining prediction")
        ax.set_xlabel("Longitude (degrees)")
        ax.set_ylabel("Latitude (degrees)")
        ax.set_title("Balloon trajectory: original vs actual vs revised")
        ax.grid(True)
        ax.legend()
        ax.set_aspect("equal", adjustable="datalim")
        fig.tight_layout()
        if output_path:
            fig.savefig(output_path, dpi=180)
        plt.close(fig)
        return str(output_path) if output_path else None
