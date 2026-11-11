# Tawhiri temperature-enabled dataset extension

This source tree extends the CUSF Tawhiri downloader and engine to store and
interpolate GFS pressure-level temperature (`TMP`) in addition to the existing
geopotential height (`HGT`) and wind components (`UGRD`, `VGRD`).

## Binary dataset layout

The five-dimensional float32 dataset is now:

`[forecast_hour=65][pressure_level=47][variable=4][latitude=361][longitude=720]`

Variable axis order (must remain identical in downloader and engine):

| Index | Variable | GRIB index short name | GRIB2 parameter |
|---:|---|---|---|
| 0 | height | HGT | discipline 0, category 3, number 5 |
| 1 | wind_u | UGRD | discipline 0, category 2, number 2 |
| 2 | wind_v | VGRD | discipline 0, category 2, number 3 |
| 3 | temperature | TMP | discipline 0, category 0, number 0 |

The expected raw dataset size is **12,704,889,600 bytes** (about 12.70 GB
decimal / 11.83 GiB). The previous three-variable format is not compatible.

## Engine API

The original `tawhiri.interpolate.make_interpolator(dataset, warnings)` API
is preserved and continues to return `(u, v)`.

A new API is added:

```python
from tawhiri.interpolate import make_environment_interpolator

get_environment = make_environment_interpolator(dataset, warning_counts)
u, v, temperature_K, pressure_hPa = get_environment(
    forecast_hour, latitude_deg, longitude_deg_0_to_360, altitude_m
)
```

Temperature is interpolated from GFS TMP data (Kelvin). Pressure is calculated
by log-linear interpolation between the dataset's native pressure levels using
the same vertical interpolation weights as the atmospheric fields. The
returned pressure is in hPa (the native pressure axis is in mb, numerically
equivalent to hPa).

## Important compatibility warning

Do not open an old three-variable dataset with this engine. Its file size and
layout are different. Download a fresh dataset with the modified downloader
into a separate directory, then point the modified engine at that directory.
Keep the old dataset until the new download has completed and passed checks.

The downloader's existing index validation requires every configured variable
at every configured pressure level for each forecast hour. This extension
therefore assumes the selected GFS index exposes TMP at all 47 pressure levels
across the two pressure-level files. Verify this on the first live download.
If NOAA omits any TMP level in a forecast cycle, the downloader will report
"Messages missing from index"; do not weaken that validation without checking
the actual index contents.

## Build notes

Downloader (inside its directory, with the existing OCaml dependencies and
ecCodes development library installed):

```bash
dune build
```

Engine (inside `tawhiri-master`, in the intended Python virtual environment):

```bash
python -m pip install -U Cython
python setup.py build_ext --inplace
python -m pip install -e .
```

The Cython source `tawhiri/interpolate.pyx` and generated C source
`tawhiri/interpolate.c` are both included. When Cython is installed, setup.py
regenerates the C extension from the `.pyx` source.

## First-download validation

1. Use a new output directory, not the existing three-variable dataset folder.
2. Download one forecast cycle.
3. Confirm the raw file is exactly 12,704,889,600 bytes.
4. Open it with the modified engine and check that `make_interpolator` still
   returns two wind components.
5. Check `make_environment_interpolator` returns finite U, V, temperature and
   pressure values. Compare TMP against the source GRIB messages at a few
   pressure levels before relying on it for balloon burst calculations.
