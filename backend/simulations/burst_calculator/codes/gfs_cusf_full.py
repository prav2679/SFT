#!/usr/bin/env python3
"""
Download GFS 0.25-degree pressure-level forecast fields and write a Tawhiri-style
binary atmosphere dataset.

IMPORTANT:
- This creates a large file (about 8.88 GiB with the dimensions below).
- It assumes the target Tawhiri dataset layout is:
    float32, C-order, [forecast_time, pressure_level, variable, latitude, longitude]
  with variables ordered [geopotential height in metres, U wind in m/s, V wind in m/s].
- Confirm that layout and the pressure/coordinate axes against the exact Tawhiri
  reader/version you are using before using the output for operational predictions.
"""

from __future__ import annotations

import argparse
import gc
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import requests
import xarray as xr
from herbie import Herbie


# Target pressure axis used by this converter. Keep this identical to the axis
# expected by your local Tawhiri data reader.
# 47 target levels spanning the GFS pressure-level range. This is a generic
# log-spaced axis, NOT guaranteed to match a particular Tawhiri build's axis.
# If your installed Tawhiri reader defines a specific 47-level pressure array,
# replace this with that exact array before using the generated dataset.
# Exact 47-level pressure axis used by CUSF Tawhiri Dataset.axes.pressure.
# Keep descending order: the Cython interpolator expects the native ordering.
PRESSURES_HPA = np.array(
    sorted(
        [
            10, 20, 30, 50, 70, 100, 150, 200, 250, 300, 350, 400,
            450, 500, 550, 600, 650, 700, 750, 800, 850, 900, 925,
            950, 975, 1000,
            1, 2, 3, 5, 7, 125, 175, 225, 275, 325, 375, 425,
            475, 525, 575, 625, 675, 725, 775, 825, 875,
        ],
        reverse=True,
    ),
    dtype=np.float64,
)

# GFS provides 3-hourly forecasts through +120 h, then 6-hourly forecasts.
# We produce a 3-hourly output axis through +192 h and interpolate missing
# valid times between the available forecast fields.
OUTPUT_HOURS = list(range(0, 193, 3))
SOURCE_HOURS = list(range(0, 121, 3)) + list(range(126, 193, 6))

# A global 0.5-degree grid: latitude -90..90, longitude 0..359.5.
LATITUDES = np.arange(-90.0, 90.0 + 0.001, 0.5, dtype=np.float32)
LONGITUDES = np.arange(0.0, 360.0, 0.5, dtype=np.float32)

N_TIMES = len(OUTPUT_HOURS)
N_PRESSURES = len(PRESSURES_HPA)
N_VARIABLES = 3
N_LAT = len(LATITUDES)
N_LON = len(LONGITUDES)
OUTPUT_SHAPE = (N_TIMES, N_PRESSURES, N_VARIABLES, N_LAT, N_LON)
OUTPUT_BYTES = int(np.prod(OUTPUT_SHAPE)) * np.dtype(np.float32).itemsize

LOG = logging.getLogger("gfs_cusf")


def parse_cycle(value: str) -> datetime:
    """Parse cycle date/time as YYYYMMDDHH and return UTC-aware datetime."""
    try:
        parsed = datetime.strptime(value, "%Y%m%d%H")
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "Cycle must use YYYYMMDDHH, for example 2026102800"
        ) from exc
    return parsed.replace(tzinfo=timezone.utc)


def get_data_dir(cycle: datetime, output_root: Path) -> Path:
    return output_root / cycle.strftime("%Y%m%d%H")


def _find_var(ds: xr.Dataset, candidates: tuple[str, ...]) -> str:
    for name in candidates:
        if name in ds.data_vars:
            return name
    lowered = {name.lower(): name for name in ds.data_vars}
    for name in candidates:
        if name.lower() in lowered:
            return lowered[name.lower()]
    raise KeyError(
        f"Could not find any of {candidates}. Variables found: "
        f"{list(ds.data_vars)}"
    )


