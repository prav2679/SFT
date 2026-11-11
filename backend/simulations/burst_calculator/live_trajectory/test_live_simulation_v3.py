import sys
import csv
import json
import math
from pathlib import Path
from datetime import datetime

import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "codes"))

from codes.flight_model_paramaterized import run_flight
from codes.wind_model_time_dependent import close_wind_dataset
from live_trajectory_manager import LiveTrajectoryManager


# ============================================================
# 1. CONFIGURATION
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

INTERVAL_S = 600

OUTPUT_DIR = ROOT / "live_trajectory" / "v3_validation"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================
# 2. DISTANCE CALCULATION
# ============================================================

def haversine_distance(lat1, lon1, lat2, lon2):
    """Calculate horizontal distance between two GPS coordinates."""

    earth_radius = 6371000.0

    lat1 = math.radians(float(lat1))
    lon1 = math.radians(float(lon1))
    lat2 = math.radians(float(lat2))
    lon2 = math.radians(float(lon2))

    dlat = lat2 - lat1
    dlon = lon2 - lon1

    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2)
        * math.sin(dlon / 2) ** 2
    )

    return 2 * earth_radius * math.asin(math.sqrt(a))


def safe_float(value):
    if value is None:
        return None
    return float(value)


# ============================================================
# 3. RUN BASELINE FLIGHT
# ============================================================

print("\n" + "=" * 70)
print("V3 - SEQUENTIAL TELEMETRY VALIDATION")
print("=" * 70)

print("\nRunning baseline flight simulation...")

baseline = run_flight(parameters)

if not baseline.get("success"):
    raise RuntimeError("Baseline flight simulation failed.")

baseline_landing = baseline["landing"]

baseline_lat = float(baseline_landing["latitude"])
baseline_lon = float(baseline_landing["longitude"])

baseline_landing_datetime = baseline_landing.get("datetime_utc")

print("\nBaseline landing:")
print("Latitude:", baseline_lat)
print("Longitude:", baseline_lon)
print("Datetime:", baseline_landing_datetime)


# ============================================================
# 4. INITIALIZE LIVE TRAJECTORY MANAGER
# ============================================================

manager = LiveTrajectoryManager(
    parameters=parameters,
    baseline_result=baseline
)


# ============================================================
# 5. GENERATE SYNTHETIC TELEMETRY
# ============================================================

print("\nGenerating synthetic telemetry...")

ascent = baseline["ascent_trajectory"]

telemetry_points = []

for point in ascent:

    elapsed = float(point["time_s"])

    if elapsed < INTERVAL_S:
        continue

    if elapsed % INTERVAL_S < parameters["ascent_time_step"]:

        telemetry = {
            "datetime_utc": point["datetime_utc"],
            "latitude": float(point["latitude"]) + 0.001,
            "longitude": float(point["longitude"]) - 0.001,
            "altitude_m": float(point["altitude_m"]) + 75,
            "phase": "ascent",
        }

        telemetry_points.append(telemetry)


if not telemetry_points:
    raise RuntimeError("No telemetry points generated.")

print("Telemetry points:", len(telemetry_points))


# ============================================================
# 6. PROCESS TELEMETRY SEQUENTIALLY
# ============================================================

print("\nProcessing sequential telemetry updates...")

records = []

previous_landing = None

