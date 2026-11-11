# SPB Diurnal Model – Clean Backend Package

This folder contains the retained Stage 5 diurnal model code for integration
into the SFT frontend/backend application.

## Retained files

| File | Keep/use | Purpose |
|---|---|---|
| `spb_stage5_model.py` | Required | Main thermal, envelope, buoyancy, vertical and horizontal simulation logic. Exposes `Balloon`, `Mission`, `run_simulation()` and `make_tawhiri_provider()`. |
| `tawhiri_spb_adapter.py` | Required | Connects the model to the temperature-enabled Tawhiri CUSF binary dataset and returns U/V/T/P. |
| `spb_parameters.py` | Reference | Spreadsheet-derived baseline parameters and validation warnings. It is not currently imported automatically by Stage 5. |
| `run_spb_stage5.py` | Optional CLI | Local command-line runner for validating the model. |
| `plot_spb_stage5.py` | Optional CLI | Creates diagnostic plots from a simulation CSV. |
| `tests/test_stage5_model.py` | Recommended | Small unit tests that do not require the Tawhiri engine. |

## Removed from this cleaned package

- Stage 1 / Stage 2 / Stage 3 / Stage 4 duplicate model implementations.
- Old fixed-altitude thermal runner and model.
- Earlier ground-to-float model and runner superseded by Stage 5.
- Legacy balloon physics reference file.
- Previous run CSVs, sensitivity CSVs, PNG plots and nested results ZIP.
- `__pycache__`, `.pyc` files and Windows `Zone.Identifier` metadata.

The original uploaded ZIP is not modified; this is a separate cleaned copy.

## Runtime dependencies

The model and adapter use Python standard-library modules. The plotter requires
Matplotlib. The Tawhiri adapter requires the modified temperature-enabled
Tawhiri engine built from the project source and its compiled Cython extensions.

`requirements.txt` contains only the Python plotting dependency. Do not install
a different Tawhiri package from PyPI as a replacement for your modified engine.

## Existing project assumptions

- Python 3.10 virtual environment: `../.venv310`
- Tawhiri data directory default: `../tawhiri-data`
- Default forecast cycle: `2026103100`
- CUSF dataset variables: height, U wind, V wind, TMP (Kelvin)
- The modified Tawhiri engine must be importable in the same Python environment.

## Run from this folder

```bash
source ../.venv310/bin/activate
python run_spb_stage5.py
```

Rigid-envelope comparison:

```bash
python run_spb_stage5.py --envelope-mode rigid \
  --output outputs/spb_stage5_rigid_72h.csv
```

Compliant-envelope baseline:

```bash
python run_spb_stage5.py --envelope-mode compliant \
  --output outputs/spb_stage5_compliant_72h.csv
```

Create plots:

```bash
python plot_spb_stage5.py outputs/spb_stage5_72h.csv
```

Run local unit tests:

```bash
python -m unittest discover -s tests -v
```

## Frontend integration contract

For a backend API, import the model functions directly rather than launching
the CLI as a subprocess:

```python
from spb_stage5_model import Balloon, Mission, run_simulation
from tawhiri_spb_adapter import TawhiriAtmosphere

mission = Mission(
    forecast_cycle="2026103100",
    dataset_dir="../tawhiri-data",
    # Override launch time, coordinates, duration and timestep here.
)
balloon = Balloon(
    envelope_mode="compliant",
    # Override physical inputs from the frontend here.
)

provider = TawhiriAtmosphere(
    cycle=mission.forecast_cycle,
    dataset_dir=mission.dataset_dir,
)
try:
    rows = run_simulation(
        provider, balloon, mission,
        output_csv="outputs/mission_<id>.csv",
    )
finally:
    provider.close()
```

For a web service, run simulations in a background worker/job rather than
blocking a web request. The model currently writes a CSV and returns a list of
row dictionaries. The frontend should receive a mission/job ID and query
progress/results through your backend API. The model does not yet implement
streaming progress updates or a REST API.

## Important model limitations

- Stage 5 is an engineering prototype, not flight-qualified.
- Ascent is prescribed at 5.4 m/s; force-based vertical dynamics apply during
  float.
- The atmosphere is sampled from Tawhiri at the outer timestep. Inner-step
  pressure/density uses a hydrostatic correction at the sampled temperature,
  not a fresh Tawhiri vertical interpolation on every inner step.
- The compliant pressure-volume law is provisional. The rigid mode is an
  idealized comparison. Neither replaces the actual manufacturer pressure-
  volume curve.
- Thermal coefficients, PXO3 material properties and drag coefficient are
  not manufacturer-validated.
- The nominal 1500 Pa pressure limit is not a certified structural safety limit.
- The Stage 5 timestep convergence and rigid/compliant comparison were tested
  in the user's prior runs; re-run after any physics/code changes.
