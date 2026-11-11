import sys
import math
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]

# Add project root and codes directory to Python import paths.
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "codes"))
from codes.flight_model_paramaterized import run_flight
from codes.wind_model_time_dependent import close_wind_dataset
from live_trajectory_manager import LiveTrajectoryManager


# ============================================================
# 1. BALLOON CONFIGURATION
# ============================================================

parameters = {
    "latitude": 13.0827,
    "longitude": 80.2707,
    "launch_altitude": 87,

    "launch_datetime": datetime(2026, 10, 31, 0, 0),

    "payload_mass": 5,
    "envelope_mass": 3,
    "helium_mass": 2,

    "initial_volume": 12.05,
    "burst_diameter": 13.02,
    "balloon_cd": 0.47,

    "parachute_diameter": 2.4,
    "parachute_cd": 1.0,

    "ascent_rate": 6.69,
    "descent_rate": 5.0,

    "ascent_time_step": 10,
    "descent_time_step": 1,

    "burst_altitude": 32000,
    "maximum_altitude": 35000,
    "ground_altitude": 87,
}


# ============================================================
# 2. RUN ORIGINAL FLIGHT SIMULATION
# ============================================================

print("\n" + "=" * 65)
print("RUNNING BASELINE BALLOON SIMULATION")
print("=" * 65)

baseline = run_flight(parameters)

if not baseline.get("success"):
    raise RuntimeError(
        f"Baseline simulation failed. Phase: {baseline.get('phase')}"
    )

print("\nBASELINE RESULTS")

print("Burst:")
print(baseline["burst"])

print("\nLanding:")
print(baseline["landing"])

print(
    "\nTotal flight time:",
    round(baseline["total_flight_time_s"] / 60, 2),
    "minutes"
)


# ============================================================
# 3. INITIALISE LIVE TRAJECTORY MANAGER
# ============================================================

print("\n" + "=" * 65)
print("INITIALISING LIVE TRAJECTORY MANAGER")
print("=" * 65)

manager = LiveTrajectoryManager(
    parameters=parameters,
    baseline_result=baseline
)

print("Live trajectory manager initialised.")


# ============================================================
# 4. GENERATE SYNTHETIC TELEMETRY
# ============================================================

print("\n" + "=" * 65)
print("GENERATING SYNTHETIC BALLOON TELEMETRY")
print("=" * 65)

ascent = baseline["ascent_trajectory"]

# Generate one telemetry point approximately every 10 minutes.
interval_s = 600

telemetry_points = []

for point in ascent:

    if point["time_s"] < interval_s:
        continue

    if point["time_s"] % interval_s < parameters["ascent_time_step"]:

        # Simulate realistic measurement deviations.
        telemetry = {
            "datetime_utc": point["datetime_utc"],

            "latitude": point["latitude"] + 0.001,

            "longitude": point["longitude"] - 0.001,

            "altitude_m": point["altitude_m"] + 75,

            "phase": "ascent",
        }

        telemetry_points.append(telemetry)


if not telemetry_points:
    raise RuntimeError("No telemetry points generated.")


print("Telemetry points generated:", len(telemetry_points))


# ============================================================
# 5. PROCESS LIVE TELEMETRY
# ============================================================

print("\n" + "=" * 65)
print("PROCESSING LIVE TELEMETRY")
print("=" * 65)

for index, telemetry in enumerate(telemetry_points, start=1):

    print(
        f"\nTelemetry {index}/{len(telemetry_points)}"
    )

    print(
        "Time:",
        telemetry["datetime_utc"]
    )

    print(
        "Measured position:",
        telemetry["latitude"],
        telemetry["longitude"]
    )

    print(
        "Measured altitude:",
        telemetry["altitude_m"]
    )

    update = manager.update(telemetry)

    print("Live update processed.")

    print("Update result:", update)


# ============================================================
# 6. DISPLAY FINAL LIVE PREDICTION
# ============================================================

print("\n" + "=" * 65)
print("FINAL LIVE TRAJECTORY RESULTS")
print("=" * 65)

# ============================================================
# SAVE LIVE TRAJECTORY RESULTS
# ============================================================

print("\n" + "=" * 65)
print("SAVING LIVE TRAJECTORY RESULTS")
print("=" * 65)

saved_files = manager.save()

print("\nFiles successfully exported:")

for name, file_path in saved_files.items():
    print(f"{name}: {file_path}")

# Display a concise summary instead of printing thousands of rows.
latest = manager.latest_update or {}

print("\nLATEST TELEMETRY SUMMARY")
print("Elapsed time:", latest.get("elapsed_s"))
print("Deviation from original (m):",
      latest.get("deviation_from_original_m"))

print("\nREVISED BURST")
print(latest.get("revised_burst"))

print("\nREVISED LANDING")
print(latest.get("revised_landing"))

print("\nTrajectory points:")
print("Original:", len(manager.original_prediction))
print("Telemetry:", len(manager.actual_telemetry))
print("Revised:", len(manager.latest_revised_prediction))


# ============================================================
# 7. CLOSE WIND DATASET
# ============================================================

close_wind_dataset()

print("\nLive trajectory test completed.")
