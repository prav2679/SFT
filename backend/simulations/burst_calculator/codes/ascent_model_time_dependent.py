import math
from datetime import datetime, timedelta, timezone

from wind_model_time_dependent import get_wind
from balloon_physics import Balloon

EARTH_RADIUS = 6371000.0


def move_balloon(latitude, longitude, north_m, east_m):
    latitude_rad = math.radians(latitude)
    new_latitude = latitude + math.degrees(north_m / EARTH_RADIUS)

    # Avoid division problems extremely close to the poles.
    cos_lat = max(abs(math.cos(latitude_rad)), 1e-12)
    new_longitude = longitude + math.degrees(east_m / (EARTH_RADIUS * cos_lat))
    return new_latitude, new_longitude


def simulate_ascent(
    launch_latitude,
    launch_longitude,
    launch_altitude,
    balloon,
    launch_datetime=None,
    maximum_altitude=35000,
    time_step=10,
    ascent_rate=5.0,
    start_time_s=0.0,
    launch_pressure_hpa=None,
    launch_temperature_K=None,
    burst_altitude=None,
):
    """Simulate ascent; burst is triggered ONLY by target altitude.

    ``maximum_altitude`` is a safety ceiling. ``burst_altitude`` is the
    commanded burst target. Balloon diameter is recorded for monitoring,
    but is never consulted to decide whether a burst has occurred.
    """
    if ascent_rate <= 0:
        raise ValueError("ascent_rate must be greater than zero.")
    if time_step <= 0:
        raise ValueError("time_step must be greater than zero.")
    if launch_datetime is None:
        raise ValueError("launch_datetime is required for the time-dependent GFS model.")

    if burst_altitude is None:
        # Backward-compatible fallback for older callers. New flight and live
        # controller paths explicitly pass the target burst altitude.
        burst_altitude = maximum_altitude
    burst_altitude = float(burst_altitude)
    maximum_altitude = float(maximum_altitude)
    if burst_altitude <= 0:
        raise ValueError("burst_altitude must be greater than zero.")
    if burst_altitude > maximum_altitude:
        raise ValueError("burst_altitude cannot exceed the maximum-altitude safety ceiling.")

    if isinstance(launch_datetime, str):
        launch_datetime = datetime.fromisoformat(launch_datetime.replace("Z", "+00:00"))
    if launch_datetime.tzinfo is None:
        launch_datetime = launch_datetime.replace(tzinfo=timezone.utc)
    else:
        launch_datetime = launch_datetime.astimezone(timezone.utc)

    latitude = float(launch_latitude)
    longitude = float(launch_longitude)
    altitude = float(launch_altitude)
    time = float(start_time_s)
    trajectory = []

    if launch_pressure_hpa is None or launch_temperature_K is None:
        launch_wind = get_wind(latitude, longitude, altitude, launch_datetime)
        if launch_pressure_hpa is None:
            launch_pressure_hpa = launch_wind["pressure_hpa"]
        if launch_temperature_K is None:
            launch_temperature_K = launch_wind["temperature_C"] + 273.15

    def state_at_current_position(phase):
        current_datetime = launch_datetime + timedelta(seconds=time)
        wind = get_wind(latitude, longitude, altitude, current_datetime)
        pressure_hpa = wind["pressure_hpa"]
        temperature_K = wind["temperature_C"] + 273.15
        volume = balloon.volume_at_altitude(
            pressure_hpa=pressure_hpa,
            temperature_K=temperature_K,
            launch_pressure_hpa=launch_pressure_hpa,
            launch_temperature_K=launch_temperature_K,
        )
        diameter = balloon.diameter_from_volume(volume)
        return {
            "time_s": time,
            "datetime_utc": current_datetime.isoformat(),
            "latitude": latitude,
            "longitude": longitude,
            "altitude_m": altitude,
            "wind_u": wind["U"],
            "wind_v": wind["V"],
            "wind_speed": wind["wind_speed_mps"],
            "temperature_C": wind["temperature_C"],
            "pressure_hpa": pressure_hpa,
            "air_density": wind["air_density"],
            "ascent_rate": ascent_rate,
            "volume_m3": volume,
            "diameter_m": diameter,
            "phase": phase,
        }, wind

    print("\n========================================")
    print("     TARGET-ALTITUDE ASCENT SIMULATION")
    print("========================================")
    print(f"\nLaunch latitude  : {latitude:.6f}°")
    print(f"Launch longitude : {longitude:.6f}°")
    print(f"Launch altitude  : {altitude:.0f} m")
    print(f"Target burst     : {burst_altitude:.0f} m")
    print(f"Safety ceiling   : {maximum_altitude:.0f} m")
    print(f"Constant ascent  : {ascent_rate:.3f} m/s")

    # A live telemetry point may already be at or above the commanded target.
    if altitude >= burst_altitude:
        burst_state, _ = state_at_current_position("burst")
        trajectory.append(burst_state)
        print(f"BURST at telemetry state: {altitude:.1f} m")
        return trajectory

    while altitude < burst_altitude and altitude < maximum_altitude:
        _, wind = state_at_current_position("ascent")
        remaining_to_burst = burst_altitude - altitude
        remaining_to_limit = maximum_altitude - altitude
        dt = min(time_step, remaining_to_burst / ascent_rate, remaining_to_limit / ascent_rate)
        if dt <= 0:
            break

        latitude, longitude = move_balloon(
            latitude, longitude, wind["V"] * dt, wind["U"] * dt
        )
        altitude = min(burst_altitude, altitude + ascent_rate * dt)
        time += dt

        reached_burst = altitude >= burst_altitude - 1e-8
        reached_limit = altitude >= maximum_altitude - 1e-8
        phase = "burst" if reached_burst else ("ascent_limit" if reached_limit else "ascent")
        row, _ = state_at_current_position(phase)
        trajectory.append(row)

        if reached_burst:
            print("\n========================================")
            print("             BALLOON BURST")
            print("========================================")
            print(f"Burst time      : {time / 60:.2f} min")
            print(f"Burst altitude  : {altitude / 1000:.3f} km")
            print(f"Burst latitude  : {latitude:.6f}°")
            print(f"Burst longitude : {longitude:.6f}°")
            print(f"Diameter (info) : {row['diameter_m']:.2f} m")
            print(f"Ascent rate     : {ascent_rate:.2f} m/s")
            break
        if reached_limit:
            print(f"Safety ceiling reached at {altitude:.1f} m before target burst altitude.")
            break

    return trajectory
