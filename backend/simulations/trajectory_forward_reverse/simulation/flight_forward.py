"""Combined balloon ascent, altitude hold, parachute descent and KML export.

Required companion files in the same project folder:
  - wind_model_time_dependent.py (provides get_wind)
  - descent_model_time_dependent.py (provides simulate_descent)
  - descent_physics.py (provides Parachute, imported by descent model)

The hold duration is counted AFTER the balloon reaches the target altitude.
All simulation timestamps are UTC. KML altitude is absolute altitude in metres.
"""

import math
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ascent_model_time_dependent import simulate_ascent
from descent_model_time_dependent import simulate_descent

EARTH_RADIUS = 6_371_000.0
DEFAULT_TARGET_ALTITUDE_M = 25_000.0
DEFAULT_ASCENT_RATE_MPS = 5.0
DEFAULT_ASCENT_HOLD_STEP_S = 60.0
DEFAULT_DESCENT_OUTPUT_STEP_S = 10.0
DEFAULT_GROUND_ALTITUDE_M = 0.0
DEFAULT_KML = Path("hover_5days") / "results" / "balloon_full_mission.kml"


def as_utc(value):
    """Accept ISO text or datetime and return timezone-aware UTC datetime."""
    if isinstance(value, str):
        value = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if not isinstance(value, datetime):
        raise TypeError("launch_datetime must be a datetime or ISO datetime string")
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def move_balloon(latitude, longitude, north_m, east_m):
    """Convert local north/east displacement in metres to lat/lon."""
    lat_rad = math.radians(latitude)
    new_lat = latitude + math.degrees(north_m / EARTH_RADIUS)
    cos_lat = max(abs(math.cos(lat_rad)), 1e-12)
    new_lon = longitude + math.degrees(east_m / (EARTH_RADIUS * cos_lat))
    new_lon = (new_lon + 180.0) % 360.0 - 180.0
    return new_lat, new_lon


def make_state(time_s, when, lat, lon, altitude_m, wind, phase, **extra):
    state = {
        "time_s": float(time_s),
        "datetime_utc": as_utc(when).isoformat(),
        "latitude": float(lat),
        "longitude": float(lon),
        "altitude_m": float(altitude_m),
        "wind_u": float(wind.get("U", 0.0)),
        "wind_v": float(wind.get("V", 0.0)),
        "wind_speed": float(wind.get("wind_speed_mps", 0.0)),
        "temperature_C": wind.get("temperature_C"),
        "pressure_hpa": wind.get("pressure_hpa"),
        "air_density": wind.get("air_density"),
        "phase": phase,
    }
    state.update(extra)
    return state


