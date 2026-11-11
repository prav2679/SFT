import re
import sys
import warnings
from pathlib import Path
from datetime import datetime

import numpy as np
import xarray as xr
import cfgrib

# Requested regional limits
LAT_MIN, LAT_MAX = 0 , 20
LON_MIN, LON_MAX = 65 , 95
MAX_HEIGHT_M = 28000.0

OUTPUT_FILENAME = "cfsv2_120hr_regional_forecast.nc"
REPORT_FILENAME = "netcdf_conversion_report.txt"

warnings.filterwarnings(
    "ignore",
    message="In a future version of xarray the default value for compat will change",
    category=FutureWarning,
)


def parse_times(path):
    """Parse valid time and initialization time from pgbfYYYYMMDDHH.01.YYYYMMDDHH.grb2."""
    match = re.search(
        r"^pgbf(\d{10})\.\d+\.(\d{10})\.grb2?$",
        path.name,
        re.IGNORECASE,
    )
    if not match:
        return None, None

    return (
        datetime.strptime(match.group(1), "%Y%m%d%H"),
        datetime.strptime(match.group(2), "%Y%m%d%H"),
    )


def canonical_name(da):
    """Map common GRIB short names to consistent variable names."""
    short = str(
        da.attrs.get("GRIB_shortName", da.attrs.get("shortName", da.name))
    ).lower()

    mapping = {
        "u": "UGRD", "ugrd": "UGRD",
        "v": "VGRD", "vgrd": "VGRD",
        "gh": "HGT", "hgt": "HGT",
        "z": "HGT",
        "t": "TMP", "tmp": "TMP",
    }
    if short in mapping:
        return mapping[short]

    name = str(da.name).upper()
    return name if name in {"UGRD", "VGRD", "HGT", "TMP"} else None


def subset_region(ds):
    """Normalize coordinate names and subset the requested geographic region."""
    rename = {}
    if "lat" in ds.coords and "latitude" not in ds.coords:
        rename["lat"] = "latitude"
    if "lon" in ds.coords and "longitude" not in ds.coords:
        rename["lon"] = "longitude"
    if rename:
        ds = ds.rename(rename)

    if "latitude" not in ds.coords or "longitude" not in ds.coords:
        raise ValueError(
            f"Latitude/longitude coordinates missing. Coordinates: {list(ds.coords)}"
        )

    # Boolean masking supports either ascending or descending latitude coordinates.
    ds = ds.where(
        (ds.latitude >= LAT_MIN) & (ds.latitude <= LAT_MAX)
        & (ds.longitude >= LON_MIN) & (ds.longitude <= LON_MAX),
        drop=True,
    )

    if ds.sizes.get("latitude", 0) == 0 or ds.sizes.get("longitude", 0) == 0:
        raise ValueError(
            "Regional crop is empty. Check the grid and longitude convention."
        )
    return ds


def read_one(path):
    valid_time, run_time = parse_times(path)
    if valid_time is None:
        print(f"Skipping unrecognized filename: {path.name}", flush=True)
        return None

    print(
        f"  Decoding {path.name} "
        f"(valid {valid_time:%Y-%m-%d %H:%M} UTC)...",
        flush=True,
    )

    # Disable .idx files; they can become stale or cause write-permission issues.
    groups = cfgrib.open_datasets(
        str(path),
        backend_kwargs={"indexpath": ""},
    )

    fields = {}
    for group in groups:
        if "isobaricInhPa" not in group.coords:
            continue

        for _, da in group.data_vars.items():
            key = canonical_name(da)
            if key is None or key in fields:
                continue

            da = da.rename(key)

            if key == "HGT":
                units = str(da.attrs.get("units", "")).lower().replace(" ", "")
                if units in {
                    "m**2s**-2", "m^2s^-2", "m2s-2", "m**2/s**2",
                    "m^2/s^2",
                }:
                    da = da / 9.80665
                    da.attrs["units"] = "m"
                    da.attrs["long_name"] = (
                        "Geopotential height derived from geopotential"
                    )

            fields[key] = da

    if not fields:
        raise ValueError(
            "No requested variables found on isobaricInhPa pressure levels."
        )

    # Assign filename-derived valid time and remove conflicting forecast metadata.
    ds = xr.Dataset(fields).expand_dims(time=[np.datetime64(valid_time)])
    for coord_name in ("step", "valid_time", "forecast_reference_time"):
        if coord_name in ds.coords:
            ds = ds.drop_vars(coord_name)

    ds = subset_region(ds)

    # Load this regional subset before moving to the next file. This avoids
    # retaining open GRIB handles and reduces deferred-read surprises.
    ds.load()

    ds.attrs["run_initialization_utc"] = run_time.isoformat() + "Z"
    ds.attrs["source_file"] = path.name
    return ds


