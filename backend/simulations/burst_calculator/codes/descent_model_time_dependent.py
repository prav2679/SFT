import math
from datetime import datetime, timedelta, timezone

from wind_model_time_dependent import get_wind
from descent_physics import Parachute


EARTH_RADIUS = 6371000.0
INTERNAL_DT = 1.0

def move_balloon(latitude, longitude, north_m, east_m):
    
    latitude_rad = math.radians(latitude)
    new_latitude = (latitude+ math.degrees(north_m / EARTH_RADIUS))
    cos_lat = max(abs(math.cos(latitude_rad)), 1e-12)
    new_longitude = (longitude+ math.degrees(east_m /(EARTH_RADIUS * cos_lat)))
    return new_latitude, new_longitude

def _as_utc(value):

    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))

    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)

    return value.astimezone(timezone.utc)



def _state(
    time_s,
    dt_utc,
    latitude,
    longitude,
    altitude,
    wind,
    descent_rate,
    terminal_velocity,
    acceleration,
    phase
):

    return {

        "time_s": time_s,

        "datetime_utc":
            dt_utc.isoformat(),

        "latitude":
            latitude,

        "longitude":
            longitude,

        "altitude_m":
            altitude,

        "wind_u":
            wind["U"],

        "wind_v":
            wind["V"],

        "wind_speed":
            wind["wind_speed_mps"],

        "temperature_C":
            wind["temperature_C"],

        "pressure_hpa":
            wind["pressure_hpa"],

        "air_density":
            wind["air_density"],

        "vertical_velocity_mps":
            descent_rate,

        "vertical_acceleration_mps2":
            acceleration,

        "terminal_velocity_mps":
            terminal_velocity,

        "phase":
            phase
    }



def _time_to_distance(
    parachute,
    air_density,
    velocity,
    target_distance,
    max_time
):

    if target_distance <= 0:
        return 0.0

    full_distance = parachute.exact_distance_step(air_density, velocity, max_time)
    if full_distance <= target_distance:
        return max_time

    low = 0.0
    high = max_time

    for _ in range(50):

        mid = 0.5 * (low + high)

        distance = (parachute.exact_distance_step(air_density,velocity,mid))

        if distance < target_distance:
            low = mid

        else:
            high = mid

    return 0.5 * (low + high)



def simulate_descent(
    burst_latitude,
    burst_longitude,
    burst_altitude,
    ground_altitude,
    payload_mass,
    parachute_diameter,
    parachute_cd=1.5,
    dt=1.0,
    burst_datetime=None,
    descent_rate=None,
    initial_vertical_velocity=0.0
):

    if dt <= 0:
        raise ValueError("dt must be greater than zero.")

    if payload_mass <= 0:
        raise ValueError("payload_mass must be greater than zero.")

    if parachute_diameter <= 0:
        raise ValueError("parachute_diameter must be greater than zero.")

    if parachute_cd <= 0:
        raise ValueError("parachute_cd must be greater than zero.")

    if ground_altitude >= burst_altitude:

        return [{
            "time_s": 0.0,

            "datetime_utc":
                _as_utc(burst_datetime).isoformat()
                if burst_datetime
                else None,

            "latitude":
                burst_latitude,

            "longitude":
                burst_longitude,

            "altitude_m":
                ground_altitude,

            "wind_u": 0.0,
            "wind_v": 0.0,
            "wind_speed": 0.0,

            "temperature_C": 0.0,
            "pressure_hpa": 0.0,
            "air_density": 0.0,

            "vertical_velocity_mps": 0.0,
            "vertical_acceleration_mps2": 0.0,
            "terminal_velocity_mps": 0.0,

            "phase": "landing"
        }]

    if burst_datetime is None:

        raise ValueError(
            "burst_datetime is required for "
            "the time-dependent GFS model."
        )

    burst_datetime = _as_utc(burst_datetime)

    parachute = Parachute(
        payload_mass=payload_mass,
        parachute_diameter=parachute_diameter,
        drag_coefficient=parachute_cd
    )

    

    latitude = float(burst_latitude)
    longitude = float(burst_longitude)
    altitude = float(burst_altitude)
    time = 0.0

    # SFT Mission Control addition (additive, default keeps the original behaviour): downward speed in m/s
    # at the start of the descent. 0.0 = parachute deploys from rest. Used to re-forecast a descent from a
    # measured mid-descent telemetry state.
    initial_vertical_velocity = float(initial_vertical_velocity)
    if not math.isfinite(initial_vertical_velocity) or initial_vertical_velocity < 0:
        raise ValueError("initial_vertical_velocity must be a finite downward speed >= 0 m/s.")
    vertical_velocity = initial_vertical_velocity

    trajectory = []

#header

    print()
    print("=" * 75)
    print("              AERODYNAMIC GFS PARACHUTE DESCENT")
    print("=" * 75)

    print()
    print(
        f"Burst latitude       : "
        f"{burst_latitude:.6f} deg"
    )

    print(
        f"Burst longitude      : "
        f"{burst_longitude:.6f} deg"
    )

    print(
        f"Burst altitude       : "
        f"{burst_altitude:.1f} m"
    )

    print()
    print(
        f"Payload mass         : "
        f"{payload_mass:.3f} kg"
    )

    print(
        f"Parachute diameter   : "
        f"{parachute_diameter:.3f} m"
    )

    print(
        f"Parachute Cd         : "
        f"{parachute_cd:.3f}"
    )

    print(
        f"Parachute area       : "
        f"{parachute.area():.3f} m²"
    )

    print()
    print(
        "Descent rate is calculated "
        "from parachute physics."
    )

    print()