def export_trajectory_kml(trajectory, filename=DEFAULT_KML):
    """Write the complete ascent/hold/descent path and event markers to KML."""
    if not trajectory:
        raise ValueError("Cannot export an empty trajectory.")

    filename = Path(filename)
    filename.parent.mkdir(parents=True, exist_ok=True)
    ns = "http://www.opengis.net/kml/2.2"
    ET.register_namespace("", ns)

    def tag(name):
        return f"{{{ns}}}{name}"

    root = ET.Element(tag("kml"))
    doc = ET.SubElement(root, tag("Document"))
    ET.SubElement(doc, tag("name")).text = "Balloon Full Mission Trajectory"
    ET.SubElement(doc, tag("description")).text = (
        "Combined time-dependent-wind ascent, altitude hold, and parachute descent. "
        "KML coordinates are longitude, latitude, absolute altitude in metres."
    )

    for style_id, color, width in (
        ("flightPath", "ff00a5ff", "4"),
        ("ascentPath", "ff00ff00", "3"),
        ("holdPath", "ffffaa00", "3"),
        ("descentPath", "ffff0000", "3"),
    ):
        style = ET.SubElement(doc, tag("Style"), id=style_id)
        line = ET.SubElement(style, tag("LineStyle"))
        ET.SubElement(line, tag("color")).text = color
        ET.SubElement(line, tag("width")).text = width

    # Overall continuous 3-D path.
    pm = ET.SubElement(doc, tag("Placemark"))
    ET.SubElement(pm, tag("name")).text = "Complete Flight Path"
    ET.SubElement(pm, tag("styleUrl")).text = "#flightPath"
    line = ET.SubElement(pm, tag("LineString"))
    ET.SubElement(line, tag("tessellate")).text = "1"
    ET.SubElement(line, tag("altitudeMode")).text = "absolute"
    ET.SubElement(line, tag("coordinates")).text = "\n" + "\n".join(
        f"{p['longitude']:.7f},{p['latitude']:.7f},{p['altitude_m']:.2f}"
        for p in trajectory
    ) + "\n"

    # Separate phase paths make the mission easier to inspect in Google Earth.
    for phase, label, style_id in (
        ("ascent", "Ascent", "#ascentPath"),
        ("altitude_hold", "Altitude Hold", "#holdPath"),
        ("descent", "Parachute Descent", "#descentPath"),
    ):
        pts = [p for p in trajectory if p.get("phase") == phase]
        if len(pts) < 2:
            continue
        phase_pm = ET.SubElement(doc, tag("Placemark"))
        ET.SubElement(phase_pm, tag("name")).text = label
        ET.SubElement(phase_pm, tag("styleUrl")).text = style_id
        phase_line = ET.SubElement(phase_pm, tag("LineString"))
        ET.SubElement(phase_line, tag("tessellate")).text = "1"
        ET.SubElement(phase_line, tag("altitudeMode")).text = "absolute"
        ET.SubElement(phase_line, tag("coordinates")).text = "\n" + "\n".join(
            f"{p['longitude']:.7f},{p['latitude']:.7f},{p['altitude_m']:.2f}"
            for p in pts
        ) + "\n"

    # Launch, arrival at hold altitude, descent start, and landing markers.
    marker_specs = [
        ("Launch", trajectory[0]),
        ("Hold Altitude Reached", next((p for p in trajectory if p.get("phase") == "altitude_hold"), trajectory[0])),
        ("Descent Started", next((p for p in trajectory if p.get("phase") == "descent"), trajectory[-1])),
        ("Final Position / Landing", trajectory[-1]),
    ]
    for name, p in marker_specs:
        marker = ET.SubElement(doc, tag("Placemark"))
        ET.SubElement(marker, tag("name")).text = name
        ET.SubElement(marker, tag("description")).text = (
            f"UTC: {p.get('datetime_utc', 'unknown')}\n"
            f"Phase: {p.get('phase', 'unknown')}\n"
            f"Latitude: {p['latitude']:.7f}\n"
            f"Longitude: {p['longitude']:.7f}\n"
            f"Altitude: {p['altitude_m']:.2f} m\n"
            f"Mission elapsed: {p.get('time_s', 0.0) / 3600:.3f} hours"
        )
        point = ET.SubElement(marker, tag("Point"))
        ET.SubElement(point, tag("altitudeMode")).text = "absolute"
        ET.SubElement(point, tag("coordinates")).text = (
            f"{p['longitude']:.7f},{p['latitude']:.7f},{p['altitude_m']:.2f}"
        )

    tree = ET.ElementTree(root)
    try:
        ET.indent(tree, space="  ")
    except AttributeError:
        pass
    tree.write(filename, encoding="utf-8", xml_declaration=True)
    print(f"\nKML exported: {filename.resolve()}")
    print(f"Trajectory points: {len(trajectory)}")
    return str(filename)


