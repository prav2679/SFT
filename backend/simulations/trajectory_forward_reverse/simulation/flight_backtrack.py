
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

from wind_model_time_dependent import get_wind
from descent_physics import Parachute
from flight_forward import simulate_mission, export_trajectory_kml, as_utc

EARTH_RADIUS_M = 6_371_000.0


def move_horizontal(lat: float, lon: float, north_m: float, east_m: float):
    lat_rad = math.radians(lat)
    new_lat = lat + math.degrees(north_m / EARTH_RADIUS_M)
    cos_lat = max(abs(math.cos(lat_rad)), 1e-12)
    new_lon = lon + math.degrees(east_m / (EARTH_RADIUS_M * cos_lat))
    new_lon = (new_lon + 180.0) % 360.0 - 180.0
    return new_lat, new_lon


def distance_m(lat1, lon1, lat2, lon2):
    """Great-circle distance between two coordinates, in metres."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


def backtrack_landing(
    target_latitude: float,
    target_longitude: float,
    target_landing_datetime,
    target_altitude_m: float = 25_000.0,
    hold_duration_hours: float = 50.0 / 60.0,
    launch_altitude_m: float = 0.0,
    ascent_rate_mps: float = 6.69,
    payload_mass_kg: float = 5,
    parachute_diameter_m: float = 2.4,
    parachute_cd: float = 1,
    ground_altitude_m: float = 0.0,
    backtrack_step_s: float = 60.0,
    ascent_hold_step_s: float = 60.0,
    descent_output_step_s: float = 10.0,
    kml_path: str = "backtracked_candidate.kml",
):
    """Estimate launch coordinates/time from a desired landing coordinate/time.

    The returned candidate is forward-simulated using flight.simulate_mission.
    All datetimes are interpreted as UTC when naive.
    """
    landing_time = as_utc(target_landing_datetime)
    if not (-90 <= target_latitude <= 90 and -180 <= target_longitude <= 180):
        raise ValueError("Target latitude/longitude are outside valid ranges.")
    if target_altitude_m <= launch_altitude_m:
        raise ValueError("Target altitude must exceed launch altitude.")
    if hold_duration_hours < 0:
        raise ValueError("Hold duration cannot be negative.")
    if min(ascent_rate_mps, payload_mass_kg, parachute_diameter_m, parachute_cd,
           backtrack_step_s, ascent_hold_step_s, descent_output_step_s) <= 0:
        raise ValueError("Rates, masses, diameters, and time steps must be positive.")

    print("\n=== BACKWARD LANDING-TARGET RECONSTRUCTION ===")
    print("This creates a candidate; forward validation determines the actual error.")

    # 1. Backtrack the descent from the known landing location/time.
    lat, lon = float(target_latitude), float(target_longitude)
    altitude = float(ground_altitude_m)
    t = landing_time
    parachute = Parachute(payload_mass_kg, parachute_diameter_m, parachute_cd)
    descent_elapsed_s = 0.0
    descent_reverse_points = [(t, lat, lon, altitude)]

    while altitude < target_altitude_m - 1e-6:
        wind = get_wind(lat, lon, altitude, t)
        rho = float(wind["air_density"])
        vt = max(float(parachute.terminal_velocity(rho)), 0.5)
        # Limit each reverse step so altitude increments remain manageable.
        dt = min(backtrack_step_s, (target_altitude_m - altitude) / vt)
        dz = min(target_altitude_m - altitude, vt * dt)
        # Backward horizontal integration: subtract forward wind displacement.
        lat, lon = move_horizontal(lat, lon, -float(wind["V"]) * dt,
                                   -float(wind["U"]) * dt)
        altitude += dz
        t -= timedelta(seconds=dt)
        descent_elapsed_s += dt
        descent_reverse_points.append((t, lat, lon, altitude))
        if descent_elapsed_s > 3 * 3600:
            raise RuntimeError("Backward descent exceeded 3 hours; check parachute parameters.")

    descent_start_lat, descent_start_lon = lat, lon
    descent_start_time = t

    # 2. Backtrack the specified hold period at the target altitude.
    remaining = hold_duration_hours * 3600.0
    while remaining > 1e-9:
        dt = min(backtrack_step_s, remaining)
        wind = get_wind(lat, lon, target_altitude_m, t)
        lat, lon = move_horizontal(lat, lon, -float(wind["V"]) * dt,
                                   -float(wind["U"]) * dt)
        t -= timedelta(seconds=dt)
        remaining -= dt

    hold_start_lat, hold_start_lon = lat, lon
    hold_start_time = t

    # 3. Backtrack ascent with the configured constant vertical ascent rate.
    altitude = float(target_altitude_m)
    while altitude > launch_altitude_m + 1e-9:
        dz = min(ascent_rate_mps * backtrack_step_s, altitude - launch_altitude_m)
        dt = dz / ascent_rate_mps
        wind = get_wind(lat, lon, altitude, t)
        lat, lon = move_horizontal(lat, lon, -float(wind["V"]) * dt,
                                   -float(wind["U"]) * dt)
        altitude -= dz
        t -= timedelta(seconds=dt)

    launch_lat, launch_lon, launch_time = lat, lon, t

    print(f"Estimated launch: {launch_lat:.6f}, {launch_lon:.6f} at {launch_time.isoformat()}")
    print(f"Estimated descent start: {descent_start_lat:.6f}, {descent_start_lon:.6f} at {descent_start_time.isoformat()}")
    print(f"Approximate descent duration: {descent_elapsed_s / 60:.1f} min")
    print("Running the existing forward mission model for validation...")

    # 4. Forward validation with the user's existing full mission model.
    trajectory = simulate_mission(
        launch_latitude=launch_lat,
        launch_longitude=launch_lon,
        launch_altitude_m=launch_altitude_m,
        launch_datetime=launch_time,
        hold_duration_hours=hold_duration_hours,
        payload_mass_kg=payload_mass_kg,
        parachute_diameter_m=parachute_diameter_m,
        parachute_cd=parachute_cd,
        target_altitude_m=target_altitude_m,
        ascent_rate_mps=ascent_rate_mps,
        ascent_hold_step_s=ascent_hold_step_s,
        descent_output_step_s=descent_output_step_s,
        ground_altitude_m=ground_altitude_m,
    )
    if not trajectory:
        raise RuntimeError("Forward validation returned an empty trajectory.")

    predicted = trajectory[-1]
    error = distance_m(target_latitude, target_longitude,
                       float(predicted["latitude"]), float(predicted["longitude"]))
    time_error_s = (as_utc(predicted["datetime_utc"]) - landing_time).total_seconds()

    print("\n=== FORWARD VALIDATION ===")
    print(f"Target landing : {target_latitude:.6f}, {target_longitude:.6f} at {landing_time.isoformat()}")
    print(f"Predicted      : {predicted['latitude']:.6f}, {predicted['longitude']:.6f} at {predicted['datetime_utc']}")
    print(f"Landing error  : {error / 1000:.3f} km")
    print(f"Landing-time error (predicted - target): {time_error_s / 60:.2f} min")

    if kml_path:
        export_trajectory_kml(trajectory, Path(kml_path))

    return {
        "estimated_launch_latitude": launch_lat,
        "estimated_launch_longitude": launch_lon,
        "estimated_launch_datetime_utc": launch_time.isoformat(),
        "estimated_descent_start_latitude": descent_start_lat,
        "estimated_descent_start_longitude": descent_start_lon,
        "estimated_descent_start_datetime_utc": descent_start_time.isoformat(),
        "predicted_landing_latitude": float(predicted["latitude"]),
        "predicted_landing_longitude": float(predicted["longitude"]),
        "predicted_landing_datetime_utc": predicted["datetime_utc"],
        "landing_error_m": error,
        "landing_time_error_s": time_error_s,
        "trajectory": trajectory,
    }


def main():
    print("Enter desired landing coordinates and time. Times are UTC.")
    target_lat = float(input("Target landing latitude (deg): "))
    target_lon = float(input("Target landing longitude (deg): "))
    landing_text = input("Target landing datetime UTC (YYYY-MM-DD HH:MM): ").strip()
    if len(landing_text) == 16:
        landing_text += ":00"
    landing_time = datetime.fromisoformat(landing_text.replace("Z", "+00:00"))
    hold_min = float(input("Altitude hold duration in minutes [50]: ") or "50")
    target_alt_km = float(input("Target altitude in km [25]: ") or "25")
    payload = float(input("Payload mass in kg [2]: ") or "2")
    chute_diam = float(input("Parachute diameter in metres [2]: ") or "2")
    cd = float(input("Parachute drag coefficient [1.5]: ") or "1.5")
    kml = input("KML output path [backtracked_candidate.kml]: ").strip() or "backtracked_candidate.kml"

    backtrack_landing(
        target_latitude=target_lat,
        target_longitude=target_lon,
        target_landing_datetime=landing_time,
        target_altitude_m=target_alt_km * 1000.0,
        hold_duration_hours=hold_min / 60.0,
        payload_mass_kg=payload,
        parachute_diameter_m=chute_diam,
        parachute_cd=cd,
        kml_path=kml,
    )


if __name__ == "__main__":
    main()