for index, telemetry in enumerate(telemetry_points, start=1):

    print("\n" + "-" * 60)
    print(f"TELEMETRY UPDATE {index}/{len(telemetry_points)}")
    print("-" * 60)

    update = manager.update(telemetry)

    if not update.get("success"):
        print("Update failed.")
        continue

    elapsed_s = float(update["elapsed_s"])

    burst = update.get("revised_burst")
    landing = update.get("revised_landing")

    if burst is None or landing is None:
        print("No complete burst-to-landing prediction yet.")
        continue

    burst_time_s = float(burst["time_s"])
    burst_remaining_s = burst_time_s - elapsed_s

    landing_lat = float(landing["latitude"])
    landing_lon = float(landing["longitude"])

    landing_datetime = landing.get("datetime_utc")

    burst_lat = float(burst["latitude"])
    burst_lon = float(burst["longitude"])
    burst_altitude = float(burst["altitude_m"])

    # Distance between the previous and current landing predictions.
    if previous_landing is None:
        landing_change_m = 0.0
    else:
        landing_change_m = haversine_distance(
            previous_landing["latitude"],
            previous_landing["longitude"],
            landing_lat,
            landing_lon
        )

    # Distance between current landing prediction and baseline landing.
    baseline_error_m = haversine_distance(
        baseline_lat,
        baseline_lon,
        landing_lat,
        landing_lon
    )

    # Telemetry deviation from baseline trajectory.
    telemetry_deviation_m = update.get(
        "deviation_from_original_m"
    )

    altitude_error_m = update.get(
        "altitude_error_from_original_m"
    )

    record = {
        "update_number": index,

        "telemetry_datetime_utc": telemetry["datetime_utc"],
        "telemetry_elapsed_s": elapsed_s,
        "telemetry_latitude": telemetry["latitude"],
        "telemetry_longitude": telemetry["longitude"],
        "telemetry_altitude_m": telemetry["altitude_m"],

        "telemetry_horizontal_deviation_m": telemetry_deviation_m,
        "telemetry_altitude_error_m": altitude_error_m,

        "predicted_burst_datetime_utc": burst.get("datetime_utc"),
        "predicted_burst_time_s": burst_time_s,
        "predicted_burst_remaining_s": burst_remaining_s,
        "predicted_burst_latitude": burst_lat,
        "predicted_burst_longitude": burst_lon,
        "predicted_burst_altitude_m": burst_altitude,

        "predicted_landing_datetime_utc": landing_datetime,
        "predicted_landing_latitude": landing_lat,
        "predicted_landing_longitude": landing_lon,

        "landing_change_from_previous_m": landing_change_m,
        "landing_error_vs_baseline_m": baseline_error_m,

        "forecast_status": update.get("forecast_status"),
    }

    records.append(record)

    previous_landing = {
        "latitude": landing_lat,
        "longitude": landing_lon,
    }

    print("Telemetry elapsed:", round(elapsed_s, 2), "seconds")
    print("Telemetry altitude:", round(telemetry["altitude_m"], 2), "m")

    print("\nPredicted burst:")
    print("  Time:", burst.get("datetime_utc"))
    print("  Altitude:", round(burst_altitude, 2), "m")
    print("  Remaining time:", round(burst_remaining_s, 2), "s")

    print("\nPredicted landing:")
    print("  Latitude:", landing_lat)
    print("  Longitude:", landing_lon)
    print("  Datetime:", landing_datetime)

    print("\nLanding prediction change:", round(landing_change_m, 2), "m")
    print("Landing difference from baseline:", round(baseline_error_m, 2), "m")


if not records:
    raise RuntimeError("No complete predictions were generated.")


# ============================================================
# 7. SAVE SEQUENTIAL TELEMETRY CSV
# ============================================================

csv_path = OUTPUT_DIR / "sequential_telemetry_results.csv"

with open(csv_path, "w", newline="") as csvfile:

    writer = csv.DictWriter(
        csvfile,
        fieldnames=list(records[0].keys())
    )

    writer.writeheader()
    writer.writerows(records)

print("\nCSV saved:", csv_path)


# ============================================================
# 8. GENERATE VALIDATION SUMMARY
# ============================================================

landing_errors = [
    row["landing_error_vs_baseline_m"]
    for row in records
]

landing_changes = [
    row["landing_change_from_previous_m"]
    for row in records
]

summary = {
    "validation_type": "sequential_synthetic_telemetry",
    "telemetry_interval_s": INTERVAL_S,
    "total_telemetry_updates": len(telemetry_points),
    "successful_predictions": len(records),

    "baseline_landing": {
        "latitude": baseline_lat,
        "longitude": baseline_lon,
        "datetime_utc": baseline_landing_datetime,
    },

    "first_update_landing_error_m": landing_errors[0],
    "final_update_landing_error_m": landing_errors[-1],

    "maximum_landing_error_m": max(landing_errors),
    "minimum_landing_error_m": min(landing_errors),

    "final_landing_prediction_change_m": landing_changes[-1],

    "final_prediction": records[-1],
}