def simulate_mission(
    launch_latitude,
    launch_longitude,
    launch_altitude_m,
    launch_datetime,
    hold_duration_hours,
    payload_mass_kg,
    parachute_diameter_m,
    parachute_cd=1.5,
    target_altitude_m=DEFAULT_TARGET_ALTITUDE_M,
    ascent_rate_mps=DEFAULT_ASCENT_RATE_MPS,
    ascent_hold_step_s=DEFAULT_ASCENT_HOLD_STEP_S,
    descent_output_step_s=DEFAULT_DESCENT_OUTPUT_STEP_S,
    ground_altitude_m=DEFAULT_GROUND_ALTITUDE_M,
):
    """Run ascent -> hold for requested duration -> physics-based descent."""
    launch_datetime = as_utc(launch_datetime)
    values = {
        "hold_duration_hours": hold_duration_hours,
        "payload_mass_kg": payload_mass_kg,
        "parachute_diameter_m": parachute_diameter_m,
        "parachute_cd": parachute_cd,
        "ascent_rate_mps": ascent_rate_mps,
        "ascent_hold_step_s": ascent_hold_step_s,
        "descent_output_step_s": descent_output_step_s,
    }
    for name, value in values.items():
        if value <= 0:
            raise ValueError(f"{name} must be greater than zero.")
    if target_altitude_m <= launch_altitude_m:
        raise ValueError("Target altitude must be above launch altitude.")
    if ground_altitude_m >= target_altitude_m:
        raise ValueError("Ground altitude must be below target altitude.")
    if not -90 <= launch_latitude <= 90:
        raise ValueError("Launch latitude must be between -90 and 90 degrees.")
    if not -180 <= launch_longitude <= 180:
        raise ValueError("Launch longitude must be between -180 and 180 degrees.")

    # Reuse the actual ascent model's simulate_ascent() implementation.
    # That model's duration argument is the total time from launch to end
    # of its ascent/hold run. Add ascent time so the requested hold duration
    # begins only after the balloon reaches target altitude.
    ascent_duration_hours = (target_altitude_m - launch_altitude_m) / ascent_rate_mps / 3600.0
    ascent_plus_hold_hours = ascent_duration_hours + hold_duration_hours

    print("\n" + "=" * 72)
    print("COMBINED BALLOON MISSION: EXISTING ASCENT MODEL -> HOLD -> DESCENT")
    print("=" * 72)
    print(f"Launch: {launch_latitude:.6f}, {launch_longitude:.6f} | {launch_datetime.isoformat()}")
    print(f"Target altitude: {target_altitude_m / 1000:.2f} km")
    print(f"Estimated ascent time: {ascent_duration_hours:.3f} h")
    print(f"Requested altitude hold: {hold_duration_hours:.3f} h")
    print(f"Ascent model run duration: {ascent_plus_hold_hours:.3f} h")
    print(f"Payload: {payload_mass_kg:.3f} kg | Chute diameter: {parachute_diameter_m:.3f} m | Cd: {parachute_cd:.3f}")

    # IMPORTANT: this is the simulate_ascent() imported from the supplied
    # ascent_model_time_dependent.py file, not a re-created ascent loop.
    ascent_trajectory = simulate_ascent(
        launch_latitude=launch_latitude,
        launch_longitude=launch_longitude,
        launch_altitude=launch_altitude_m,
        balloon=None,
        launch_datetime=launch_datetime,
        maximum_altitude=target_altitude_m,
        time_step=ascent_hold_step_s,
        ascent_rate=ascent_rate_mps,
        hold_duration_hours=ascent_plus_hold_hours,
    )

    if not ascent_trajectory:
        raise RuntimeError("The ascent model returned an empty trajectory.")

    # The final ascent-model point is the hold-end state. Keep its original
    # timestamps and elapsed times, then hand that exact state to descent.
    trajectory = [dict(point) for point in ascent_trajectory]
    hold_end = trajectory[-1]
    lat = float(hold_end["latitude"])
    lon = float(hold_end["longitude"])
    hold_end_altitude = float(hold_end["altitude_m"])
    descent_start_elapsed = float(hold_end["time_s"])
    descent_start_datetime = as_utc(hold_end["datetime_utc"])

    if abs(hold_end_altitude - target_altitude_m) > 1.0:
        raise RuntimeError(
            f"Ascent model ended at {hold_end_altitude:.1f} m, not target "
            f"altitude {target_altitude_m:.1f} m. Descent was not started."
        )

    print(f"Ascent/hold model finished at mission time {descent_start_elapsed / 3600:.3f} h.")
    print("Requested hold interval is complete. Starting parachute descent...")

    descent_trajectory = simulate_descent(
        burst_latitude=lat,
        burst_longitude=lon,
        burst_altitude=hold_end_altitude,
        ground_altitude=ground_altitude_m,
        payload_mass=payload_mass_kg,
        parachute_diameter=parachute_diameter_m,
        parachute_cd=parachute_cd,
        dt=descent_output_step_s,
        burst_datetime=descent_start_datetime,
        descent_rate=None,
    )

    # Descent time is relative to the start of descent. Offset it to mission
    # elapsed time; skip the first point because it duplicates the hold-end.
    for point in descent_trajectory[1:]:
        p = dict(point)
        p["time_s"] = descent_start_elapsed + float(point.get("time_s", 0.0))
        p["phase"] = "landing" if point.get("phase") == "landing" else "descent"
        trajectory.append(p)

    print("\n" + "=" * 72)
    print("FULL MISSION COMPLETE")
    print("=" * 72)
    print(f"Total elapsed: {trajectory[-1]['time_s'] / 3600:.3f} h")
    print(f"Landing coordinates: {trajectory[-1]['latitude']:.6f}, {trajectory[-1]['longitude']:.6f}")
    print(f"Landing altitude: {trajectory[-1]['altitude_m']:.2f} m")
    return trajectory


