import math
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from wind_model_time_dependent import get_wind


EARTH_RADIUS = 6371000.0

TARGET_ALTITUDE = 25000.0       # 25 km
ASCENT_RATE = 5.0                # m/s
TIME_STEP = 60.0                 # seconds
HOLD_DURATION_HOURS = 120.0      # 5 days

KML_FILENAME = r"hover_5days\results\balloon_120hr_trajectory.kml"


# ============================================================
# HORIZONTAL MOVEMENT
# ============================================================

def move_balloon(latitude, longitude, north_m, east_m):
    """
    Update latitude and longitude based on horizontal displacement.

    north_m: northward displacement in metres
    east_m: eastward displacement in metres
    """

    latitude_rad = math.radians(latitude)

    new_latitude = latitude + math.degrees(
        north_m / EARTH_RADIUS
    )

    cos_lat = max(abs(math.cos(latitude_rad)), 1e-12)

    new_longitude = longitude + math.degrees(
        east_m / (EARTH_RADIUS * cos_lat)
    )

    # Normalize longitude to [-180, 180).
    new_longitude = (new_longitude + 180.0) % 360.0 - 180.0

    return new_latitude, new_longitude


# ============================================================
# KML EXPORT
# ============================================================

def export_trajectory_kml(
    trajectory,
    filename=KML_FILENAME
):
    """
    Export trajectory as a 3D KML file for Google Earth.

    Coordinates use KML order:
        longitude, latitude, altitude

    Altitude mode:
        absolute
    """

    if not trajectory:
        raise ValueError("Cannot export an empty trajectory.")

    ns = "http://www.opengis.net/kml/2.2"

    ET.register_namespace("", ns)

    def tag(name):
        return f"{{{ns}}}{name}"

    root = ET.Element(tag("kml"))
    document = ET.SubElement(root, tag("Document"))

    ET.SubElement(
        document, tag("name")
    ).text = "Balloon 120-Hour Trajectory"

    ET.SubElement(
        document, tag("description")
    ).text = (
        "Balloon ascent to 25 km followed by 120 hours "
        "of idealised altitude hold using time-dependent "
        "GFS wind data. No burst or descent is simulated."
    )

    # --------------------------------------------------------
    # TRAJECTORY STYLE
    # --------------------------------------------------------

    style = ET.SubElement(document, tag("Style"))
    style.set("id", "trajectoryStyle")

    line_style = ET.SubElement(style, tag("LineStyle"))

    # KML color format: alpha, blue, green, red.
    ET.SubElement(
        line_style, tag("color")
    ).text = "ff00a5ff"

    ET.SubElement(
        line_style, tag("width")
    ).text = "4"

    # --------------------------------------------------------
    # COMPLETE 3D TRAJECTORY
    # --------------------------------------------------------

    placemark = ET.SubElement(document, tag("Placemark"))

    ET.SubElement(
        placemark, tag("name")
    ).text = "Balloon Flight Path"

    ET.SubElement(
        placemark, tag("styleUrl")
    ).text = "#trajectoryStyle"

    linestring = ET.SubElement(
        placemark, tag("LineString")
    )

    ET.SubElement(
        linestring, tag("extrude")
    ).text = "0"

    ET.SubElement(
        linestring, tag("tessellate")
    ).text = "1"

    ET.SubElement(
        linestring, tag("altitudeMode")
    ).text = "absolute"

    coordinates = []

    for point in trajectory:
        lon = float(point["longitude"])
        lat = float(point["latitude"])
        alt = float(point["altitude_m"])

        coordinates.append(
            f"{lon:.7f},{lat:.7f},{alt:.2f}"
        )

    ET.SubElement(
        linestring, tag("coordinates")
    ).text = "\n" + "\n".join(coordinates) + "\n"

    # --------------------------------------------------------
    # LAUNCH MARKER
    # --------------------------------------------------------

    first = trajectory[0]

    launch = ET.SubElement(document, tag("Placemark"))

    ET.SubElement(
        launch, tag("name")
    ).text = "Initial Position"

    ET.SubElement(
        launch, tag("description")
    ).text = (
        f"UTC: {first['datetime_utc']}\n"
        f"Latitude: {first['latitude']:.6f}\n"
        f"Longitude: {first['longitude']:.6f}\n"
        f"Altitude: {first['altitude_m']:.2f} m"
    )

    launch_point = ET.SubElement(launch, tag("Point"))

    ET.SubElement(
        launch_point, tag("altitudeMode")
    ).text = "absolute"

    ET.SubElement(
        launch_point, tag("coordinates")
    ).text = (
        f"{first['longitude']},"
        f"{first['latitude']},"
        f"{first['altitude_m']}"
    )

    # --------------------------------------------------------
    # FINAL POSITION MARKER
    # --------------------------------------------------------

    last = trajectory[-1]

    final = ET.SubElement(document, tag("Placemark"))

    ET.SubElement(
        final, tag("name")
    ).text = "Final Position After 120-Hour Hold"

    ET.SubElement(
        final, tag("description")
    ).text = (
        f"UTC: {last['datetime_utc']}\n"
        f"Latitude: {last['latitude']:.6f}\n"
        f"Longitude: {last['longitude']:.6f}\n"
        f"Altitude: {last['altitude_m']:.2f} m\n"
        f"Phase: {last['phase']}"
    )

    final_point = ET.SubElement(final, tag("Point"))

    ET.SubElement(
        final_point, tag("altitudeMode")
    ).text = "absolute"

    ET.SubElement(
        final_point, tag("coordinates")
    ).text = (
        f"{last['longitude']},"
        f"{last['latitude']},"
        f"{last['altitude_m']}"
    )

    # --------------------------------------------------------
    # SAVE FILE
    # --------------------------------------------------------

    tree = ET.ElementTree(root)

    try:
        ET.indent(tree, space="  ")
    except AttributeError:
        pass

    tree.write(
        filename,
        encoding="utf-8",
        xml_declaration=True
    )

    print("\n========================================")
    print("           KML EXPORT COMPLETE")
    print("========================================")
    print(f"File              : {filename}")
    print(f"Trajectory points : {len(trajectory)}")
    print(f"Final latitude    : {last['latitude']:.6f}")
    print(f"Final longitude   : {last['longitude']:.6f}")
    print(f"Final altitude    : {last['altitude_m'] / 1000:.3f} km")

    return filename


