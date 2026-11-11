"""
download_cfsv2_time_series.py

Download CFSv2 pressure-level forecast fields from NOAA NOMADS and combine
them into one time-dependent NetCDF for the balloon GNC model.

This replaces the previous GFS/Herbie downloader. CFSv2 is accessed through
the NOMADS CFS pressure-level filter; Herbie is not used.

Configured example:
  CFS cycle initialized: 2026-10-15 00 UTC
  Valid times:           2026-10-17 00, 06, 12, 18 UTC

Output dimensions:
  time x isobaricInhPa x latitude x longitude

Output variables:
  HGT, TMP, UGRD, VGRD
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
import time

import requests
import numpy as np
import xarray as xr

try:
    import cfgrib  # noqa: F401
except ImportError as exc:
    raise SystemExit(
        "\nMissing GRIB support. Install the required packages with:\n"
        "python -m pip install -U xarray netCDF4 cfgrib eccodes requests\n"
    ) from exc


# ============================================================
# USER SETTINGS - EDIT THESE
# ============================================================

# Forecast initialization must be on/before the requested valid date.
# Here the 15 Oct 00 UTC cycle is used to forecast 17 Oct.
ISSUE_DATE = "2026-10-15"
ISSUE_CYCLE_UTC = 0                 # 0, 6, 12, or 18

# Valid forecast times to download, inclusive, at 6-hour intervals.
VALID_START = "2026-10-17 00:00"
VALID_END   = "2026-10-17 18:00"

# Spatial subset (degrees). Keep some margin around Chennai.
MIN_LAT = 5.0
MAX_LAT = 20.0
MIN_LON = 70.0
MAX_LON = 90.0

# Pressure levels in hPa. These cover the lower atmosphere to about 40+ km.
PRESSURE_LEVELS_HPA = [
    1000, 975, 950, 925, 900, 875, 850, 825, 800, 775, 750,
    700, 650, 600, 550, 500, 450, 400, 350, 300, 250, 225,
    200, 175, 150, 125, 100, 70, 50, 30, 20, 10, 7, 5, 3, 2, 1
]

# Files and output.
DATA_DIR = Path("balloon_burst_calculator") / "cfsv2_time_series"
GRIB_DIR = DATA_DIR / "grib"
NETCDF_FILE = DATA_DIR / "cfs_time_dependent.nc"

# Network settings.
REQUEST_TIMEOUT_SECONDS = 120
MAX_RETRIES = 3
REQUEST_DELAY_SECONDS = 0.5

BASE_URL = "https://nomads.ncep.noaa.gov/cgi-bin/filter_cfs_pgb.pl"


# ============================================================
# HELPERS
# ============================================================

def parse_utc(text):
    """Parse a timezone-naive date string and treat it as UTC."""
    return datetime.strptime(text, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)


def valid_times(start, end):
    if end < start:
        raise ValueError("VALID_END must be equal to or later than VALID_START.")
    if start.minute or start.second or end.minute or end.second:
        raise ValueError("Valid times must be on whole hours.")
    if start.hour % 6 or end.hour % 6:
        raise ValueError("CFSv2 pressure-level valid times must be requested at 6-hour intervals.")
    result = []
    current = start
    while current <= end:
        result.append(current)
        current += timedelta(hours=6)
    return result


def build_url(issue_time, valid_time):
    lead_hours = int((valid_time - issue_time).total_seconds() // 3600)
    if lead_hours < 0:
        raise ValueError(
            f"Valid time {valid_time} precedes initialization {issue_time}."
        )

    init_tag = issue_time.strftime("%Y%m%d%H")
    valid_tag = valid_time.strftime("%Y%m%d%H")
    filename = f"pgbf{valid_tag}.01.{init_tag}.grb2"
    directory = f"/cfs.{issue_time:%Y%m%d}/{issue_time:%H}/6hrly_grib_01"

    params = {
        "dir": directory,
        "file": filename,
        "var_HGT": "on",
        "var_TMP": "on",
        "var_UGRD": "on",
        "var_VGRD": "on",
        "subregion": "",
        "toplat": str(MAX_LAT),
        "leftlon": str(MIN_LON),
        "rightlon": str(MAX_LON),
        "bottomlat": str(MIN_LAT),
    }

    # NOMADS filter uses one lev_<value>_mb=on flag for each pressure.
    for level in PRESSURE_LEVELS_HPA:
        params[f"lev_{level}_mb"] = "on"

    return BASE_URL + "?" + urlencode(params), filename, lead_hours


def download_file(url, destination):
    if destination.exists() and destination.stat().st_size > 1000:
        # Avoid treating an HTML error page as a downloaded GRIB.
        with destination.open("rb") as f:
            head = f.read(4)
        if head == b"GRIB":
            print(f"Already downloaded: {destination.name}")
            return True

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            print(f"  Download attempt {attempt}/{MAX_RETRIES}")
            response = requests.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
            if response.status_code != 200:
                raise RuntimeError(f"HTTP {response.status_code}: {response.text[:180]}")
            content = response.content
            if len(content) < 1000 or not content.startswith(b"GRIB"):
                raise RuntimeError(
                    "Response does not look like a GRIB2 file. "
                    "The requested CFS file may not be available on NOMADS."
                )
            destination.write_bytes(content)
            print(f"  Saved {destination} ({len(content):,} bytes)")
            return True
        except Exception as exc:
            print(f"  Download failed: {type(exc).__name__}: {exc}")
            if attempt < MAX_RETRIES:
                time.sleep(2 * attempt)

    return False


def normalize_dataset(path, valid_time, issue_time):
    """Open one filtered CFS GRIB2 and standardize its variable/coordinate names."""
    ds = xr.open_dataset(
        path,
        engine="cfgrib",
        backend_kwargs={"indexpath": ""},
    ).load()

    rename = {}
    for old, new in (
        ("gh", "HGT"),
        ("t", "TMP"),
        ("u", "UGRD"),
        ("v", "VGRD"),
        ("isobaricInhPa", "isobaricInhPa"),
        ("latitude", "latitude"),
        ("longitude", "longitude"),
    ):
        if old in ds.data_vars and old != new:
            rename[old] = new
    if rename:
        ds = ds.rename(rename)

    # Some cfgrib builds expose alternate coordinate spellings.
    coord_rename = {}
    for old, new in (("lat", "latitude"), ("lon", "longitude"),
                     ("isobaricInPa", "pressure_pa")):
        if old in ds.coords and new not in ds.coords:
            coord_rename[old] = new
    if coord_rename:
        ds = ds.rename(coord_rename)

    # Drop GRIB reference-time/step scalar coordinates before assigning valid time.
    drop_coords = [
        name for name in ("time", "step", "valid_time", "surface")
        if name in ds.coords and name not in ds.dims
    ]
    if drop_coords:
        ds = ds.drop_vars(drop_coords)

    required = {"HGT", "TMP", "UGRD", "VGRD"}
    missing = required - set(ds.data_vars)
    if missing:
        ds.close()
        raise ValueError(
            f"{path.name}: missing variables {sorted(missing)}. "
            f"Found {list(ds.data_vars)}."
        )

    # Ensure the standard dimensions expected by wind_model_time_dependent.py.
    if "isobaricInhPa" not in ds.coords and "isobaricInhPa" not in ds.dims:
        ds.close()
        raise ValueError(
            f"{path.name}: pressure coordinate 'isobaricInhPa' not found. "
            f"Coordinates: {list(ds.coords)}"
        )

    # Keep only required variables and put time first.
    ds = ds[["HGT", "TMP", "UGRD", "VGRD"]]
    ds = ds.expand_dims(time=[np.datetime64(valid_time.replace(tzinfo=None), "ns")])
    ds.attrs["source"] = "NOAA/NCEP CFSv2 pressure-level forecast via NOMADS"
    ds.attrs["forecast_initialization_utc"] = issue_time.strftime("%Y-%m-%d %H:%M UTC")
    ds.attrs["valid_time_utc"] = valid_time.strftime("%Y-%m-%d %H:%M UTC")
    return ds


def combine_gribs(grib_paths, times, issue_time):
    datasets = []
    try:
        for path, valid_time in zip(grib_paths, times):
            print(f"Reading {path.name} ...")
            ds = normalize_dataset(path, valid_time, issue_time)
            datasets.append(ds)

        combined = xr.concat(
            datasets,
            dim="time",
            data_vars="all",
            coords="minimal",
            compat="override",
            join="exact",
        ).sortby("time")

        # Attach useful metadata.
        combined.attrs.update({
            "title": "CFSv2 time-dependent pressure-level atmospheric data",
            "source": "NOAA/NCEP CFSv2 via NOMADS filter",
            "variables": "HGT (m), TMP (K), UGRD (m/s), VGRD (m/s)",
            "temporal_resolution": "6-hourly",
            "forecast_initialization_utc": (
                f"{ISSUE_DATE} {ISSUE_CYCLE_UTC:02d}:00 UTC"
            ),
            "region": (
                f"{MIN_LAT}-{MAX_LAT} N, {MIN_LON}-{MAX_LON} E"
            ),
        })

        # Compress variables for a smaller NetCDF file.
        encoding = {
            name: {"zlib": True, "complevel": 4}
            for name in ("HGT", "TMP", "UGRD", "VGRD")
        }
        NETCDF_FILE.parent.mkdir(parents=True, exist_ok=True)
        combined.to_netcdf(NETCDF_FILE, engine="netcdf4", encoding=encoding)

        print("\nNetCDF created successfully:")
        print(f"  {NETCDF_FILE.resolve()}")
        print(combined)
        print("\nTime coordinates (UTC):")
        for value in combined["time"].values:
            print(" ", np.datetime_as_string(value, unit="m"), "UTC")
        combined.close()
    finally:
        for ds in datasets:
            try:
                ds.close()
            except Exception:
                pass


# ============================================================
# MAIN
# ============================================================

def main():
    issue_time = datetime.strptime(
        f"{ISSUE_DATE} {ISSUE_CYCLE_UTC:02d}",
        "%Y-%m-%d %H",
    ).replace(tzinfo=timezone.utc)

    start = parse_utc(VALID_START)
    end = parse_utc(VALID_END)
    times = valid_times(start, end)

    if any(t < issue_time for t in times):
        raise ValueError("All valid times must be on/after the CFS initialization time.")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    GRIB_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 72)
    print("CFSv2 PRESSURE-LEVEL DOWNLOAD + NETCDF COMBINATION")
    print("=" * 72)
    print(f"Initialization : {issue_time:%Y-%m-%d %H:%M UTC}")
    print(f"Valid times    : {VALID_START} to {VALID_END} UTC")
    print(f"Region         : {MIN_LAT}-{MAX_LAT} N, {MIN_LON}-{MAX_LON} E")
    print(f"Levels         : {len(PRESSURE_LEVELS_HPA)} pressure levels")
    print(f"Output         : {NETCDF_FILE.resolve()}")

    downloaded_paths = []
    successful_times = []
    failures = []

    for valid_time in times:
        url, filename, lead_hours = build_url(issue_time, valid_time)
        destination = GRIB_DIR / filename
        print(
            f"\nValid {valid_time:%Y-%m-%d %H:%M UTC} | "
            f"lead F{lead_hours:03d} | {filename}"
        )
        if download_file(url, destination):
            downloaded_paths.append(destination)
            successful_times.append(valid_time)
        else:
            failures.append((valid_time, filename))
        time.sleep(REQUEST_DELAY_SECONDS)

    if failures:
        print("\nWARNING: These valid times could not be downloaded:")
        for valid_time, filename in failures:
            print(f"  {valid_time:%Y-%m-%d %H:%M UTC}: {filename}")

    if not downloaded_paths:
        raise SystemExit(
            "\nNo CFSv2 GRIB files were downloaded. Check the issue cycle, "
            "valid times, and NOMADS file availability."
        )

    combine_gribs(downloaded_paths, successful_times, issue_time)

    print("\nDone.")
    if failures:
        print(
            "The NetCDF contains only successfully downloaded timestamps. "
            "Check the warnings before using it for a trajectory simulation."
        )


if __name__ == "__main__":
    main()
