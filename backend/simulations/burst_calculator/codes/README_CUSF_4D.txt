# CUSF/Tawhiri 4D interpolation integration

## Architecture

1. `gfs_cusf_full.py` downloads GFS pressure-level fields, converts them to the
   CUSF Tawhiri array shape and writes the preprocessed binary.
2. The final binary must be named exactly `YYYYMMDDHH` in the dataset directory.
   Example: `data/tawhiri-data/2026102800` (no `.bin` extension).
3. `cusf_wind.py` runs in the Python environment where Tawhiri's Cython
   extensions are compiled. It opens the binary using Tawhiri's memory-mapped
   `Dataset` and calls `tawhiri.interpolate.make_interpolator`, which performs
   Cython four-dimensional interpolation at runtime.

## Dataset axes

- Shape: `(65, 47, 3, 361, 720)`
- Order: `[time, pressure_level, variable, latitude, longitude]`
- Variables: `[height, wind_u, wind_v]`
- Time: 0, 3, ..., 192 hours since cycle
- Latitude: -90 to +90 in 0.5-degree increments
- Longitude: 0 to 359.5 in 0.5-degree increments
- Pressure axis: exact sorted union defined in Tawhiri's `Dataset` source.

## Important

The Cython interpolator uses the height field to find the pressure levels that
bracket a requested altitude, then interpolates U/V across time, latitude,
longitude and altitude. Do not replace runtime altitude handling with simple
linear interpolation in log-pressure.

The downloaded GFS product and output must still be validated against the exact
Tawhiri version before trusting predictions. The Cython extension must be built
in the Python environment used by `cusf_wind.py`.