#wind atmospheric state
    wind = get_wind(
        latitude,
        longitude,
        altitude,
        burst_datetime
    )

    density = wind["air_density"]

    terminal_velocity = (parachute.terminal_velocity(density))

    acceleration = (parachute.vertical_acceleration(density,vertical_velocity))

    trajectory.append(
        _state(

            time_s=0.0,

            dt_utc=
                burst_datetime,

            latitude=
                latitude,

            longitude=
                longitude,

            altitude=
                altitude,

            wind=
                wind,

            descent_rate=
                vertical_velocity,

            terminal_velocity=
                terminal_velocity,

            acceleration=
                acceleration,

            phase=
                "descent"
        )
    )

    
    next_output_time = dt


    while altitude > ground_altitude:

     

        current_datetime = (burst_datetime+ timedelta(seconds=time))

        wind = get_wind(
            latitude,
            longitude,
            altitude,
            current_datetime
        )

        density = wind["air_density"]

        terminal_velocity = (
            parachute.terminal_velocity(density))


        step = INTERNAL_DT

        remaining_output_time = (next_output_time - time)

        if remaining_output_time > 0:

            step = min(step,remaining_output_time)

        remaining_height = (altitude -ground_altitude)

        distance_possible = (parachute.exact_distance_step(
                density,
                vertical_velocity,
                step
            )
        )

    
        if distance_possible >= remaining_height:

            actual_step = (
                _time_to_distance(
                    parachute,
                    density,
                    vertical_velocity,
                    remaining_height,
                    step
                )
            )

        else:

            actual_step = step

        new_velocity = (
            parachute.exact_velocity_step(
                density,
                vertical_velocity,
                actual_step
            )
        )

     
        acceleration = (parachute.vertical_acceleration(
                density,
                vertical_velocity
            )
        )

        north_distance = (wind["V"] * actual_step)

        east_distance = (wind["U"] * actual_step)

        latitude, longitude = (
            move_balloon(
                latitude,
                longitude,
                north_distance,
                east_distance
            )
        )

        altitude -= (
            parachute.exact_distance_step(
                density,
                vertical_velocity,
                actual_step
            )
        )

    
        if altitude < ground_altitude:
            altitude = ground_altitude

        time += actual_step

        vertical_velocity = (new_velocity)

        if altitude <= (ground_altitude + 1e-9):

            landing_datetime = (burst_datetime + timedelta(seconds=time))

            trajectory.append(
                _state(

                    time_s=time,

                    dt_utc=
                        landing_datetime,

                    latitude=
                        latitude,

                    longitude=
                        longitude,

                    altitude=
                        ground_altitude,

                    wind=
                        wind,

                    descent_rate=
                        vertical_velocity,

                    terminal_velocity=
                        terminal_velocity,

                    acceleration=
                        acceleration,

                    phase=
                        "landing"
                )
            )

            break


        if (time >=next_output_time - 1e-9):

            state_datetime = (burst_datetime + timedelta(seconds=time))

            trajectory.append(
                _state(

                    time_s=time,

                    dt_utc=
                        state_datetime,

                    latitude=
                        latitude,

                    longitude=
                        longitude,

                    altitude=
                        altitude,

                    wind=
                        wind,

                    descent_rate=
                        vertical_velocity,

                    terminal_velocity=
                        terminal_velocity,

                    acceleration=
                        acceleration,

                    phase=
                        "descent"
                )
            )

            next_output_time += dt
#display

        if (
            len(trajectory) == 2
            or
            int(time) % 60 == 0
        ):

            print(
                f"t = {time:7.1f} s | "
                f"alt = {altitude:8.1f} m | "
                f"Vdown = "
                f"{vertical_velocity:6.2f} m/s | "
                f"Vterm = "
                f"{terminal_velocity:6.2f} m/s | "
                f"wind = "
                f"{wind['wind_speed_mps']:6.2f} m/s"
            )

        # ----------------------------------------------------
        # SAFETY LIMIT
        # ----------------------------------------------------

        if time > 7200:

            print()
            print(
                "WARNING: Maximum descent "
                "simulation time reached."
            )

            break

    # ========================================================
    # FINAL RESULTS
    # ========================================================

    print()
    print("=" * 75)
    print("                    DESCENT COMPLETE")
    print("=" * 75)

    print()

    print(
        f"Descent time          : "
        f"{time:.1f} s "
        f"({time / 60:.2f} min)"
    )

    print(
        f"Final descent speed   : "
        f"{vertical_velocity:.2f} m/s"
    )

    print(
        f"Final latitude        : "
        f"{latitude:.6f} deg"
    )

    print(
        f"Final longitude       : "
        f"{longitude:.6f} deg"
    )

    print(
        f"Final altitude        : "
        f"{altitude:.1f} m"
    )

    return trajectory