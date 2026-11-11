import csv
import math
import matplotlib.pyplot as plt
from pathlib import Path


# ============================================================
# FILE
# ============================================================

CSV_FILE = "complete_flight_trajectory.csv"


# ============================================================
# READ TRAJECTORY
# ============================================================

def read_trajectory(filename):

    path = Path(filename)

    if not path.exists():
        raise FileNotFoundError(
            f"Could not find '{filename}'. "
            f"Make sure it is in the same folder as plot_model.py."
        )

    with path.open("r", newline="", encoding="utf-8") as file:

        return list(csv.DictReader(file))


# ============================================================
# GET FLOAT VALUE
# ============================================================

def get_float(row, *names):

    for name in names:

        if name in row and row[name] not in ("", None):

            return float(row[name])

    raise KeyError(
        f"None of these columns were found: {names}"
    )


# ============================================================
# EXTRACT DATA
# ============================================================

def extract_data(rows):

    time_s = []
    latitude = []
    longitude = []
    altitude = []
    phase = []

    for row in rows:

        time_s.append(
            get_float(row, "flight_time_s", "time_s")
        )

        latitude.append(
            get_float(row, "latitude")
        )

        longitude.append(
            get_float(row, "longitude")
        )

        altitude.append(
            get_float(row, "altitude_m")
        )

        phase.append(
            row.get("phase", "").lower()
        )

    return (
        time_s,
        latitude,
        longitude,
        altitude,
        phase
    )


# ============================================================
# FIND BURST
# ============================================================

def find_burst_index(phase, altitude):

    # First look for explicit burst phase

    for i, p in enumerate(phase):

        if p == "burst":

            return i

    # Otherwise find ascent -> descent transition

    for i in range(1, len(phase)):

        if phase[i - 1] == "ascent" and phase[i] == "descent":

            return i

    # Final fallback: maximum altitude

    return max(
        range(len(altitude)),
        key=lambda i: altitude[i]
    )


# ============================================================
# FIND LANDING
# ============================================================

def find_landing_index(altitude):

    return min(
        range(len(altitude)),
        key=lambda i: abs(altitude[i])
    )


# ============================================================
# PLOT 1
# ALTITUDE VS TIME
# ============================================================

def plot_altitude(
    time_s,
    altitude,
    burst_i,
    landing_i
):

    plt.figure(figsize=(10, 6))

    time_min = [
        t / 60.0
        for t in time_s
    ]

    altitude_km = [
        a / 1000.0
        for a in altitude
    ]

    plt.plot(
        time_min,
        altitude_km,
        linewidth=2,
        label="Flight path"
    )

    # Burst

    plt.scatter(
        time_min[burst_i],
        altitude_km[burst_i],
        s=80,
        marker="^",
        label="Burst"
    )

    # Landing

    plt.scatter(
        time_min[landing_i],
        altitude_km[landing_i],
        s=80,
        marker="x",
        label="Landing"
    )

    plt.xlabel("Flight time (minutes)")
    plt.ylabel("Altitude (km)")

    plt.title(
        "Balloon Altitude vs Flight Time"
    )

    plt.grid(True, alpha=0.3)

    plt.legend()

    plt.tight_layout()

    plt.savefig(
        "altitude_vs_time.png",
        dpi=300
    )

    plt.show()


# ============================================================
# PLOT 2
# GROUND TRAJECTORY
# ============================================================

def plot_ground_trajectory(
    latitude,
    longitude,
    burst_i,
    landing_i
):

    plt.figure(figsize=(9, 7))

    # Flight path

    plt.plot(
        longitude,
        latitude,
        linewidth=2,
        label="Flight path"
    )

    # Launch

    plt.scatter(
        longitude[0],
        latitude[0],
        s=90,
        marker="o",
        label="Launch"
    )

    # Burst

    plt.scatter(
        longitude[burst_i],
        latitude[burst_i],
        s=100,
        marker="^",
        label="Burst"
    )

    # Landing

    plt.scatter(
        longitude[landing_i],
        latitude[landing_i],
        s=100,
        marker="x",
        label="Landing"
    )

    plt.xlabel("Longitude (°)")
    plt.ylabel("Latitude (°)")

    plt.title(
        "Balloon Ground Trajectory"
    )

    plt.grid(True, alpha=0.3)

    plt.legend()

    plt.tight_layout()

    plt.savefig(
        "ground_trajectory.png",
        dpi=300
    )

    plt.show()


# ============================================================
# PLOT 3
# 3D FLIGHT TRAJECTORY
# ============================================================

