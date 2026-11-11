from pathlib import Path
import sys
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

# ---------------------------------------------------------------------
# CONFIGURATION — change these paths if needed
# ---------------------------------------------------------------------
SONDEHUB_CSV = Path(
    r"results\sondehub.csv"
)
MODEL_CSV = Path(r"results\cusf_trajectory.csv")

OUTPUT_DIR = Path("trajectory_comparison_output")

# Set True if SondeHub altitude is in kilometres rather than metres.
SONDEHUB_ALTITUDE_IS_KM = False

EARTH_RADIUS_KM = 6371.0088


def find_column(df, candidates, description):
    """Find a column case-insensitively from a list of candidate names."""
    lookup = {str(c).strip().lower(): c for c in df.columns}
    for candidate in candidates:
        if candidate.lower() in lookup:
            return lookup[candidate.lower()]
    raise KeyError(
        f"Could not find {description} column. Tried {candidates}.\n"
        f"Available columns: {list(df.columns)}"
    )


def load_trajectory(path, kind):
    """Load and normalize trajectory columns."""
    if not path.exists():
        raise FileNotFoundError(
            f"Cannot find {path.resolve()}\n"
            "Place the CSV beside this script or update its path at the top."
        )

    df = pd.read_csv(path)
    if df.empty:
        raise ValueError(f"{path} is empty.")

    if kind == "sondehub":
        time_candidates = ["datetime", "timestamp", "time", "datetime_utc"]
        altitude_candidates = [
            "altitude", "altitude_m", "altitude(m)", "altitude_meters",
            "gps_altitude", "alt"
        ]
    else:
        time_candidates = ["datetime_utc", "datetime", "timestamp", "time"]
        altitude_candidates = [
            "altitude_m", "altitude", "altitude(m)", "altitude_meters", "alt"
        ]

    time_col = find_column(df, time_candidates, "timestamp")
    lat_col = find_column(df, ["latitude", "lat"], "latitude")
    lon_col = find_column(df, ["longitude", "lon", "lng"], "longitude")
    alt_col = find_column(df, altitude_candidates, "altitude")

    out = pd.DataFrame({
        "time_utc": pd.to_datetime(df[time_col], utc=True, errors="coerce", format="mixed"),
        "latitude": pd.to_numeric(df[lat_col], errors="coerce"),
        "longitude": pd.to_numeric(df[lon_col], errors="coerce"),
        "altitude_m": pd.to_numeric(df[alt_col], errors="coerce"),
    })

    if kind == "sondehub" and SONDEHUB_ALTITUDE_IS_KM:
        out["altitude_m"] *= 1000.0

    before = len(out)
    out = out.dropna(subset=["time_utc", "latitude", "longitude", "altitude_m"])
    dropped = before - len(out)
    if out.empty:
        raise ValueError(f"No valid rows remain after parsing {path}.")

    # Average duplicate timestamps so np.interp receives a strictly increasing
    # time coordinate and no duplicate x-values.
    out = (
        out.groupby("time_utc", as_index=False)
        .agg({
            "latitude": "mean",
            "longitude": "mean",
            "altitude_m": "mean",
        })
        .sort_values("time_utc")
        .reset_index(drop=True)
    )

    print(f"{kind.title()} rows loaded: {len(out)} (dropped invalid rows: {dropped})")
    print(f"{kind.title()} time span: {out['time_utc'].min()} to {out['time_utc'].max()}")
    return out


def haversine_km(lat1_deg, lon1_deg, lat2_deg, lon2_deg):
    """Great-circle distance in kilometres; inputs are arrays in degrees."""
    lat1 = np.radians(np.asarray(lat1_deg, dtype=float))
    lon1 = np.radians(np.asarray(lon1_deg, dtype=float))
    lat2 = np.radians(np.asarray(lat2_deg, dtype=float))
    lon2 = np.radians(np.asarray(lon2_deg, dtype=float))

    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = (
        np.sin(dlat / 2.0) ** 2
        + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2.0) ** 2
    )
    a = np.clip(a, 0.0, 1.0)
    return 2.0 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(a))


def interpolate_model_to_times(model, target_times):
    """Linearly interpolate model fields at target UTC timestamps."""
    model_seconds = model["time_utc"].astype("int64").to_numpy() / 1e9
    target_seconds = pd.Series(target_times).astype("int64").to_numpy() / 1e9

    result = {}
    for col in ["latitude", "longitude", "altitude_m"]:
        result[col] = np.interp(
            target_seconds,
            model_seconds,
            model[col].to_numpy(dtype=float)
        )
    return result


