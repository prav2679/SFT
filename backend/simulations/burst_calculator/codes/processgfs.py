"""
process_gfs_forecast_to_netcdf.py

Convert downloaded NOAA GFS GRIB2 forecast files to a regional, time-dependent
NetCDF file for the balloon GNC workflow.

Supports common filename styles:
  1) NCEI archive: gfs_4_YYYYMMDD_HHMM_FFF.grb2
     Example: gfs_4_20261012_1800_384.grb2
  2) NOMADS operational: gfs.tCCz.pgrb2.0p25.fFFF
     Example: gfs.t18z.pgrb2.0p25.f006
  3) CFS-style pgbf files (kept for compatibility):
     pgbfYYYYMMDDHH.01.YYYYMMDDHH.grb2

This script processes files already downloaded. It does NOT download data.

Install:
    py -m pip install numpy xarray cfgrib netCDF4 eccodes

Run:
    py process_gfs_forecast_to_netcdf.py "C:\\path\\to\\downloaded_grib_folder"

Notes:
- Output time is the forecast valid time, not just the initialization time.
- Only isobaric pressure-level fields are selected.
- Variables are normalized to UGRD, VGRD, HGT, TMP where present.
- GFS files may not contain all four variables in every file. The report lists
  missing variables and incomplete valid times.
"""

from __future__ import annotations

import re
import sys
import warnings
from datetime import datetime, timedelta
from pathlib import Path

import cfgrib
import numpy as np
import xarray as xr

# ------------------------- USER SETTINGS -------------------------

LAT_MIN, LAT_MAX = 5.0, 20.0
LON_MIN, LON_MAX = 70.0, 90.0

# Balloon project needs upper-air coverage through 40 km.
MAX_HEIGHT_M = 40000

OUTPUT_FILENAME = "gfs_regional_time_dependent.nc"
REPORT_FILENAME = "gfs_netcdf_conversion_report.txt"

REQUIRED_VARIABLES = {"UGRD", "VGRD", "HGT", "TMP"}

warnings.filterwarnings(
    "ignore",
    message="In a future version of xarray the default value for compat will change",
    category=FutureWarning,
)


# ------------------------- FILE TIME PARSING -------------------------

def parse_times(path: Path):
    
    name = path.name

    # NCEI GFS archive: gfs_4_YYYYMMDD_HHMM_FFF.grb2
    match = re.search(
        r"gfs_4_(\d{8})_(\d{4})_(\d{3,4})\.grb2?$",
        name,
        re.IGNORECASE,
    )
    if match:
        init = datetime.strptime(match.group(1) + match.group(2), "%Y%m%d%H%M")
        lead_hours = int(match.group(3))
        return init + timedelta(hours=lead_hours), init

    # NOMADS operational GFS: gfs.tCCz.pgrb2....fFFF (file may have no extension)
    match = re.search(
        r"gfs\.t(\d{2})z\.pgrb2(?:\.[^.]+)*\.f(\d{3})$",
        name,
        re.IGNORECASE,
    )
    if match:
        # Cycle date is not in this filename. The caller will prefer GRIB metadata
        # for valid_time when available; this returns no date-based fallback.
        return None, None

    # CFSv2 / pgbf-style filename, retained for compatibility.
    match = re.search(
        r"^pgbf(\d{10})\.\d+\.(\d{10})\.grb2?$",
        name,
        re.IGNORECASE,
    )
    if match:
        valid_time = datetime.strptime(match.group(1), "%Y%m%d%H")
        init_time = datetime.strptime(match.group(2), "%Y%m%d%H")
        return valid_time, init_time

    return None, None


def normalized_variable_name(da):
    """Map common GRIB short names and cfgrib variable names."""
    short = str(
        da.attrs.get("GRIB_shortName", da.attrs.get("shortName", da.name))
    ).lower()

    mapping = {
        "u": "UGRD",
        "ugrd": "UGRD",
        "v": "VGRD",
        "vgrd": "VGRD",
        "gh": "HGT",
        "hgt": "HGT",
        "z": "HGT",   # geopotential; converted to geopotential height below
        "t": "TMP",
        "tmp": "TMP",
    }
    if short in mapping:
        return mapping[short]

    name = str(da.name).upper()
    if name in REQUIRED_VARIABLES:
        return name
    return None


