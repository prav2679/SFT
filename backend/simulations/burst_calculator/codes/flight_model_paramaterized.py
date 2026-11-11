import csv
import math
from pathlib import Path

from ascent_model_time_dependent import simulate_ascent
from balloon_physics import Balloon
from descent_model_time_dependent import simulate_descent
from parameter_validation import validate_flight_parameters


# ============================================================
# COMPLETE FLIGHT MODEL
# GUI-PARAMETERIZED VERSION
# ASCENT -> BURST -> DESCENT -> LANDING
# ============================================================

OUTPUT_FILE = r"C:\Users\Praveen Vasudevan\Desktop\SFT\balloon_burst_calculator\results\complete_flight_trajectory.csv"
KML_FILE = r"C:\Users\Praveen Vasudevan\Desktop\SFT\balloon_burst_calculator\results\complete_flight_trajectory.kml"
OUTPUT_DIR = Path(__file__).resolve().parent


# ============================================================
# RUN FLIGHT
# ============================================================

def run_flight(parameters):
    """
    Run the complete balloon flight using parameters supplied
    by the GUI or by another Python program.

    Required keys:

        latitude
        longitude
        launch_altitude

        payload_mass
        envelope_mass
        helium_mass
        initial_volume
        burst_diameter
        balloon_cd

        parachute_diameter
        parachute_cd

        launch_datetime
        ascent_rate
        descent_rate
        ascent_time_step
        descent_time_step

        burst_altitude
        maximum_altitude  (safety ceiling)
        ground_altitude
    """

    # ========================================================
    # READ PARAMETERS
    # ========================================================

    # Validate all inputs before constructing physical models.
    validate_flight_parameters(parameters)

    launch_latitude = parameters["latitude"]
    launch_longitude = parameters["longitude"]
    launch_altitude = parameters["launch_altitude"]
    launch_datetime = parameters["launch_datetime"]
    ascent_rate = parameters["ascent_rate"]
    descent_rate = parameters["descent_rate"]

    if ascent_rate <= 0:
        raise ValueError("ascent_rate must be greater than zero.")
    if descent_rate <= 0:
        raise ValueError("descent_rate must be greater than zero.")

    payload_mass = parameters["payload_mass"]
    envelope_mass = parameters["envelope_mass"]
    helium_mass = parameters["helium_mass"]

    initial_volume = parameters["initial_volume"]
    burst_diameter = parameters["burst_diameter"]
    balloon_cd = parameters["balloon_cd"]

    parachute_diameter = parameters["parachute_diameter"]
    parachute_cd = parameters["parachute_cd"]

    ascent_time_step = parameters["ascent_time_step"]
    descent_time_step = parameters["descent_time_step"]

    burst_altitude = float(parameters["burst_altitude"])
    maximum_altitude = parameters["maximum_altitude"]
    ground_altitude = parameters["ground_altitude"]


    if burst_altitude <= launch_altitude:
        raise ValueError("burst_altitude must be greater than launch_altitude.")
    if burst_altitude > maximum_altitude:
        raise ValueError("burst_altitude cannot exceed maximum_altitude (safety ceiling).")

    # ========================================================
    # CREATE BALLOON
    # ========================================================

    balloon = Balloon(

        payload_mass=payload_mass,

        envelope_mass=envelope_mass,

        helium_mass=helium_mass,

        initial_volume=initial_volume,

        burst_diameter=burst_diameter,

        drag_coefficient=balloon_cd
    )


    # ========================================================
    # DESCENDING MASS
    # ========================================================
    #
    # For the current model the payload mass is used.
    #
    # Later this should become:
    #
    # payload + electronics + recovery hardware
    # + parachute + lines + retained components
    #
    # ========================================================

    descent_mass = payload_mass


    # ========================================================
    # PRINT INPUT SUMMARY
    # ========================================================

    print()
    print("=" * 75)
    print("              COMPLETE BALLOON FLIGHT MODEL")
    print("=" * 75)

    print()
    print("INPUT PARAMETERS")
    print("-" * 75)

    print(
        f"Launch latitude       : "
        f"{launch_latitude:.6f} deg"
    )

    print(
        f"Launch longitude      : "
        f"{launch_longitude:.6f} deg"
    )

    print(
        f"Launch altitude       : "
        f"{launch_altitude:.1f} m"
    )

    print(
        f"Payload mass          : "
        f"{payload_mass:.2f} kg"
    )

    print(
        f"Envelope mass         : "
        f"{envelope_mass:.2f} kg"
    )

    print(
        f"Helium mass           : "
        f"{helium_mass:.2f} kg"
    )

    print(
        f"Initial volume        : "
        f"{initial_volume:.2f} m3"
    )

    print(
        f"Burst diameter        : "
        f"{burst_diameter:.2f} m"
    )

    print(
        f"Balloon Cd            : "
        f"{balloon_cd:.2f}"
    )

    print(
        f"Parachute diameter    : "
        f"{parachute_diameter:.2f} m"
    )

    print(
        f"Parachute Cd          : "
        f"{parachute_cd:.2f}"
    )

    print(
        f"Maximum altitude      : "
        f"{maximum_altitude:.1f} m"
    )

    print(
        f"Ground altitude       : "
        f"{ground_altitude:.1f} m"
    )
    print(f"Ascent rate           : {ascent_rate:.2f} m/s")
    print(f"Descent rate          : {descent_rate:.2f} m/s")


    # ========================================================
    # 1. ASCENT
    # ========================================================

    print()
    print("=" * 75)
    print("                         ASCENT")
    print("=" * 75)

    ascent_trajectory = simulate_ascent(

        launch_latitude=launch_latitude,

        launch_longitude=launch_longitude,

        launch_altitude=launch_altitude,

        balloon=balloon,

        launch_datetime=launch_datetime,

        maximum_altitude=maximum_altitude,

        burst_altitude=burst_altitude,

        time_step=ascent_time_step,

        ascent_rate=ascent_rate
    )


    # ========================================================
    # CHECK ASCENT
    # ========================================================

    if not ascent_trajectory:

        raise RuntimeError(
            "Ascent produced no trajectory."
        )


    final_ascent_state = ascent_trajectory[-1]


    # ========================================================
    # CHECK BURST
    # ========================================================

    if final_ascent_state.get("phase") != "burst":

        print()
        print("=" * 75)
        print("                    FLIGHT TERMINATED")
        print("=" * 75)

        print()
        print(
            "The balloon did not reach the burst condition."
        )

        print(
            f"Final altitude : "
            f"{final_ascent_state['altitude_m']:.1f} m"
        )

        print(
            f"Final latitude : "
            f"{final_ascent_state['latitude']:.6f} deg"
        )

        print(
            f"Final longitude: "
            f"{final_ascent_state['longitude']:.6f} deg"
        )

        partial_csv = OUTPUT_DIR / OUTPUT_FILE
        partial_kml = OUTPUT_DIR / KML_FILE

        save_combined_trajectory(
            ascent_trajectory,
            partial_csv
        )
        save_kml_trajectory(
            ascent_trajectory,
            partial_kml
        )

        return {
            "success": False,
            "phase": "ascent_terminated",
            "ascent_trajectory": ascent_trajectory,
            "descent_trajectory": [],
            "trajectory": ascent_trajectory,

            "burst": None,

            "landing": None
        }


    # ========================================================
    # 2. BURST STATE
    # ========================================================

    burst_time = final_ascent_state["time_s"]

    burst_latitude = final_ascent_state["latitude"]

    burst_longitude = final_ascent_state["longitude"]

    burst_altitude = final_ascent_state["altitude_m"]


    # ========================================================
    # BURST SUMMARY
    # ========================================================

    print()
    print("=" * 75)
    print("                       BURST STATE")
    print("=" * 75)

    print()

    print(
        f"Burst time       : "
        f"{burst_time:.1f} s "
        f"({burst_time / 60:.2f} min)"
    )

    print(
        f"Burst latitude   : "
        f"{burst_latitude:.6f} deg"
    )

    print(
        f"Burst longitude  : "
        f"{burst_longitude:.6f} deg"
    )

    print(
        f"Burst altitude   : "
        f"{burst_altitude:.1f} m"
    )

    print(
        f"Burst diameter   : "
        f"{final_ascent_state['diameter_m']:.2f} m"
    )

    print(
        f"Ascent rate      : "
        f"{final_ascent_state['ascent_rate']:.2f} m/s"
    )


    # ========================================================
    # 3. DESCENT
    # ========================================================

    print()
    print("=" * 75)
    print("                         DESCENT")
    print("=" * 75)

    descent_trajectory = simulate_descent(

        burst_latitude=burst_latitude,

        burst_longitude=burst_longitude,

        burst_altitude=burst_altitude,

        ground_altitude=ground_altitude,

        payload_mass=descent_mass,

        parachute_diameter=parachute_diameter,

        parachute_cd=parachute_cd,

        dt=descent_time_step,

        burst_datetime=final_ascent_state["datetime_utc"],

        descent_rate=descent_rate
    )


    # ========================================================
    # CHECK DESCENT
    # ========================================================

    if not descent_trajectory:

        raise RuntimeError(
            "Descent produced no trajectory."
        )


    final_descent_state = descent_trajectory[-1]


    # ========================================================
    # 4. LANDING STATE
    # ========================================================

    landing_latitude = final_descent_state["latitude"]

    landing_longitude = final_descent_state["longitude"]

    landing_altitude = final_descent_state["altitude_m"]

    descent_time = final_descent_state["time_s"]

    total_flight_time = (
        burst_time +
        descent_time
    )


    # ========================================================
    # 5. HORIZONTAL DISTANCE
    # ========================================================

    launch_to_landing_distance = horizontal_distance(

        launch_latitude,
        launch_longitude,

        landing_latitude,
        landing_longitude
    )


    burst_to_landing_distance = horizontal_distance(

        burst_latitude,
        burst_longitude,

        landing_latitude,
        landing_longitude
    )


    # ========================================================
    # 6. COMPLETE RESULTS
    # ========================================================

    print()
    print("=" * 75)
    print("                     FLIGHT COMPLETE")
    print("=" * 75)

    print()
    print("LAUNCH")
    print("-" * 75)

    print(
        f"Latitude         : "
        f"{launch_latitude:.6f} deg"
    )

    print(
        f"Longitude        : "
        f"{launch_longitude:.6f} deg"
    )

    print(
        f"Altitude         : "
        f"{launch_altitude:.1f} m"
    )


    print()
    print("BURST")
    print("-" * 75)

    print(
        f"Time             : "
        f"{burst_time:.1f} s "
        f"({burst_time / 60:.2f} min)"
    )

    print(
        f"Latitude         : "
        f"{burst_latitude:.6f} deg"
    )

    print(
        f"Longitude        : "
        f"{burst_longitude:.6f} deg"
    )

    print(
        f"Altitude         : "
        f"{burst_altitude:.1f} m"
    )


    print()
    print("LANDING")
    print("-" * 75)

    print(
        f"Latitude         : "
        f"{landing_latitude:.6f} deg"
    )

    print(
        f"Longitude        : "
        f"{landing_longitude:.6f} deg"
    )

    print(
        f"Altitude         : "
        f"{landing_altitude:.1f} m"
    )


    print()
    print("FLIGHT TIME")
    print("-" * 75)

    print(
        f"Ascent time      : "
        f"{burst_time:.1f} s "
        f"({burst_time / 60:.2f} min)"
    )

    print(
        f"Descent time     : "
        f"{descent_time:.1f} s "
        f"({descent_time / 60:.2f} min)"
    )

    print(
        f"TOTAL FLIGHT     : "
        f"{total_flight_time:.1f} s "
        f"({total_flight_time / 60:.2f} min)"
    )


    print()
    print("HORIZONTAL DRIFT")
    print("-" * 75)

    print(
        f"Launch → Landing : "
        f"{launch_to_landing_distance:.1f} m "
        f"({launch_to_landing_distance / 1000:.3f} km)"
    )

    print(
        f"Burst → Landing  : "
        f"{burst_to_landing_distance:.1f} m "
        f"({burst_to_landing_distance / 1000:.3f} km)"
    )


    # ========================================================
    # 7. COMBINE TRAJECTORIES
    # ========================================================

    combined_trajectory = combine_trajectories(

        ascent_trajectory,
        descent_trajectory,

        burst_time
    )


    # ========================================================
    # 8. SAVE CSV
    # ========================================================

    output_csv = OUTPUT_DIR / OUTPUT_FILE
    output_kml = OUTPUT_DIR / KML_FILE

    save_combined_trajectory(
        combined_trajectory,
        output_csv
    )

    save_kml_trajectory(
        combined_trajectory,
        output_kml
    )


    # ========================================================
    # RETURN RESULTS TO GUI
    # ========================================================

    return {

        "success": True,

        "phase": "complete",

        "ascent_trajectory": ascent_trajectory,

        "descent_trajectory": descent_trajectory,

        "trajectory": combined_trajectory,

        "burst": {

            "time_s": burst_time,

            "latitude": burst_latitude,

            "longitude": burst_longitude,

            "altitude_m": burst_altitude,

            "diameter_m":
                final_ascent_state["diameter_m"],

            "ascent_rate":
                final_ascent_state["ascent_rate"]
        },

        "landing": {

            "time_s": total_flight_time,

            "latitude": landing_latitude,

            "longitude": landing_longitude,

            "altitude_m": landing_altitude
        },

        "ascent_time_s": burst_time,

        "descent_time_s": descent_time,

        "total_flight_time_s":
            total_flight_time,

        "launch_to_landing_distance_m":
            launch_to_landing_distance,

        "burst_to_landing_distance_m":
            burst_to_landing_distance
    }