def main():
    default_input = Path.cwd() / r"hover_5days\grib"
    input_dir = Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 else default_input
    input_dir = input_dir.resolve()

    if not input_dir.is_dir():
        print(f"ERROR: input folder does not exist: {input_dir}")
        print(
            'Run with the GRIB folder path, for example:\n'
            'python gribtonetcdf.py "C:\\path\\to\\cfsv2_download"'
        )
        sys.exit(2)

    files = []
    for pattern in ("*.grb2", "*.grb", "*.grib2", "*.grib"):
        files.extend(input_dir.glob(pattern))

    files = sorted(
        {f.resolve() for f in files if parse_times(f)[0] is not None},
        key=lambda f: parse_times(f)[0],
    )

    if not files:
        print(f"No recognized pgbf GRIB files found in: {input_dir}")
        print("Expected names like pgbf2026101700.01.2026101118.grb2")
        sys.exit(2)

    print("=" * 72)
    print("CFSv2 GRIB2 -> REGIONAL NETCDF")
    print("=" * 72)
    print("Input folder:", input_dir)
    print("Recognized GRIB files:", len(files))
    print(f"Region: {LAT_MIN}–{LAT_MAX} N, {LON_MIN}–{LON_MAX} E")
    print("Fields: U wind, V wind, geopotential/height, temperature")
    print("Vertical filter: regional median height <= 28 km")
    print("Output will be written directly inside the input folder.")
    print()

    datasets, errors = [], []
    for i, path in enumerate(files, 1):
        print(f"[{i}/{len(files)}]", flush=True)
        try:
            ds = read_one(path)
            if ds is not None:
                datasets.append(ds)
        except Exception as exc:
            errors.append((path.name, repr(exc)))
            print(f"  ERROR: {exc}", flush=True)

    if not datasets:
        print("No files were successfully decoded. See errors above.")
        sys.exit(3)

    print("\nConcatenating by explicit valid time...", flush=True)
    combined = xr.concat(
        datasets,
        dim="time",
        data_vars="all",
        coords="minimal",
        compat="override",
        join="outer",
        combine_attrs="drop_conflicts",
    ).sortby("time")

    # Remove duplicate valid timestamps if the input folder contains duplicates.
    times = np.asarray(combined.time.values)
    _, first_idx = np.unique(times, return_index=True)
    combined = combined.isel(time=np.sort(first_idx))

    if "HGT" in combined and "isobaricInhPa" in combined.coords:
        dims = [d for d in ("time", "latitude", "longitude") if d in combined.HGT.dims]
        median_height = (
            combined.HGT.median(dim=dims, skipna=True)
            if dims else combined.HGT
        )
        levels = median_height.where(
            np.isfinite(median_height) & (median_height <= MAX_HEIGHT_M),
            drop=True,
        )["isobaricInhPa"].values

        if len(levels):
            combined = combined.sel(isobaricInhPa=levels)
        else:
            print(
                "WARNING: no pressure levels passed the 28 km filter; "
                "retaining all pressure levels."
            )

    metadata = {
        "UGRD": ("Eastward wind", "m s-1"),
        "VGRD": ("Northward wind", "m s-1"),
        "HGT": ("Geopotential height", "m"),
        "TMP": ("Air temperature", "K"),
    }
    for name, (long_name, units) in metadata.items():
        if name in combined:
            combined[name].attrs.setdefault("long_name", long_name)
            combined[name].attrs.setdefault("units", units)

    required = {"UGRD", "VGRD", "HGT", "TMP"}
    missing = sorted(required - set(combined.data_vars))

    combined.attrs.update({
        "title": "CFSv2 regional pressure-level forecast",
        "source": "NOAA NCEI CFSv2 operational forecast GRIB2 files",
        "latitude_min": LAT_MIN,
        "latitude_max": LAT_MAX,
        "longitude_min": LON_MIN,
        "longitude_max": LON_MAX,
        "vertical_selection": (
            "Pressure levels with regional median height <= 28000 m"
        ),
        "input_file_count": len(files),
        "decoded_file_count": len(datasets),
        "failed_file_count": len(errors),
        "missing_required_variables": ", ".join(missing) if missing else "none",
    })

    output = input_dir / OUTPUT_FILENAME
    report_path = input_dir / REPORT_FILENAME

    # If an old output is locked by another program, fail with a clear message.
    if output.exists():
        try:
            output.unlink()
        except PermissionError:
            print(
                f"\nERROR: Cannot replace existing output:\n{output}\n"
                "Close the file in Python, Panoply, QGIS, or any other program, "
                "then delete/rename it and rerun."
            )
            sys.exit(4)

    # Compression reduces output size but costs CPU time. Use level 1 for a
    # faster conversion; change to 4 if stronger compression is preferred.
    encoding = {
        name: {"zlib": True, "complevel": 1, "dtype": "float32"}
        for name in combined.data_vars
        if np.issubdtype(combined[name].dtype, np.number)
    }

    print("Writing:", output, flush=True)
    try:
        combined.to_netcdf(
            output,
            engine="netcdf4",
            format="NETCDF4",
            encoding=encoding,
        )
    except PermissionError as exc:
        print(
            "\nERROR: Windows denied access to the output path.\n"
            f"Path: {output}\n"
            "Check that the file is not open in another program and that you "
            "have write permission to the input folder."
        )
        raise exc

    lines = [
        "CFSv2 GRIB2 to NetCDF report",
        f"Input folder: {input_dir}",
        f"GRIB files found: {len(files)}",
        f"Files decoded: {len(datasets)}",
        f"Files failed: {len(errors)}",
        f"Output file: {output}",
        f"Output size MiB: {output.stat().st_size / (1024 * 1024):.2f}",
        f"Dimensions: {dict(combined.sizes)}",
        f"Variables: {list(combined.data_vars)}",
        f"Missing required variables: {missing}",
        f"Times: {combined.time.values}",
        (
            "Pressure levels hPa: "
            f"{combined.isobaricInhPa.values.tolist() if 'isobaricInhPa' in combined.coords else 'missing'}"
        ),
        "",
        "Errors:",
        *(f"{name}: {error}" for name, error in errors),
    ]
    report_path.write_text("\n".join(map(str, lines)), encoding="utf-8")

    print("\nCONVERSION FINISHED")
    print("NetCDF:", output)
    print("Report:", report_path)
    print("Dimensions:", dict(combined.sizes))
    print("Variables:", list(combined.data_vars))
    print("Missing required variables:", missing if missing else "none")
    print(f"Successfully decoded {len(datasets)} of {len(files)} files.")

    # Inform the user about gaps in the expected 6-hour time series.
    actual_times = {
        np.datetime_as_string(t, unit="h")
        for t in np.asarray(combined.time.values).astype("datetime64[h]")
    }
    if len(combined.time) > 1:
        expected = np.arange(
            np.asarray(combined.time.values).min().astype("datetime64[h]"),
            np.asarray(combined.time.values).max().astype("datetime64[h]") + np.timedelta64(6, "h"),
            np.timedelta64(6, "h"),
        )
        missing_times = [
            np.datetime_as_string(t, unit="h")
            for t in expected
            if np.datetime_as_string(t, unit="h") not in actual_times
        ]
        if missing_times:
            print("WARNING: missing 6-hour valid times:", ", ".join(missing_times))

    if errors:
        print("Some files failed. Review netcdf_conversion_report.txt before using the output.")


if __name__ == "__main__":
    main()