# ============================================================
# ASCENT + 120-HOUR ALTITUDE HOLD SIMULATION
# ============================================================

def simulate_ascent(
    launch_latitude,
    launch_longitude,
    launch_altitude,
    balloon,
    launch_datetime=None,
    maximum_altitude=TARGET_ALTITUDE,
    time_step=TIME_STEP,
    ascent_rate=ASCENT_RATE,
    hold_duration_hours=HOLD_DURATION_HOURS
):
    """
    Simulate ascent to the target altitude and then hold
    that altitude for the specified duration.

    The hold duration starts when the balloon reaches
    the target altitude.

    Horizontal movement is calculated from GFS winds.

    No burst or descent model is included.
    """

    if ascent_rate <= 0:
        raise ValueError("ascent_rate must be greater than zero.")

    if time_step <= 0:
        raise ValueError("time_step must be greater than zero.")

    if hold_duration_hours <= 0:
        raise ValueError("hold_duration_hours must be greater than zero.")

    if maximum_altitude <= launch_altitude:
        raise ValueError(
            "Target altitude must be greater than launch altitude."
        )

    if launch_datetime is None:
        raise ValueError(
            "launch_datetime is required for the time-dependent GFS model."
        )

    if isinstance(launch_datetime, str):
        launch_datetime = datetime.fromisoformat(
            launch_datetime.replace("Z", "+00:00")
        )

    if launch_datetime.tzinfo is None:
        launch_datetime = launch_datetime.replace(
            tzinfo=timezone.utc
        )
    else:
        launch_datetime = launch_datetime.astimezone(
            timezone.utc
        )

    # Initial state.
    latitude = float(launch_latitude)
    longitude = float(launch_longitude)
    altitude = float(launch_altitude)
    time = 0.0

    # The GFS forecast covers 120 hours from launch, so the complete
    # simulation (ascent + altitude hold) must end at this boundary.
    mission_duration_seconds = hold_duration_hours * 3600.0

    hold_start_time = None

    trajectory = []

    print("\n========================================")
    print("   BALLOON 120-HOUR MISSION SIMULATION")
    print("========================================")

    print(f"Launch latitude : {latitude:.6f}°")
    print(f"Launch longitude: {longitude:.6f}°")
    print(f"Launch altitude : {altitude:.2f} m")
    print(f"Target altitude : {maximum_altitude / 1000:.2f} km")
    print(f"Ascent rate     : {ascent_rate:.2f} m/s")
    print(f"Time step       : {time_step:.2f} seconds")
    print(f"Total mission   : {hold_duration_hours:.2f} hours from launch")
    print("Burst detection : Disabled")
    print("Descent model   : Disabled")

    # --------------------------------------------------------
    # STORE INITIAL POSITION
    # --------------------------------------------------------

    initial_datetime = launch_datetime.isoformat()

    trajectory.append({
        "time_s": 0.0,
        "datetime_utc": initial_datetime,
        "latitude": latitude,
        "longitude": longitude,
        "altitude_m": altitude,
        "wind_u": 0.0,
        "wind_v": 0.0,
        "wind_speed": 0.0,
        "temperature_C": None,
        "pressure_hpa": None,
        "air_density": None,
        "ascent_rate": ascent_rate,
        "phase": "ascent"
    })

    # --------------------------------------------------------
    # MAIN SIMULATION LOOP
    # --------------------------------------------------------

    while time < mission_duration_seconds:

        # Clip the final step so the simulation ends at exactly 120 hours
        # and never requests a wind timestamp beyond the available forecast.
        step_limit = min(time_step, mission_duration_seconds - time)

        current_datetime = (
            launch_datetime + timedelta(seconds=time)
        )

        # Obtain GFS wind at the current state.
        wind = get_wind(
            latitude,
            longitude,
            altitude,
            current_datetime
        )

        U = float(wind["U"])
        V = float(wind["V"])

        # -----------------------------------------------
        # PHASE 1: ASCENT
        # -----------------------------------------------

        if altitude < maximum_altitude:

            remaining_altitude = maximum_altitude - altitude

            dt = min(
                step_limit,
                remaining_altitude / ascent_rate
            )

            # The final ascent step must not overshoot 25 km.
            vertical_velocity = ascent_rate

            # Move horizontally using the current wind.
            latitude, longitude = move_balloon(
                latitude,
                longitude,
                V * dt,
                U * dt
            )

            altitude = min(
                maximum_altitude,
                altitude + ascent_rate * dt
            )

            if altitude >= maximum_altitude:
                altitude = maximum_altitude

                # Start the 120-hour timer at arrival.
                hold_start_time = time + dt

                phase = "altitude_hold"
            else:
                phase = "ascent"

        # -----------------------------------------------
        # PHASE 2: ALTITUDE HOLD
        # -----------------------------------------------

        else:

            elapsed_hold = time - hold_start_time

            remaining_hold = max(
                0.0,
                mission_duration_seconds - time
            )

            dt = min(step_limit, remaining_hold)

            vertical_velocity = 0.0
            phase = "altitude_hold"

            # Horizontal drift continues at 25 km.
            latitude, longitude = move_balloon(
                latitude,
                longitude,
                V * dt,
                U * dt
            )

            # Idealised altitude control.
            altitude = maximum_altitude

        # Advance time.
        time += dt

        next_datetime = (
            launch_datetime + timedelta(seconds=time)
        )

        # Record state at the end of this step.
        trajectory.append({
            "time_s": time,
            "datetime_utc": next_datetime.isoformat(),
            "latitude": latitude,
            "longitude": longitude,
            "altitude_m": altitude,
            "wind_u": U,
            "wind_v": V,
            "wind_speed": float(wind["wind_speed_mps"]),
            "temperature_C": wind["temperature_C"],
            "pressure_hpa": wind["pressure_hpa"],
            "air_density": wind["air_density"],
            "ascent_rate": vertical_velocity,
            "phase": phase
        })

        # Display progress approximately every 30 minutes.
        if (
            len(trajectory) == 2
            or time % 1800 < dt
        ):
            hold_elapsed = (
                0.0
                if hold_start_time is None
                else max(0.0, time - hold_start_time) / 3600.0
            )

            print(
                f"Time: {time / 3600:7.2f} h | "
                f"Altitude: {altitude / 1000:6.2f} km | "
                f"Lat: {latitude:9.5f}° | "
                f"Lon: {longitude:10.5f}° | "
                f"Wind: {wind['wind_speed_mps']:6.2f} m/s | "
                f"Hold: {hold_elapsed:7.2f} h"
            )

    # --------------------------------------------------------
    # FINAL SUMMARY
    # --------------------------------------------------------

    total_duration_hours = time / 3600.0

    print("\n========================================")
    print("         MISSION COMPLETED")
    print("========================================")

    print(f"Final altitude : {altitude / 1000:.3f} km")
    print(f"Final latitude : {latitude:.6f}°")
    print(f"Final longitude: {longitude:.6f}°")
    actual_hold_hours = (
        0.0 if hold_start_time is None
        else max(0.0, time - hold_start_time) / 3600.0
    )
    print(f"Actual hold    : {actual_hold_hours:.2f} hours")
    print(f"Total duration : {total_duration_hours:.2f} hours")
    print(f"Trajectory pts : {len(trajectory)}")

    return trajectory