def get_time_from_dataset(ds, fallback_valid_time=None):
    """Read cfgrib valid_time/time+step; fall back to filename time."""
    if "valid_time" in ds.coords:
        value = np.asarray(ds["valid_time"].values).reshape(-1)[0]
        try:
            return np.datetime64(value, "ns")
        except Exception:
            pass

    if "time" in ds.coords:
        base = np.asarray(ds["time"].values).reshape(-1)[0]
        if "step" in ds.coords:
            step = np.asarray(ds["step"].values).reshape(-1)[0]
            try:
                return np.datetime64(base, "ns") + np.timedelta64(
                    int(step / np.timedelta64(1, "ns")), "ns"
                )
            except Exception:
                pass
        try:
            return np.datetime64(base, "ns")
        except Exception:
            pass

    if fallback_valid_time is not None:
        return np.datetime64(fallback_valid_time, "ns")

    raise ValueError("Could not determine forecast valid time from GRIB metadata or filename.")


def subset_region(ds):
    """Normalize coordinate names and crop to requested region."""
    rename = {}
    if "lat" in ds.coords and "latitude" not in ds.coords:
        rename["lat"] = "latitude"
    if "lon" in ds.coords and "longitude" not in ds.coords:
        rename["lon"] = "longitude"
    if rename:
        ds = ds.rename(rename)

    if "latitude" not in ds.coords or "longitude" not in ds.coords:
        raise ValueError(f"Latitude/longitude coordinates missing: {list(ds.coords)}")

    # Convert 0..360 longitudes to -180..180 if needed, then crop consistently.
    lon = ds["longitude"]
    if float(lon.max()) > 180 and LON_MAX <= 180:
        normalized = ((lon + 180) % 360) - 180
        ds = ds.assign_coords(longitude=normalized).sortby("longitude")

    lat_mask = (ds.latitude >= LAT_MIN) & (ds.latitude <= LAT_MAX)
    lon_mask = (ds.longitude >= LON_MIN) & (ds.longitude <= LON_MAX)
    ds = ds.where(lat_mask & lon_mask, drop=True)

    if ds.sizes.get("latitude", 0) == 0 or ds.sizes.get("longitude", 0) == 0:
        raise ValueError("Regional crop is empty; check grid and longitude convention.")
    return ds