def _normalise_coords(ds: xr.Dataset) -> xr.Dataset:
    """Normalise common GFS coordinate names and longitude convention."""
    rename = {}
    for old, new in (
        ("latitude", "latitude"),
        ("longitude", "longitude"),
        ("lat", "latitude"),
        ("lon", "longitude"),
        ("isobaricInhPa", "isobaricInhPa"),
        ("pressure", "isobaricInhPa"),
    ):
        if old in ds.coords and old != new and new not in ds.coords:
            rename[old] = new
        elif old in ds.dims and old != new and new not in ds.dims:
            rename[old] = new
    if rename:
        ds = ds.rename(rename)

    if "latitude" not in ds.coords or "longitude" not in ds.coords:
        raise KeyError(
            f"Expected latitude/longitude coordinates; got {list(ds.coords)}"
        )
    if "isobaricInhPa" not in ds.coords:
        raise KeyError(
            f"Expected isobaricInhPa pressure coordinate; got {list(ds.coords)}"
        )

    # GFS usually uses 0..360 longitude. Convert negative longitudes if needed.
    lon = np.asarray(ds["longitude"].values, dtype=np.float64)
    if np.nanmin(lon) < 0:
        ds = ds.assign_coords(longitude=(lon % 360.0))
    ds = ds.sortby("longitude").sortby("latitude")
    return ds


def _open_grib(grib_path: Path) -> xr.Dataset:
    """
    Open and combine GFS pressure-level groups.

    GFS may store lower/middle pressure levels under isobaricInhPa (hPa) and
    very high-altitude levels under isobaricInPa (Pa). cfgrib can therefore
    split one file into multiple groups. Normalize each pressure coordinate
    to hPa and concatenate compatible groups along the pressure axis.
    """
    import cfgrib

    groups = cfgrib.open_datasets(
        str(grib_path),
        backend_kwargs={"indexpath": ""},
    )

    candidates = []
    for group_index, original in enumerate(groups):
        ds = original
        names = set(ds.data_vars)

        has_height = bool(names & {"gh", "hgt", "HGT", "z", "Geopotential_height"})
        has_u = bool(names & {"u", "ugrd", "UGRD", "u_component_of_wind"})
        has_v = bool(names & {"v", "vgrd", "VGRD", "v_component_of_wind"})
        if not (has_height and has_u and has_v):
            continue

        # Identify pressure coordinate and convert its numeric values to hPa.
        if "isobaricInPa" in ds.coords:
            raw_pressure = np.asarray(ds["isobaricInPa"].values, dtype=np.float64)
            pressure_hpa = raw_pressure / 100.0
            pressure_dim = "isobaricInPa"
        elif "isobaricInhPa" in ds.coords:
            raw_pressure = np.asarray(ds["isobaricInhPa"].values, dtype=np.float64)
            pressure_hpa = raw_pressure
            pressure_dim = "isobaricInhPa"
        else:
            LOG.warning(
                "Skipping GRIB group %d: no supported pressure coordinate; coords=%s",
                group_index, list(ds.coords),
            )
            continue

        rename = {}
        if pressure_dim != "isobaricInhPa":
            rename[pressure_dim] = "isobaricInhPa"
        if "lat" in ds.coords and "latitude" not in ds.coords:
            rename["lat"] = "latitude"
        if "lon" in ds.coords and "longitude" not in ds.coords:
            rename["lon"] = "longitude"
        if rename:
            ds = ds.rename(rename)

        # Overwrite with normalized hPa values. The coordinate and dimension
        # now share the canonical name.
        ds = ds.assign_coords(
            isobaricInhPa=("isobaricInhPa", pressure_hpa)
        )

        if "latitude" not in ds.coords or "longitude" not in ds.coords:
            LOG.warning(
                "Skipping GRIB group %d: no latitude/longitude; coords=%s",
                group_index, list(ds.coords),
            )
            continue

        # Keep only the three fields needed for the atmospheric data.
        selected = {}
        for canonical, options in (
            ("height", ("gh", "hgt", "HGT", "z", "Geopotential_height")),
            ("u", ("u", "ugrd", "UGRD", "u_component_of_wind")),
            ("v", ("v", "vgrd", "VGRD", "v_component_of_wind")),
        ):
            found = next((name for name in options if name in ds.data_vars), None)
            if found is not None:
                selected[canonical] = ds[found]

        if set(selected) != {"height", "u", "v"}:
            continue

        part = xr.Dataset(selected).sortby("isobaricInhPa")
        candidates.append(part)

        LOG.info(
            "Accepted GRIB group %d: pressure %.4g–%.4g hPa, %d levels",
            group_index,
            float(np.min(pressure_hpa)),
            float(np.max(pressure_hpa)),
            len(pressure_hpa),
        )

    if not candidates:
        details = [
            f"group {i}: dims={dict(ds.sizes)}, coords={list(ds.coords)}, "
            f"vars={list(ds.data_vars)}"
            for i, ds in enumerate(groups)
        ]
        raise ValueError(
            f"No suitable pressure-level groups found in {grib_path}.\n"
            + "\n".join(details)
        )

    # Concatenate groups with distinct pressure ranges (e.g. Pa and hPa groups).
    if len(candidates) == 1:
        merged = candidates[0]
    else:
        merged = xr.concat(
            candidates,
            dim="isobaricInhPa",
            data_vars="all",
            coords="minimal",
            compat="override",
            join="exact",
        )
        merged = merged.sortby("isobaricInhPa")

        # Remove duplicate pressure levels if any groups overlap.
        pressure_values = np.asarray(merged["isobaricInhPa"].values)
        _, unique_indices = np.unique(pressure_values, return_index=True)
        if len(unique_indices) != len(pressure_values):
            merged = merged.isel(
                isobaricInhPa=np.sort(unique_indices)
            )

    return _normalise_coords(merged)