# ============================================================
# MAIN PROGRAM
# ============================================================

if __name__ == "__main__":

    # --------------------------------------------------------
    # MISSION INPUTS
    # --------------------------------------------------------

    launch_latitude = 13.0827
    launch_longitude = 80.2707
    launch_altitude = 0.0

    # Change this to your actual forecast initialization time.
    launch_datetime = datetime(
        2026, 10, 20, 0, 0, 0,
        tzinfo=timezone.utc
    )

    target_altitude = 25000.0
    ascent_rate = 5.0
    time_step = 60.0
    hold_duration_hours = 120.0

    # The existing balloon object is retained for compatibility.
    # This simulation does not use its burst calculations.
    balloon = None

    # --------------------------------------------------------
    # RUN SIMULATION
    # --------------------------------------------------------

    trajectory = simulate_ascent(
        launch_latitude=launch_latitude,
        launch_longitude=launch_longitude,
        launch_altitude=launch_altitude,
        balloon=balloon,
        launch_datetime=launch_datetime,
        maximum_altitude=target_altitude,
        time_step=time_step,
        ascent_rate=ascent_rate,
        hold_duration_hours=hold_duration_hours
    )

    # --------------------------------------------------------
    # EXPORT KML
    # --------------------------------------------------------

    export_trajectory_kml(
        trajectory,
        filename=KML_FILENAME
    )

    print("\nOpen the generated KML file in Google Earth Pro.")