def make_plot(times, y, title, ylabel, output_path):
    plt.figure(figsize=(11, 5.5))
    plt.plot(times, y, linewidth=1.8)
    plt.xlabel("Time (UTC)")
    plt.ylabel(ylabel)
    plt.title(title)
    plt.grid(True, alpha=0.3)
    plt.xticks(rotation=30, ha="right")
    plt.tight_layout()
    plt.savefig(output_path, dpi=160)
    plt.close()


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    sondehub = load_trajectory(SONDEHUB_CSV, "sondehub")
    model = load_trajectory(MODEL_CSV, "model")

    # Restrict comparison to the shared time window.
    overlap_start = max(sondehub["time_utc"].min(), model["time_utc"].min())
    overlap_end = min(sondehub["time_utc"].max(), model["time_utc"].max())

    if overlap_start >= overlap_end:
        raise ValueError(
            "The two CSV files have no overlapping time interval.\n"
            f"SondeHub: {sondehub['time_utc'].min()} to {sondehub['time_utc'].max()}\n"
            f"Model:    {model['time_utc'].min()} to {model['time_utc'].max()}\n"
            "Check that both timestamps are in UTC and refer to the same flight."
        )

    reference = sondehub[
        sondehub["time_utc"].between(overlap_start, overlap_end)
    ].copy().reset_index(drop=True)

    model_values = interpolate_model_to_times(model, reference["time_utc"])

    result = pd.DataFrame({
        "datetime_utc": reference["time_utc"].dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        "elapsed_minutes": (
            reference["time_utc"] - overlap_start
        ).dt.total_seconds() / 60.0,
        "sondehub_latitude": reference["latitude"],
        "sondehub_longitude": reference["longitude"],
        "sondehub_altitude_m": reference["altitude_m"],
        "model_latitude_interpolated": model_values["latitude"],
        "model_longitude_interpolated": model_values["longitude"],
        "model_altitude_m_interpolated": model_values["altitude_m"],
    })

    result["latitude_error_deg_model_minus_sondehub"] = (
        result["model_latitude_interpolated"] - result["sondehub_latitude"]
    )
    result["longitude_error_deg_model_minus_sondehub"] = (
        result["model_longitude_interpolated"] - result["sondehub_longitude"]
    )
    result["horizontal_error_km"] = haversine_km(
        result["sondehub_latitude"],
        result["sondehub_longitude"],
        result["model_latitude_interpolated"],
        result["model_longitude_interpolated"],
    )
    result["altitude_error_m_model_minus_sondehub"] = (
        result["model_altitude_m_interpolated"] - result["sondehub_altitude_m"]
    )
    result["absolute_altitude_error_m"] = (
        result["altitude_error_m_model_minus_sondehub"].abs()
    )

    # Approximate phase labels based on SondeHub altitude trend. These are
    # diagnostic labels only; adjust thresholds/phase boundaries if needed.
    altitude = result["sondehub_altitude_m"].to_numpy()
    if len(altitude) >= 3:
        peak_idx = int(np.argmax(altitude))
        result["phase_approx"] = np.where(
            np.arange(len(result)) < peak_idx, "ascent",
            np.where(np.arange(len(result)) == peak_idx, "near_peak", "post_peak")
        )
    else:
        result["phase_approx"] = "unknown"

    csv_out = OUTPUT_DIR / "sondehub_model_displacement_error.csv"
    result.to_csv(csv_out, index=False)

    times = pd.to_datetime(result["datetime_utc"], utc=True, format="mixed")
    make_plot(
        times,
        result["horizontal_error_km"],
        "SondeHub vs Model: Horizontal Position Error",
        "Horizontal separation (km)",
        OUTPUT_DIR / "horizontal_displacement_error.png",
    )

    plt.figure(figsize=(11, 5.5))
    plt.plot(times, result["sondehub_altitude_m"] / 1000.0, label="SondeHub")
    plt.plot(
        times,
        result["model_altitude_m_interpolated"] / 1000.0,
        label="Model (interpolated)",
    )
    plt.xlabel("Time (UTC)")
    plt.ylabel("Altitude (km)")
    plt.title("SondeHub vs Model: Altitude Comparison")
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.xticks(rotation=30, ha="right")
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / "altitude_comparison.png", dpi=160)
    plt.close()

    make_plot(
        times,
        result["altitude_error_m_model_minus_sondehub"],
        "SondeHub vs Model: Signed Altitude Error",
        "Model altitude − SondeHub altitude (m)",
        OUTPUT_DIR / "altitude_error.png",
    )

    e = result["horizontal_error_km"].to_numpy()
    ae = result["altitude_error_m_model_minus_sondehub"].to_numpy()
    summary = {
        "matched_rows": len(result),
        "overlap_start_utc": str(overlap_start),
        "overlap_end_utc": str(overlap_end),
        "mean_horizontal_error_km": float(np.mean(e)),
        "median_horizontal_error_km": float(np.median(e)),
        "horizontal_error_rmse_km": float(np.sqrt(np.mean(e ** 2))),
        "maximum_horizontal_error_km": float(np.max(e)),
        "final_horizontal_error_km": float(e[-1]),
        "mean_absolute_altitude_error_m": float(np.mean(np.abs(ae))),
        "altitude_error_rmse_m": float(np.sqrt(np.mean(ae ** 2))),
        "maximum_absolute_altitude_error_m": float(np.max(np.abs(ae))),
        "final_signed_altitude_error_m": float(ae[-1]),
    }

    summary_path = OUTPUT_DIR / "summary.txt"
    with summary_path.open("w", encoding="utf-8") as f:
        f.write("SONDEHUB VS MODEL TRAJECTORY COMPARISON\n")
        f.write("=" * 45 + "\n")
        for key, value in summary.items():
            f.write(f"{key}: {value}\n")

    print("\n" + "=" * 65)
    print("COMPARISON SUMMARY")
    print("=" * 65)
    for key, value in summary.items():
        print(f"{key}: {value}")

    print("\nOutput files created in:")
    print(OUTPUT_DIR.resolve())
    print(f"  - {csv_out.name}")
    print("  - horizontal_displacement_error.png")
    print("  - altitude_comparison.png")
    print("  - altitude_error.png")
    print(f"  - {summary_path.name}")
    print(
        "\nNote: model values are linearly interpolated in time to the "
        "SondeHub timestamps. This aligns times but does not make the "
        "model forecast more accurate."
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"\nERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)