summary_path = OUTPUT_DIR / "validation_summary.json"

with open(summary_path, "w") as jsonfile:
    json.dump(summary, jsonfile, indent=4)

print("Summary saved:", summary_path)


# ============================================================
# 9. PLOT 1 - LANDING PREDICTION CONVERGENCE
# ============================================================

x_minutes = [
    row["telemetry_elapsed_s"] / 60
    for row in records
]

landing_error = [
    row["landing_error_vs_baseline_m"]
    for row in records
]

plt.figure(figsize=(10, 5))

plt.plot(
    x_minutes,
    landing_error,
    marker="o"
)

plt.xlabel("Telemetry Time Since Launch (minutes)")
plt.ylabel("Landing Difference from Baseline (m)")
plt.title("Landing Prediction Error vs Telemetry Time")
plt.grid(True)

plt.tight_layout()

plt.savefig(
    OUTPUT_DIR / "landing_error.png",
    dpi=200
)

plt.close()


# ============================================================
# 10. PLOT 2 - LANDING PREDICTION CHANGE
# ============================================================

landing_change = [
    row["landing_change_from_previous_m"]
    for row in records
]

plt.figure(figsize=(10, 5))

plt.plot(
    x_minutes,
    landing_change,
    marker="o"
)

plt.xlabel("Telemetry Time Since Launch (minutes)")
plt.ylabel("Landing Prediction Change (m)")
plt.title("Landing Prediction Change Between Updates")
plt.grid(True)

plt.tight_layout()

plt.savefig(
    OUTPUT_DIR / "landing_convergence.png",
    dpi=200
)

plt.close()


# ============================================================
# 11. PLOT 3 - PREDICTED BURST LOCATION
# ============================================================

burst_latitudes = [
    row["predicted_burst_latitude"]
    for row in records
]

burst_longitudes = [
    row["predicted_burst_longitude"]
    for row in records
]

plt.figure(figsize=(8, 7))

plt.plot(
    burst_longitudes,
    burst_latitudes,
    marker="o"
)

for i, row in enumerate(records):
    plt.annotate(
        str(row["update_number"]),
        (burst_longitudes[i], burst_latitudes[i])
    )

plt.xlabel("Longitude")
plt.ylabel("Latitude")
plt.title("Predicted Burst Location Across Telemetry Updates")
plt.grid(True)

plt.tight_layout()

plt.savefig(
    OUTPUT_DIR / "burst_prediction.png",
    dpi=200
)

plt.close()


# ============================================================
# 12. PLOT 4 - PREDICTED BURST TIME
# ============================================================

burst_remaining_minutes = [
    row["predicted_burst_remaining_s"] / 60
    for row in records
]

plt.figure(figsize=(10, 5))

plt.plot(
    x_minutes,
    burst_remaining_minutes,
    marker="o"
)

plt.xlabel("Telemetry Time Since Launch (minutes)")
plt.ylabel("Predicted Remaining Time to Burst (minutes)")
plt.title("Predicted Burst Time Across Telemetry Updates")
plt.grid(True)

plt.tight_layout()

plt.savefig(
    OUTPUT_DIR / "burst_time_prediction.png",
    dpi=200
)

plt.close()


# ============================================================
# 13. FINAL RESULTS
# ============================================================

print("\n" + "=" * 70)
print("V3 VALIDATION COMPLETED")
print("=" * 70)

print("Telemetry updates:", len(telemetry_points))
print("Successful predictions:", len(records))

print("\nFirst landing error:", round(landing_errors[0], 2), "m")
print("Final landing error:", round(landing_errors[-1], 2), "m")

print(
    "\nFinal predicted landing:",
    records[-1]["predicted_landing_latitude"],
    records[-1]["predicted_landing_longitude"]
)

print("\nOutput directory:")
print(OUTPUT_DIR)

print("\nGenerated files:")
for path in sorted(OUTPUT_DIR.iterdir()):
    print(" -", path.name)


# ============================================================
# 14. CLOSE WIND DATASET
# ============================================================

close_wind_dataset()

print("\nWind dataset closed.")
print("V3 test finished.")