def prompt_float(label, default):
    raw = input(f"{label} [{default}]: ").strip()
    return float(raw) if raw else float(default)


def main():
    print("\nEnter launch and mission inputs. Launch datetime must be UTC.")
    launch_latitude = prompt_float("Launch latitude (degrees)", 13.0827)
    launch_longitude = prompt_float("Launch longitude (degrees)", 80.2707)
    launch_altitude_m = prompt_float("Launch altitude ASL (m)", 0.0)
    launch_text = input("Launch datetime UTC (YYYY-MM-DD HH:MM, e.g. 2026-10-20 00:00) [2026-10-20 00:00]: ").strip()
    if not launch_text:
        launch_text = "2026-10-20 00:00"
    if len(launch_text) == 16:
        launch_text += ":00"
    launch_datetime = as_utc(launch_text)

    target_altitude_m = prompt_float("Target/hold altitude (m)", DEFAULT_TARGET_ALTITUDE_M)
    ascent_rate_mps = prompt_float("Ascent rate (m/s)", DEFAULT_ASCENT_RATE_MPS)
    hold_duration_hours = prompt_float("Hold duration AFTER reaching target altitude (hours)", 120.0)
    payload_mass_kg = prompt_float("Payload mass for parachute model (kg)", 2.0)
    parachute_diameter_m = prompt_float("Parachute diameter (m)", 2.0)
    parachute_cd = prompt_float("Parachute drag coefficient Cd", 1.5)
    ground_altitude_m = prompt_float("Landing/ground altitude ASL (m)", 0.0)
    ascent_hold_step_s = prompt_float("Ascent/hold time step (seconds)", DEFAULT_ASCENT_HOLD_STEP_S)
    descent_output_step_s = prompt_float("Descent trajectory output interval (seconds)", DEFAULT_DESCENT_OUTPUT_STEP_S)
    kml_path_text = input(f"KML output path [{DEFAULT_KML}]: ").strip()
    kml_path = Path(kml_path_text) if kml_path_text else DEFAULT_KML

    trajectory = simulate_mission(
        launch_latitude=launch_latitude,
        launch_longitude=launch_longitude,
        launch_altitude_m=launch_altitude_m,
        launch_datetime=launch_datetime,
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
    export_trajectory_kml(trajectory, kml_path)
    print("Open the KML in Google Earth Pro to inspect the complete mission.")


if __name__ == "__main__":
    main()
