"""
Live trajectory correction V2.

Input: an observed balloon state at a specific UTC time during ASCENT.
Output: the remaining ascent, predicted burst, descent and landing.

This version deliberately does not modify thermal physics or the existing
ascent/descent models. It reuses those models and preserves the original
launch time so weather queries remain on the mission's forecast timeline.
"""

from __future__ import annotations

import csv
import inspect
import json
import math
import sys
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CODES_DIR = PROJECT_ROOT / "codes"
if str(CODES_DIR) not in sys.path:
    sys.path.insert(0, str(CODES_DIR))

from ascent_model_time_dependent import simulate_ascent
from balloon_physics import Balloon
from descent_model_time_dependent import simulate_descent
from flight_model_paramaterized import combine_trajectories
from wind_model_time_dependent import get_wind


def _utc(value: Any) -> datetime:
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if not isinstance(value, datetime):
        raise TypeError("datetime_utc must be an ISO timestamp or datetime.")
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _distance_m(lat1, lon1, lat2, lon2) -> float:
    radius = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * radius * math.asin(min(1.0, math.sqrt(a)))


def _finite_number(value, field_name: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be numeric.") from exc
    if not math.isfinite(result):
        raise ValueError(f"{field_name} must be finite.")
    return result


def _point_datetime(point: dict, launch_datetime: datetime) -> datetime | None:
    if point.get("datetime_utc"):
        return _utc(point["datetime_utc"])
    # Some legacy trajectory outputs have only time_s.
    if point.get("time_s") is not None:
        return launch_datetime.timestamp() and (
            launch_datetime
            + __import__("datetime").timedelta(seconds=float(point["time_s"]))
        )
    if point.get("flight_time_s") is not None:
        from datetime import timedelta
        return launch_datetime + timedelta(seconds=float(point["flight_time_s"]))
    return None


class LiveTrajectoryManager:
    """
    Keep the original forecast, actual telemetry and latest revised forecast.

    V2 supports telemetry supplied during ascent. Each update predicts from
    that observed state through burst and parachute landing.
    """

    def __init__(self, parameters, baseline_result, output_dir=None):
        if not baseline_result or not baseline_result.get("success"):
            raise ValueError("Pass a successful result returned by run_flight(parameters).")
        if not baseline_result.get("trajectory"):
            raise ValueError("Baseline result contains no trajectory.")

        self.parameters = deepcopy(parameters)
        self.original_prediction = deepcopy(baseline_result["trajectory"])
        self.actual_telemetry: list[dict] = []
        self.latest_revised_prediction: list[dict] = []
        self.latest_update: dict | None = None

        self.launch_datetime = _utc(self.parameters["launch_datetime"])
        self.output_dir = (
            Path(output_dir)
            if output_dir
            else PROJECT_ROOT / "live_trajectory" / "results"
        )
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Keep launch reference conditions fixed between telemetry updates.
        launch_wind = get_wind(
            float(self.parameters["latitude"]),
            float(self.parameters["longitude"]),
            float(self.parameters["launch_altitude"]),
            self.launch_datetime,
        )
        self.launch_pressure_hpa = float(launch_wind["pressure_hpa"])
        self.launch_temperature_K = float(launch_wind["temperature_C"]) + 273.15

        self._validate_ascent_model_interface()

    @staticmethod
    def _validate_ascent_model_interface():
        """
        The reforecast must start at elapsed mission time, not time zero.
        Fail early if the installed ascent model cannot do that.
        """
        sig = inspect.signature(simulate_ascent)
        if "start_time_s" not in sig.parameters:
            raise RuntimeError(
                "The installed ascent_model_time_dependent.simulate_ascent() "
                "does not accept start_time_s. Use the time-dependent ascent "
                "model version that supports start_time_s before running V2."
            )

    def _nearest_original(self, telemetry_dt):
        candidates = []
        for point in self.original_prediction:
            try:
                point_dt = _point_datetime(point, self.launch_datetime)
            except (TypeError, ValueError, KeyError):
                continue
            if point_dt is not None:
                candidates.append((point_dt, point))
        if not candidates:
            return None
        return min(candidates, key=lambda item: abs((item[0] - telemetry_dt).total_seconds()))[1]

    def _original_time_bounds(self):
        times = []
        for point in self.original_prediction:
            try:
                dt = _point_datetime(point, self.launch_datetime)
            except (TypeError, ValueError, KeyError):
                continue
            if dt is not None:
                times.append(dt)
        return (min(times), max(times)) if times else (self.launch_datetime, None)

    def _make_balloon(self):
        p = self.parameters
        return Balloon(
            payload_mass=p["payload_mass"],
            envelope_mass=p["envelope_mass"],
            helium_mass=p["helium_mass"],
            initial_volume=p["initial_volume"],
            burst_diameter=p["burst_diameter"],
            drag_coefficient=p["balloon_cd"],
        )

    def _run_remaining_ascent(self, point, elapsed_s):
        p = self.parameters
        sig = inspect.signature(simulate_ascent)
        supported = sig.parameters

        # Pass only kwargs accepted by the installed version. Some older
        # versions do not have burst_altitude; physical burst is determined
        # by Balloon.has_burst() in the ascent model.
        kwargs = {
            "launch_latitude": point["latitude"],
            "launch_longitude": point["longitude"],
            "launch_altitude": point["altitude_m"],
            "balloon": self._make_balloon(),
            # Keep the original launch datetime. start_time_s advances the
            # weather-query clock to the supplied telemetry timestamp.
            "launch_datetime": self.launch_datetime,
            "maximum_altitude": p["maximum_altitude"],
            "time_step": p["ascent_time_step"],
            "ascent_rate": p["ascent_rate"],
            "start_time_s": elapsed_s,
            "launch_pressure_hpa": self.launch_pressure_hpa,
            "launch_temperature_K": self.launch_temperature_K,
        }
        if "burst_altitude" in supported and "burst_altitude" in p:
            kwargs["burst_altitude"] = p["burst_altitude"]

        kwargs = {key: value for key, value in kwargs.items() if key in supported}
        trajectory = simulate_ascent(**kwargs)
        if not trajectory:
            raise RuntimeError("Remaining-ascent simulation returned no trajectory.")
        return trajectory

    def _run_descent(self, burst_point):
        p = self.parameters
        return simulate_descent(
            burst_latitude=float(burst_point["latitude"]),
            burst_longitude=float(burst_point["longitude"]),
            burst_altitude=float(burst_point["altitude_m"]),
            ground_altitude=float(p["ground_altitude"]),
            payload_mass=float(p["payload_mass"]),
            parachute_diameter=float(p["parachute_diameter"]),
            parachute_cd=float(p["parachute_cd"]),
            dt=float(p["descent_time_step"]),
            burst_datetime=burst_point["datetime_utc"],
            descent_rate=p.get("descent_rate"),
        )

    def update(self, telemetry):
        """
        Reforecast from an observed state during ASCENT.

        Required:
            datetime_utc, latitude, longitude, altitude_m

        Optional:
            phase='ascent', wind_u, wind_v, wind_speed_mps,
            wind_direction_deg

        The output trajectory begins at the supplied telemetry point and
        continues through predicted burst and landing.
        """
        required = ("datetime_utc", "latitude", "longitude", "altitude_m")
        missing = [key for key in required if key not in telemetry]
        if missing:
            raise ValueError("Missing telemetry fields: " + ", ".join(missing))

        point = dict(telemetry)
        current_dt = _utc(point["datetime_utc"])
        point["datetime_utc"] = current_dt.isoformat()
        point["latitude"] = _finite_number(point["latitude"], "latitude")
        point["longitude"] = _finite_number(point["longitude"], "longitude")
        point["altitude_m"] = _finite_number(point["altitude_m"], "altitude_m")
        point["phase"] = str(point.get("phase", "ascent")).strip().lower()

        if not -90.0 <= point["latitude"] <= 90.0:
            raise ValueError("latitude must be between -90 and 90 degrees.")
        if not -180.0 <= point["longitude"] <= 180.0:
            raise ValueError("longitude must be between -180 and 180 degrees.")
        if point["altitude_m"] < float(self.parameters["ground_altitude"]):
            raise ValueError("altitude_m is below the configured ground altitude.")
        if point["phase"] != "ascent":
            raise NotImplementedError(
                "This V2 update accepts an observed point during ASCENT. "
                "It predicts the remaining ascent, burst and descent. "
                "A reforecast starting midway through DESCENT needs the "
                "descent model to accept measured vertical velocity."
            )

        elapsed_s = (current_dt - self.launch_datetime).total_seconds()
        if elapsed_s < 0:
            raise ValueError("Telemetry timestamp is earlier than launch.")

        start_bound, end_bound = self._original_time_bounds()
        if end_bound is not None and current_dt > end_bound:
            raise ValueError(
                "Telemetry timestamp is later than the baseline trajectory. "
                "Check the mission time and weather-forecast coverage."
            )

        if self.actual_telemetry:
            previous_dt = _utc(self.actual_telemetry[-1]["datetime_utc"])
            if current_dt <= previous_dt:
                raise ValueError("Telemetry timestamps must be strictly increasing.")

        original_point = self._nearest_original(current_dt)
        horizontal_error_m = None
        altitude_error_m = None
        if original_point:
            horizontal_error_m = _distance_m(
                point["latitude"],
                point["longitude"],
                float(original_point["latitude"]),
                float(original_point["longitude"]),
            )
            altitude_error_m = (
                point["altitude_m"] - float(original_point["altitude_m"])
            )

        # 1. Reforecast the remaining ascent from the supplied state/time.
        revised_ascent = self._run_remaining_ascent(point, elapsed_s)

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

        # Avoid duplicate start rows if simulate_ascent already returns its
        # initial state at start_time_s.
        revised_ascent = [
            measured_state,
            *[
                dict(row)
                for row in revised_ascent
                if abs(float(row.get("time_s", elapsed_s)) - elapsed_s) > 1e-6
            ],
        ]

        # Ensure every point has an absolute UTC timestamp. The ascent model
        # should provide this; this fallback derives it from mission elapsed time.
        from datetime import timedelta
        for row in revised_ascent:
            if not row.get("datetime_utc") and row.get("time_s") is not None:
                row["datetime_utc"] = (
                    self.launch_datetime + timedelta(seconds=float(row["time_s"]))
                ).isoformat()

        # 2. Find the predicted burst point and calculate descent.
        burst_candidates = [
            row for row in revised_ascent
            if str(row.get("phase", "")).lower() == "burst"
        ]
        revised_burst = dict(burst_candidates[-1]) if burst_candidates else None
        revised_descent = []
        revised_landing = None

        if revised_burst is not None:
            if not revised_burst.get("datetime_utc"):
                revised_burst["datetime_utc"] = (
                    self.launch_datetime
                    + timedelta(seconds=float(revised_burst["time_s"]))
                ).isoformat()

            revised_descent = self._run_descent(revised_burst)
            if not revised_descent:
                raise RuntimeError("Descent simulation returned no trajectory.")
            revised_landing = dict(revised_descent[-1])

        # 3. Combine using the absolute mission elapsed time at burst.
        burst_time_s = (
            float(revised_burst["time_s"])
            if revised_burst is not None
            else 0.0
        )
        revised_combined = combine_trajectories(
            revised_ascent,
            revised_descent,
            burst_time_s,
        )

        landing_deviation_m = None
        original_landing = None
        if revised_landing is not None:
            original_landing = self._find_original_landing()
            if original_landing is not None:
                landing_deviation_m = _distance_m(
                    float(revised_landing["latitude"]),
                    float(revised_landing["longitude"]),
                    float(original_landing["latitude"]),
                    float(original_landing["longitude"]),
                )

            # Add absolute mission time to descent endpoint for easier use.
            revised_landing["mission_time_s"] = (
                burst_time_s + float(revised_landing.get("time_s", 0.0))
            )

        result = {
            "success": True,
            "telemetry": point,
            "elapsed_s": elapsed_s,
            "original_prediction_at_telemetry": original_point,
            "deviation_from_original_m": horizontal_error_m,
            "altitude_error_from_original_m": altitude_error_m,
            "revised_burst": revised_burst,
            "revised_landing": revised_landing,
            "original_landing": original_landing,
            "landing_deviation_from_original_m": landing_deviation_m,
            "revised_ascent": revised_ascent,
            "revised_descent": revised_descent,
            "revised_trajectory": revised_combined,
            "forecast_status": (
                "complete_to_landing"
                if revised_landing is not None
                else "ascent_reforecast_only_no_burst_detected"
            ),
        }

        # Commit state only after all calculations have succeeded.
        self.actual_telemetry.append(point)
        self.latest_revised_prediction = revised_combined
        self.latest_update = result
        return result

    def _find_original_landing(self):
        for point in reversed(self.original_prediction):
            phase = str(point.get("phase", "")).lower()
            if phase in ("landing", "landed"):
                return dict(point)
        return dict(self.original_prediction[-1]) if self.original_prediction else None

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
            preferred = [
                "track", "datetime_utc", "time_s", "flight_time_s",
                "phase", "latitude", "longitude", "altitude_m",
            ]
            fields = [key for key in preferred if key in fields] + [
                key for key in fields if key not in preferred
            ]
            with csv_path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(
                    handle, fieldnames=fields, extrasaction="ignore"
                )
                writer.writeheader()
                writer.writerows(rows)

        json_path = self.output_dir / "latest_live_update.json"
        json_path.write_text(
            json.dumps(self.latest_update, indent=2, default=str),
            encoding="utf-8",
        )

        plot_path = self.output_dir / "trajectory_comparison.png"
        self.plot(plot_path)

        return {
            "csv": str(csv_path),
            "json": str(json_path),
            "plot": str(plot_path),
        }

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
                label=label,
                marker=marker,
                markersize=3,
            )

        draw(self.original_prediction, "Original prediction")
        draw(self.actual_telemetry, "Actual telemetry", "o")
        draw(self.latest_revised_prediction, "Updated remaining prediction")

        ax.set_xlabel("Longitude (degrees)")
        ax.set_ylabel("Latitude (degrees)")
        ax.set_title("Remaining flight forecast: original vs actual vs revised")
        ax.grid(True)
        ax.legend()
        ax.set_aspect("equal", adjustable="datalim")
        fig.tight_layout()

        if output_path:
            fig.savefig(output_path, dpi=180)
        plt.close(fig)
        return str(output_path) if output_path else None
