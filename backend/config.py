"""Central configuration for the SFT Balloon GNC Mission Control backend.

Every path can be overridden with an environment variable so the original
Tawhiri downloader/engine locations (e.g. ~/projects/tawhiri-master,
~/projects/tawhiri-data) can be used without moving or rebuilding them.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND_DIR.parent


def _path(env: str, default: Path) -> Path:
    value = os.environ.get(env)
    return Path(value).expanduser().resolve() if value else default


# --- Preserved scientific model packages (unchanged originals) -------------
SIMULATIONS_DIR = BACKEND_DIR / "simulations"
BURST_CALCULATOR_DIR = SIMULATIONS_DIR / "burst_calculator"
BURST_CODES_DIR = BURST_CALCULATOR_DIR / "codes"
TRAJECTORY_DIR = SIMULATIONS_DIR / "trajectory_forward_reverse" / "simulation"
DIURNAL_DIR = SIMULATIONS_DIR / "diurnal"
RECORDED_MODEL_OUTPUT_CSV = (
    BURST_CALCULATOR_DIR / "artifacts" / "imported_outputs" / "complete_flight_trajectory.csv"
)

# --- Tawhiri (original OCaml/Dune downloader + Python/Cython engine) -------
TAWHIRI_ROOT = PROJECT_ROOT / "tawhiri"
TAWHIRI_DATA_DIR = _path("TAWHIRI_DATA_DIR", TAWHIRI_ROOT / "tawhiri-data")
TAWHIRI_ENGINE_DIR = _path("TAWHIRI_ENGINE_DIR", TAWHIRI_ROOT / "tawhiri-engine" / "tawhiri-master")
TAWHIRI_DOWNLOADER_DIR = _path("TAWHIRI_DOWNLOADER_DIR", TAWHIRI_ROOT / "tawhiri-downloader")
TAWHIRI_DOWNLOADER_EXE = _path(
    "TAWHIRI_DOWNLOADER_EXE", TAWHIRI_DOWNLOADER_DIR / "_build" / "default" / "main.exe"
)
TAWHIRI_DOWNLOADER_BASE_URL = os.environ.get("TAWHIRI_DOWNLOADER_BASE_URL", "nomads")  # nomads | aws-mirror
TAWHIRI_API_URL = os.environ.get("TAWHIRI_API_URL", "http://127.0.0.1:5000").rstrip("/")
TAWHIRI_API_TIMEOUT_S = float(os.environ.get("TAWHIRI_API_TIMEOUT_S", "300"))

# Dataset layout from tawhiri/dataset.py (temperature-enabled 4-variable build)
DATASET_SHAPE = (65, 47, 4, 361, 720)
DATASET_SIZE_BYTES = 4 * 65 * 47 * 4 * 361 * 720          # 12,704,889,600
LEGACY_3VAR_SIZE_BYTES = 4 * 65 * 47 * 3 * 361 * 720      # 9,528,667,200 (incompatible)
DATASET_MAX_LEAD_HOURS = 192.0                              # exclusive upper bound (V4 Stage 6)

# --- Model worker interpreter --------------------------------------------
# The models import the compiled Tawhiri Cython extensions. Point this at the
# Python 3.10 virtualenv where the modified engine is built (e.g. .venv310).
SFT_MODEL_PYTHON = os.environ.get("SFT_MODEL_PYTHON", sys.executable)
SIM_TIMEOUT_S = float(os.environ.get("SFT_SIM_TIMEOUT_S", "3600"))
MAX_CONCURRENT_SIMULATIONS = int(os.environ.get("SFT_MAX_CONCURRENT_SIMULATIONS", "2"))

# --- Storage ------------------------------------------------------------------
DATA_DIR = _path("SFT_DATA_DIR", BACKEND_DIR / "data")
DB_PATH = _path("SFT_DB_PATH", DATA_DIR / "sft_mission_control.db")
RESULTS_DIR = DATA_DIR / "simulation_results"
LOG_DIR = DATA_DIR / "logs"
EXPORT_DIR = BACKEND_DIR / "exports"
for _d in (DATA_DIR, RESULTS_DIR, LOG_DIR, EXPORT_DIR / "csv", EXPORT_DIR / "kml"):
    _d.mkdir(parents=True, exist_ok=True)

# --- Frontend -------------------------------------------------------------
FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"
LEGACY_PREDICTOR_DIR = PROJECT_ROOT / "legacy" / "leaflet_predictor"

# --- Telemetry defaults (configurable per mission) -----------------------
DEFAULT_TELEMETRY_INTERVAL_S = 10.0
APP_VERSION = "1.0.0"