def read_grib_file(path: Path):
    fallback_valid_time, filename_init_time = parse_times(path)

    print(f"  Decoding {path.name} ...", flush=True)

    # Open separate GRIB message groups (e.g. variables/level types).
    groups = cfgrib.open_datasets(
        str(path),
        backend_kwargs={"indexpath": ""},
    )

    try:
        collected = {}
        valid_time = None
        init_time = None

        for group in groups:
            if "isobaricInhPa" not in group.coords:
                continue

            try:
                this_valid = get_time_from_dataset(group, fallback_valid_time)
                if valid_time is None:
                    valid_time = this_valid
                elif this_valid != valid_time:
                    # A single file should normally represent one valid time.
                    print(
                        f"  WARNING: multiple valid times found in {path.name}; "
                        "using each group only when its time matches the first."
                    )
                    if this_valid != valid_time:
                        continue
            except Exception:
                continue

            if "time" in group.coords:
                try:
                    init_time = np.asarray(group["time"].values).reshape(-1)[0]
                except Exception:
                    pass

            for _, da in group.data_vars.items():
                key = normalized_variable_name(da)
                if key is None:
                    continue

                # Keep first instance of each standardized variable for this file.
                if key in collected:
                    continue

                da = da.rename(key)

                if key == "HGT":
                    units = str(da.attrs.get("units", "")).lower().replace(" ", "")
                    # GRIB geopotential z is m^2/s^2; divide by standard gravity.
                    if units in {
                        "m**2s**-2", "m^2s^-2", "m2s-2", "m**2/s**2",
                        "m^2/s^2", "m2/s2",
                    } or str(da.attrs.get("GRIB_shortName", "")).lower() == "z":
                        da = da / 9.80665
                        da.attrs["units"] = "m"
                        da.attrs["long_name"] = "Geopotential height derived from geopotential"

                collected[key] = da

        if not collected:
            raise ValueError(
                "No U/V/HGT/TMP variables found on isobaric pressure levels."
            )

        if valid_time is None:
            if fallback_valid_time is None:
                raise ValueError("Could not determine valid time.")
            valid_time = np.datetime64(fallback_valid_time, "ns")

        ds = xr.Dataset(collected)
        # Remove forecast metadata coordinates that can conflict with the explicit time dimension.
        for coord_name in ("step", "valid_time", "forecast_reference_time"):
            if coord_name in ds.coords:
                ds = ds.drop_vars(coord_name)

        ds = subset_region(ds)
        ds = ds.load()
        ds = ds.expand_dims(time=[valid_time])

        ds.attrs["source_file"] = path.name
        ds.attrs["forecast_valid_time_utc"] = str(valid_time)
        if filename_init_time is not None:
            ds.attrs["run_initialization_utc"] = filename_init_time.isoformat() + "Z"
        elif init_time is not None:
            ds.attrs["run_initialization_utc"] = str(init_time)

        return ds
    finally:
        for group in groups:
            try:
                group.close()
            except Exception:
                pass