def _select_fields(ds: xr.Dataset) -> tuple[xr.DataArray, xr.DataArray, xr.DataArray]:
    h_name = _find_var(ds, ("height", "gh", "hgt", "HGT", "z", "Geopotential_height"))
    u_name = _find_var(ds, ("u", "ugrd", "UGRD", "u_component_of_wind"))
    v_name = _find_var(ds, ("v", "vgrd", "VGRD", "v_component_of_wind"))

    height = ds[h_name]
    # Convert only if the data are geopotential (m^2/s^2), not geopotential
    # height. GFS "gh" is normally geopotential height already, often in metres.
    units = str(height.attrs.get("units", "")).lower().replace(" ", "")
    if units in {"m**2s**-2", "m2s-2", "m^2/s^2", "m2/s2"}:
        height = height / 9.80665

    return height, ds[u_name], ds[v_name]


def _interpolate_pressure(
    field: xr.DataArray, target_pressure_hpa: np.ndarray
) -> np.ndarray:
    """
    Interpolate a field to target pressure levels in log-pressure coordinates.
    Returns float32 [pressure, latitude, longitude].
    """
    if "isobaricInhPa" not in field.dims:
        raise ValueError(
            f"Field {field.name!r} has no isobaricInhPa dimension: {field.dims}"
        )

    source_p = np.asarray(field["isobaricInhPa"].values, dtype=np.float64)
    if np.any(source_p <= 0):
        raise ValueError("Pressure levels must be positive for log-pressure interpolation")

    # xarray's interp accepts target values in the coordinate's transformed units.
    log_source = np.log(source_p)
    target_log = np.log(target_pressure_hpa)
    work = field.assign_coords(log_pressure=("isobaricInhPa", log_source))
    work = work.swap_dims({"isobaricInhPa": "log_pressure"})
    work = work.drop_vars("isobaricInhPa", errors="ignore")
    work = work.sortby("log_pressure")

    if target_log.min() < float(work.log_pressure.min()) - 1e-8 or \
       target_log.max() > float(work.log_pressure.max()) + 1e-8:
        raise ValueError(
            "Target pressure levels exceed source pressure range; refusing to extrapolate."
        )

    result = work.interp(log_pressure=target_log)
    arr = np.asarray(result.values, dtype=np.float32)
    if arr.ndim != 3:
        raise ValueError(
            f"Expected [pressure, latitude, longitude] after interpolation, got {arr.shape}"
        )
    return arr


def _to_half_degree(
    arr: np.ndarray, latitude: np.ndarray, longitude: np.ndarray
) -> np.ndarray:
    """
    Put [pressure, latitude, longitude] data onto the global 0.5-degree grid.
    Sort coordinates before selection so the output has consistent orientation.
    """
    lat_order = np.argsort(latitude)
    lon_order = np.argsort(longitude)
    arr = arr[:, lat_order, :][:, :, lon_order]
    lat_sorted = np.asarray(latitude)[lat_order]
    lon_sorted = np.asarray(longitude)[lon_order]

    # GFS 0.25-degree grid points should include exact 0.5-degree coordinates.
    lat_idx = np.rint((LATITUDES - lat_sorted[0]) / 0.25).astype(int)
    lon_idx = np.rint((LONGITUDES - lon_sorted[0]) / 0.25).astype(int)

    if (
        lat_idx.min() < 0
        or lat_idx.max() >= len(lat_sorted)
        or lon_idx.min() < 0
        or lon_idx.max() >= len(lon_sorted)
    ):
        raise ValueError("GFS grid does not cover the expected global 0.5-degree grid")

    selected_lat = lat_sorted[lat_idx]
    selected_lon = lon_sorted[lon_idx]
    if not np.allclose(selected_lat, LATITUDES, atol=1e-3):
        raise ValueError("Latitude selection did not produce the expected 0.5-degree grid")
    if not np.allclose(selected_lon, LONGITUDES, atol=1e-3):
        raise ValueError("Longitude selection did not produce the expected 0.5-degree grid")

    return arr[:, lat_idx, :][:, :, lon_idx]