def plot_3d_trajectory(
    latitude,
    longitude,
    altitude,
    burst_i,
    landing_i
):

    # Create 3D figure

    fig = plt.figure(
        figsize=(11, 8)
    )

    ax = fig.add_subplot(
        111,
        projection="3d"
    )

    # Convert altitude to km

    altitude_km = [
        a / 1000.0
        for a in altitude
    ]

    # --------------------------------------------------------
    # COMPLETE FLIGHT PATH
    # --------------------------------------------------------

    ax.plot(
        longitude,
        latitude,
        altitude_km,
        linewidth=2,
        label="Flight path"
    )

    # --------------------------------------------------------
    # LAUNCH
    # --------------------------------------------------------

    ax.scatter(
        longitude[0],
        latitude[0],
        altitude_km[0],
        s=100,
        marker="o",
        label="Launch"
    )

    # --------------------------------------------------------
    # BURST
    # --------------------------------------------------------

    ax.scatter(
        longitude[burst_i],
        latitude[burst_i],
        altitude_km[burst_i],
        s=120,
        marker="^",
        label="Burst"
    )

    # --------------------------------------------------------
    # LANDING
    # --------------------------------------------------------

    ax.scatter(
        longitude[landing_i],
        latitude[landing_i],
        altitude_km[landing_i],
        s=120,
        marker="x",
        label="Landing"
    )

    # --------------------------------------------------------
    # VERTICAL LINE FROM BURST TO GROUND
    # --------------------------------------------------------

    ax.plot(
        [
            longitude[burst_i],
            longitude[burst_i]
        ],
        [
            latitude[burst_i],
            latitude[burst_i]
        ],
        [
            0,
            altitude_km[burst_i]
        ],
        linestyle="--",
        linewidth=1
    )

    # --------------------------------------------------------
    # VERTICAL LINE FROM LAUNCH TO GROUND
    # --------------------------------------------------------

    ax.plot(
        [
            longitude[0],
            longitude[0]
        ],
        [
            latitude[0],
            latitude[0]
        ],
        [
            0,
            altitude_km[0]
        ],
        linestyle="--",
        linewidth=1
    )

    # --------------------------------------------------------
    # AXIS LABELS
    # --------------------------------------------------------

    ax.set_xlabel(
        "Longitude (°)"
    )

    ax.set_ylabel(
        "Latitude (°)"
    )

    ax.set_zlabel(
        "Altitude (km)"
    )

    # --------------------------------------------------------
    # TITLE
    # --------------------------------------------------------

    ax.set_title(
        "3D Balloon Flight Trajectory"
    )

    # --------------------------------------------------------
    # VIEW ANGLE
    # --------------------------------------------------------

    ax.view_init(
        elev=25,
        azim=-60
    )

    # --------------------------------------------------------
    # LEGEND
    # --------------------------------------------------------

    ax.legend()

    plt.tight_layout()

    # --------------------------------------------------------
    # SAVE
    # --------------------------------------------------------

    plt.savefig(
        "3d_flight_trajectory.png",
        dpi=300
    )

    plt.show()


# ============================================================
# MAIN
# ============================================================

def main():

    # --------------------------------------------------------
    # READ CSV
    # --------------------------------------------------------

    rows = read_trajectory(
        CSV_FILE
    )

    if not rows:

        raise ValueError(
            "The trajectory CSV contains no data."
        )

    # --------------------------------------------------------
    # EXTRACT
    # --------------------------------------------------------

    (
        time_s,
        latitude,
        longitude,
        altitude,
        phase
    ) = extract_data(rows)

    # --------------------------------------------------------
    # FIND BURST
    # --------------------------------------------------------

    burst_i = find_burst_index(
        phase,
        altitude
    )

    # --------------------------------------------------------
    # FIND LANDING
    # --------------------------------------------------------

    landing_i = find_landing_index(
        altitude
    )

    # --------------------------------------------------------
    # PRINT INFORMATION
    # --------------------------------------------------------

    print()
    print("=" * 55)
    print(" BALLOON FLIGHT TRAJECTORY")
    print("=" * 55)

    print(
        f"Trajectory points : {len(rows)}"
    )

    print(
        f"Flight duration   : "
        f"{time_s[-1] / 60.0:.2f} minutes"
    )

    print(
        f"Maximum altitude  : "
        f"{max(altitude) / 1000.0:.2f} km"
    )

    # --------------------------------------------------------
    # BURST INFORMATION
    # --------------------------------------------------------

    print()
    print("BURST")

    print(
        f"Latitude  : "
        f"{latitude[burst_i]:.6f}°"
    )

    print(
        f"Longitude : "
        f"{longitude[burst_i]:.6f}°"
    )

    print(
        f"Altitude  : "
        f"{altitude[burst_i] / 1000.0:.2f} km"
    )

    # --------------------------------------------------------
    # LANDING INFORMATION
    # --------------------------------------------------------

    print()
    print("LANDING")

    print(
        f"Latitude  : "
        f"{latitude[landing_i]:.6f}°"
    )

    print(
        f"Longitude : "
        f"{longitude[landing_i]:.6f}°"
    )

    print(
        f"Altitude  : "
        f"{altitude[landing_i]:.2f} m"
    )

    # --------------------------------------------------------
    # CREATE PLOTS
    # --------------------------------------------------------

    print()
    print("Generating plots...")

    plot_altitude(
        time_s,
        altitude,
        burst_i,
        landing_i
    )

    plot_ground_trajectory(
        latitude,
        longitude,
        burst_i,
        landing_i
    )

    plot_3d_trajectory(
        latitude,
        longitude,
        altitude,
        burst_i,
        landing_i
    )

    # --------------------------------------------------------
    # DONE
    # --------------------------------------------------------

    print()
    print("Saved:")

    print(
        "  altitude_vs_time.png"
    )

    print(
        "  ground_trajectory.png"
    )

    print(
        "  3d_flight_trajectory.png"
    )

    print()


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    main()