def main():
    if len(sys.argv) > 1:
        input_dir = Path(sys.argv[1]).expanduser().resolve()
    else:
        input_dir = (Path.cwd() / r"cfsv2_time_series\22oct1").resolve()

    if not input_dir.is_dir():
        print(f"ERROR: input folder does not exist: {input_dir}")
        print('Usage: py process_gfs_forecast_to_netcdf.py "C:\\path\\to\\GRIB_folder"')
        sys.exit(2)

    extensions = {".grb2", ".grb", ".grib2", ".grib"}
    files = sorted(
        [p for p in input_dir.iterdir() if p.is_file() and
         (p.suffix.lower() in extensions or p.name.lower().endswith(".f000")
          or ".pgrb2." in p.name.lower())]
    )

    if not files:
        print(f"No GRIB files found in {input_dir}")
        sys.exit(2)

    print("=" * 72)
    print("GFS GRIB2 -> REGIONAL TIME-DEPENDENT NETCDF")
    print("=" * 72)
    print("Input folder:", input_dir)
    print("GRIB files found:", len(files))
    print(f"Region: {LAT_MIN}–{LAT_MAX}°N, {LON_MIN}–{LON_MAX}°E")
    print(f"Maximum target height: {MAX_HEIGHT_M / 1000:.1f} km")
    print("Required variables:", ", ".join(sorted(REQUIRED_VARIABLES)))
    print()

    datasets = []
    errors = []

    for index, path in enumerate(files, start=1):
        print(f"[{index}/{len(files)}]", flush=True)
        try:
            ds = read_grib_file(path)
            datasets.append(ds)
            print(
                f"  Valid time: {ds.time.values[0]} | Variables: "
                f"{', '.join(sorted(ds.data_vars))}",
                flush=True,
            )
        except Exception as exc:
            errors.append((path.name, repr(exc)))
            print(f"  ERROR: {type(exc).__name__}: {exc}", flush=True)

    if not datasets:
        print("No files were decoded successfully. See errors above.")
        sys.exit(3)

    print("\nCombining fields by valid time...", flush=True)
    combined = xr.concat(
        datasets,
        dim="time",
        data_vars="all",
        coords="minimal",
        compat="override",
        join="outer",
        combine_attrs="drop_conflicts",
    ).sortby("time")

    # Remove duplicate valid times, keeping first occurrence.
    time_values = np.asarray(combined.time.values)
    _, first_indices = np.unique(time_values, return_index=True)
    combined = combined.isel(time=np.sort(first_indices))

    # Filter pressure levels based on regional median geopotential height.
    # Keep all levels if height isn't available or no level qualifies.
    if "HGT" in combined and "isobaricInhPa" in combined.coords:
        dims = [dim for dim in ("time", "latitude", "longitude") if dim in combined["HGT"].dims]
        median_height = combined["HGT"].median(dim=dims, skipna=True) if dims else combined["HGT"]
        selected_levels = median_height.where(
            np.isfinite(median_height) & (median_height <= MAX_HEIGHT_M),
            drop=True,
        )["isobaricInhPa"].values
        if len(selected_levels):
            combined = combined.sel(isobaricInhPa=selected_levels)
        else:
            print("WARNING: no levels passed the height filter; retaining all levels.")

    variable_metadata = {
        "UGRD": ("Eastward wind component", "m s-1"),
        "VGRD": ("Northward wind component", "m s-1"),
        "HGT": ("Geopotential height", "m"),
        "TMP": ("Air temperature", "K"),
    }
    for name, (long_name, units) in variable_metadata.items():
        if name in combined:
            combined[name].attrs.setdefault("long_name", long_name)
            combined[name].attrs.setdefault("units", units)

    missing_variables = sorted(REQUIRED_VARIABLES - set(combined.data_vars))
    combined.attrs.update({
        "title": "GFS regional pressure-level forecast",
        "source": "NOAA Global Forecast System (GFS) GRIB files",
        "latitude_min": LAT_MIN,
        "latitude_max": LAT_MAX,
        "longitude_min": LON_MIN,
        "longitude_max": LON_MAX,
        "maximum_height_filter_m": MAX_HEIGHT_M,
        "input_file_count": len(files),
        "decoded_file_count": len(datasets),
        "failed_file_count": len(errors),
        "missing_required_variables": ", ".join(missing_variables) if missing_variables else "none",
        "temporal_resolution_note": "Uses valid times present in input files; no hourly data are synthesized.",
    })

    output_path = input_dir / OUTPUT_FILENAME
    report_path = input_dir / REPORT_FILENAME

    encoding = {
        name: {"zlib": True, "complevel": 1, "dtype": "float32"}
        for name in combined.data_vars
        if np.issubdtype(combined[name].dtype, np.number)
    }

    print("Writing NetCDF:", output_path, flush=True)
    combined.to_netcdf(
        output_path,
        engine="netcdf4",
        format="NETCDF4",
        encoding=encoding,
    )

    report_lines = [
        "GFS GRIB to NetCDF conversion report",
        f"Input folder: {input_dir}",
        f"GRIB files found: {len(files)}",
        f"Files decoded: {len(datasets)}",
        f"Files failed: {len(errors)}",
        f"Output file: {output_path}",
        f"Output size MiB: {output_path.stat().st_size / (1024 * 1024):.2f}",
        f"Dimensions: {dict(combined.sizes)}",
        f"Variables: {list(combined.data_vars)}",
        f"Missing required variables: {missing_variables}",
        f"Valid times UTC: {combined.time.values}",
        "Pressure levels hPa: " + (
            str(combined.isobaricInhPa.values.tolist())
            if "isobaricInhPa" in combined.coords else "missing"
        ),
        "",
        "Errors:",
        *(f"{name}: {error}" for name, error in errors),
    ]
    report_path.write_text("\n".join(map(str, report_lines)), encoding="utf-8")

    print("\nCONVERSION FINISHED")
    print("NetCDF:", output_path)
    print("Report:", report_path)
    print("Dimensions:", dict(combined.sizes))
    print("Variables:", list(combined.data_vars))
    print("Missing required variables:", missing_variables if missing_variables else "none")
    print(f"Successfully decoded {len(datasets)} of {len(files)} files.")
    print("Note: timestamps come from GRIB metadata where possible.")

    combined.close()
    for ds in datasets:
        ds.close()

    if errors:
        print("\nSome files failed. Review:", report_path)


if __name__ == "__main__":
    main()