# ============================================================
# COMBINE TRAJECTORIES
# ============================================================

def combine_trajectories(
    ascent_trajectory,
    descent_trajectory,
    burst_time
):

    combined = []

    # --------------------------------------------------------
    # ASCENT
    # --------------------------------------------------------

    for point in ascent_trajectory:

        p = dict(point)

        p["flight_time_s"] = point["time_s"]

        combined.append(p)


    # --------------------------------------------------------
    # DESCENT
    # --------------------------------------------------------

    for point in descent_trajectory:

        p = dict(point)

        p["flight_time_s"] = (
            burst_time +
            point["time_s"]
        )

        p["phase"] = "descent"

        combined.append(p)


    return combined


# ============================================================
# SAVE COMPLETE TRAJECTORY
# ============================================================

def save_combined_trajectory(
    trajectory,
    filename
):

    if not trajectory:
        return

    fields = set()

    for point in trajectory:
        fields.update(point.keys())

    # Keep important columns first.
    preferred = [
        "flight_time_s",
        "time_s",
        "phase",
        "latitude",
        "longitude",
        "altitude_m",

        "wind_u",
        "wind_v",
        "wind_speed",

        "temperature_C",
        "pressure_hpa",
        "air_density",

        "ascent_rate",
        "descent_rate",

        "vertical_velocity_mps",
        "vertical_acceleration_mps2",

        "volume_m3",
        "diameter_m"
    ]

    fieldnames = []

    for field in preferred:

        if field in fields:

            fieldnames.append(field)

            fields.remove(field)

    fieldnames.extend(
        sorted(fields)
    )


    with open(
        filename,
        "w",
        newline="",
        encoding="utf-8"
    ) as file:

        writer = csv.DictWriter(
            file,
            fieldnames=fieldnames,
            extrasaction="ignore"
        )

        writer.writeheader()

        writer.writerows(
            trajectory
        )


    print()
    print(
        f"Complete trajectory saved to: {filename}"
    )


