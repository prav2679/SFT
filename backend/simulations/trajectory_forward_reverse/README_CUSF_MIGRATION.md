# SFT Forward / Reverse Trajectory — CUSF/Tawhiri wind backend

## What changed
- Replaced the old xarray/NetCDF-backed `simulation/wind_model_time_dependent.py`
  with the existing SFT CUSF/Tawhiri binary-backed wind adapter.
- Forward, reverse, ascent-hold and descent code continue to call the same
  `get_wind(latitude, longitude, altitude_m, simulation_time)` interface.
- Wind U/V now come from the native Tawhiri CUSF binary and Cython 4-D
  interpolator. Temperature, pressure and density are still ISA estimates
  supplied by the adapter because the CUSF wind binary contains height/U/V,
  not temperature/pressure.
- Enforced the known native upper boundary: forecast lead time must be
  less than 192 hours (the exact 192-hour endpoint is not supported).
- Old NetCDF downloader/converter scripts are retained under `legacy_netcdf/`
  for reference only; they are not part of the active CUSF execution path.

## Files
Active:
- `simulation/flight_forward.py`
- `simulation/flight_backtrack.py`
- `simulation/ascent_model_time_dependent.py`
- `simulation/descent_model_time_dependent.py`
- `simulation/descent_physics.py`
- `simulation/wind_model_time_dependent.py` (CUSF/Tawhiri adapter)

Archived:
- `legacy_netcdf/download.py`
- `legacy_netcdf/gribtonetcdf.py`

## Configure the runtime
Run inside the Python environment where the Tawhiri Python package and its
compiled Cython extensions are installed.

From the project root, set the directory containing the binary dataset file
named exactly `YYYYMMDDHH` and the selected cycle:

```bash
export TAWHIRI_DATA_DIR="$HOME/balloon-burst-tawhiri-integrated/tawhiri-data"
export TAWHIRI_CYCLE="2026103100"
```

Adjust the path and cycle to the dataset actually downloaded. Do not rename the
binary with a `.bin` extension.

## Run
From the `simulation/` directory:

```bash
python flight_forward.py
python flight_backtrack.py
```

All launch/target times are interpreted as UTC when entered without a timezone.

## Important model distinction
These files preserve the uploaded legacy mission logic:
- Forward: constant-rate ascent to a target altitude, idealised altitude hold,
  then parachute descent.
- Reverse: backtracks parachute descent, altitude hold and ascent, then
  forward-simulates the candidate to calculate landing position/time error.

This is a separate mission mode from the current SFT main flight model
(`ascent -> physical burst condition/target -> descent`). The old forward file
passes `hold_duration_hours` to its own legacy ascent-hold model; it is not
drop-in compatible with the current burst-oriented `codes/ascent_model_time_dependent.py`.
The two workflows should remain separately named until the product requirement
decides whether reverse targeting should reconstruct an altitude-hold mission
or a burst-and-descent mission.

## Validation status
- Python syntax compilation: checked for all active Python modules.
- NetCDF/xarray dependency: removed from the active forward/reverse wind path.
- End-to-end wind lookup and trajectory execution: not run here because this
  review package does not contain the live Tawhiri binary dataset/runtime.
- Before operational use, run one known-cycle wind lookup and a short forward
  and reverse test, then compare against the corresponding reference run.