def download_forecast(
    cycle: datetime,
    lead: int,
    cache_dir: Path,
    retries: int = 5,
) -> Path:
    """
    Download the required GFS fields. Prefer AWS first because NOMADS inventory
    requests can intermittently time out; retry both sources if necessary.
    """
    # Herbie versions differ in how source priorities are handled, so try an
    # AWS-first list first and then fall back to a NOMADS-first list.
    priority_options = (
        ["aws", "nomads"],
        ["nomads", "aws"],
    )
    last_error: Optional[BaseException] = None

    for priority in priority_options:
        for attempt in range(retries):
            try:
                # Herbie expects a naive datetime for many versions.
                h = Herbie(
                    cycle.replace(tzinfo=None),
                    model="gfs",
                    product="pgrb2.0p25",
                    fxx=lead,
                    save_dir=str(cache_dir),
                    priority=priority,
                )
                path = h.download(search=r":(?:HGT|UGRD|VGRD):")
                if path:
                    candidate = Path(path)
                    if candidate.exists() and candidate.stat().st_size > 0:
                        return candidate
                raise RuntimeError("Herbie did not return a valid GRIB file path.")
            except (
                requests.exceptions.RequestException,
                TimeoutError,
                OSError,
                RuntimeError,
                ValueError,
            ) as exc:
                last_error = exc
                wait = min(5 * (attempt + 1), 30)
                LOG.warning(
                    "Download failed for f%03d (source priority %s, attempt %d/%d): %s",
                    lead, priority, attempt + 1, retries, exc,
                )
                if attempt < retries - 1:
                    LOG.info("Retrying in %d seconds...", wait)
                    time.sleep(wait)

    raise RuntimeError(
        f"Could not download GFS f{lead:03d} after retries. Last error: {last_error}"
    )


def read_forecast(
    cycle: datetime, lead: int, cache_dir: Path
) -> np.ndarray:
    """Return one source forecast as float32 [pressure, variable, lat, lon]."""
    LOG.info("Reading GFS f%03d ...", lead)
    grib_path = download_forecast(cycle, lead, cache_dir)
    LOG.info("Using GRIB: %s", grib_path)

    ds = _open_grib(grib_path)
    try:
        height, u, v = _select_fields(ds)
        source_pressure = np.asarray(ds["isobaricInhPa"].values, dtype=np.float64)
        LOG.info("Source pressure levels: %s", sorted(source_pressure.tolist()))

        latitude = np.asarray(ds["latitude"].values, dtype=np.float64)
        longitude = np.asarray(ds["longitude"].values, dtype=np.float64)

        fields = []
        for field in (height, u, v):
            # Interpolate pressure first, then put onto a consistent 0.5-degree grid.
            pressure_data = _interpolate_pressure(field, PRESSURES_HPA)
            pressure_data = _to_half_degree(pressure_data, latitude, longitude)
            fields.append(pressure_data)

        output = np.stack(fields, axis=1)  # [pressure, variable, latitude, longitude]
        if output.shape != (N_PRESSURES, N_VARIABLES, N_LAT, N_LON):
            raise ValueError(f"Unexpected source output shape: {output.shape}")
        return output.astype(np.float32, copy=False)
    finally:
        ds.close()
        gc.collect()