# ============================================================
# SAVE KML TRAJECTORY
# ============================================================

def save_kml_trajectory(trajectory, filename):
    if not trajectory:
        return

    coords = [
        f"{float(p['longitude']):.8f},{float(p['latitude']):.8f},{max(float(p['altitude_m']), 0.0):.2f}"
        for p in trajectory
    ]
    launch = trajectory[0]
    burst = next((p for p in trajectory if p.get("phase") == "burst"), max(trajectory, key=lambda p: float(p["altitude_m"])))
    landing = trajectory[-1]

    def point_xml(name, p):
        return f"""    <Placemark>
      <name>{name}</name>
      <Point>
        <altitudeMode>absolute</altitudeMode>
        <coordinates>{float(p['longitude']):.8f},{float(p['latitude']):.8f},{max(float(p['altitude_m']),0.0):.2f}</coordinates>
      </Point>
    </Placemark>
"""

    kml = f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>Balloon Flight Trajectory</name>
    <Style id="flightPath"><LineStyle><width>4</width></LineStyle></Style>
    <Placemark>
      <name>Complete Flight Path</name>
      <styleUrl>#flightPath</styleUrl>
      <LineString>
        <altitudeMode>absolute</altitudeMode>
        <tessellate>1</tessellate>
        <coordinates>{' '.join(coords)}</coordinates>
      </LineString>
    </Placemark>
{point_xml('Launch', launch)}{point_xml('Burst', burst)}{point_xml('Landing', landing)}  </Document>
</kml>
"""

    filename = Path(filename)
    filename.write_text(kml, encoding="utf-8")
    print(f"KML trajectory saved to: {filename}")


# ============================================================
# DISTANCE
# ============================================================

def horizontal_distance(
    latitude1,
    longitude1,
    latitude2,
    longitude2
):

    earth_radius = 6371000.0

    north = (

        latitude2 -
        latitude1

    ) * math.pi / 180.0 * earth_radius


    east = (

        longitude2 -
        longitude1

    ) * math.pi / 180.0 * earth_radius * math.cos(

        math.radians(latitude1)

    )


    return math.sqrt(

        north ** 2 +
        east ** 2

    )


# ============================================================
# COMMAND LINE TEST
# ============================================================

if __name__ == "__main__":

    # Default test values.
    #
    # When launched from the GUI, these values are NOT used.
    # The GUI passes its own parameter dictionary to run_flight().

    test_parameters = {

        "latitude": 13.08,

        "longitude": 80.27,

        "launch_altitude": 0,

        "launch_datetime": "2026-10-02T06:00:00Z",

        "ascent_rate": 6.69,
        "descent_rate": 5.0,


        "payload_mass": 1.0,

        "envelope_mass": 0.5,

        "helium_mass": 0.3,

        "initial_volume": 12.05,

        "burst_diameter": 13.02,

        "balloon_cd": 0.47,


        "parachute_diameter": 2.4,

        "parachute_cd": 1,


        "ascent_time_step": 10.0,

        "descent_time_step": 1.0,


        "burst_altitude": 32000.0,

        "maximum_altitude": 35000.0,

        "ground_altitude": 73.0
    }


    result = run_flight(
        test_parameters
    )

    if result["success"]:

        print()
        print(
            "Flight simulation completed successfully."
        )

        print(
            f"Landing: "
            f"{result['landing']['latitude']:.6f}, "
            f"{result['landing']['longitude']:.6f}"
        )