def write_dataset(
    cycle: datetime,
    output_root: Path,
    cache_dir: Path,
    overwrite: bool = False,
) -> Path:
    """Download forecast fields and write the binary file."""
    # Tawhiri Dataset.filename expects the binary named YYYYMMDDHH directly
    # inside the dataset directory, without a file extension or nested folder.
    output_root.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)

    dataset_name = cycle.strftime("%Y%m%d%H")
    output_file = output_root / dataset_name
    metadata_file = output_root / f"{dataset_name}.metadata.txt"

    if output_file.exists() and not overwrite:
        if output_file.stat().st_size == OUTPUT_BYTES:
            LOG.info("Output already exists with expected size: %s", output_file)
            return output_file
        raise FileExistsError(
            f"{output_file} already exists but has size {output_file.stat().st_size:,}; "
            "use --overwrite to replace it."
        )

    LOG.info("Cycle: %s", cycle.strftime("%Y-%m-%d %H:%M UTC"))
    LOG.info("Output: %s", output_file)
    LOG.info("Output shape: %s", OUTPUT_SHAPE)
    LOG.info("Expected output size: %s bytes (%.2f GiB)",
             f"{OUTPUT_BYTES:,}", OUTPUT_BYTES / (1024**3))

    if output_file.exists() and overwrite:
        output_file.unlink()

    # Temporary .partial file protects against mistaking an incomplete output
    # for a completed dataset if a download fails midway.
    partial_file = output_root / f"{dataset_name}.partial"
    if partial_file.exists():
        partial_file.unlink()

    mm = np.memmap(
        partial_file,
        dtype=np.float32,
        mode="w+",
        shape=OUTPUT_SHAPE,
        order="C",
    )

    source_cache: dict[int, np.ndarray] = {}
    try:
        for output_index, target_hour in enumerate(OUTPUT_HOURS):
            if target_hour in SOURCE_HOURS:
                if target_hour not in source_cache:
                    source_cache[target_hour] = read_forecast(
                        cycle, target_hour, cache_dir
                    )
                mm[output_index] = source_cache[target_hour]
            else:
                lower = max(hour for hour in SOURCE_HOURS if hour < target_hour)
                upper = min(hour for hour in SOURCE_HOURS if hour > target_hour)
                if lower not in source_cache:
                    source_cache[lower] = read_forecast(cycle, lower, cache_dir)
                if upper not in source_cache:
                    source_cache[upper] = read_forecast(cycle, upper, cache_dir)

                fraction = (target_hour - lower) / (upper - lower)
                mm[output_index] = (
                    source_cache[lower] * (1.0 - fraction)
                    + source_cache[upper] * fraction
                )
                LOG.info(
                    "Interpolated f%03d between f%03d and f%03d",
                    target_hour, lower, upper,
                )

            mm.flush()
            LOG.info("Completed output time %d/%d (f%03d)",
                     output_index + 1, N_TIMES, target_hour)

            # Retain only nearby source fields to limit RAM use.
            keep = set()
            if target_hour in SOURCE_HOURS:
                keep.add(target_hour)
            if target_hour not in SOURCE_HOURS:
                keep.update((lower, upper))
            for key in list(source_cache):
                if key not in keep:
                    del source_cache[key]
            gc.collect()

        del mm
        partial_file.replace(output_file)

        metadata = [
            "Format: float32 little-endian C-order binary",
            "Layout: [time, pressure, variable, latitude, longitude]",
            f"Shape: {OUTPUT_SHAPE}",
            f"Cycle UTC: {cycle.strftime('%Y-%m-%d %H:%M')}",
            f"Forecast hours: {OUTPUT_HOURS}",
            f"Pressure levels hPa: {PRESSURES_HPA.tolist()}",
            "Variable order: geopotential_height_m, u_wind_m_s, v_wind_m_s",
            f"Latitude axis: {LATITUDES[0]} to {LATITUDES[-1]} by 0.5 degrees, ascending",
            f"Longitude axis: {LONGITUDES[0]} to {LONGITUDES[-1]} by 0.5 degrees",
            f"Expected binary bytes: {OUTPUT_BYTES}",
            "Pressure axis matches Tawhiri Dataset.axes.pressure; confirm your installed version.",
        ]
        metadata_file.write_text("\n".join(metadata) + "\n", encoding="utf-8")

        actual_size = output_file.stat().st_size
        if actual_size != OUTPUT_BYTES:
            raise RuntimeError(
                f"Output size mismatch: expected {OUTPUT_BYTES:,}, got {actual_size:,}"
            )

        LOG.info("Finished: %s (%s bytes)", output_file, f"{actual_size:,}")
        LOG.info("Metadata: %s", metadata_file)
        return output_file

    except Exception:
        try:
            del mm
        except UnboundLocalError:
            pass
        LOG.exception("Processing failed. Partial output retained at %s", partial_file)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download GFS pressure-level forecasts and create a Tawhiri-style binary dataset."
    )
    parser.add_argument(
        "--cycle",
        required=True,
        type=parse_cycle,
        help="GFS initialization cycle in UTC, YYYYMMDDHH (e.g. 2026102800)",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("data/tawhiri-data"),
        help="Directory in which the cycle-named output folder is created.",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path("data/tawhiri-grib"),
        help="Directory for downloaded GRIB files.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace an existing output file.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%H:%M:%S",
    )

    try:
        result = write_dataset(
            cycle=args.cycle,
            output_root=args.output_root,
            cache_dir=args.cache_dir,
            overwrite=args.overwrite,
        )
        print(f"\nSUCCESS: {result}")
    except Exception as exc:
        print(f"\nFAILED: {exc}")
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
