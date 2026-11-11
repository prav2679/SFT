# Stage 1 — Architecture assessment of the supplied SFT codebase

Inspected 1 Nov 2026 from seven uploads. No original file was modified (see ORIGINALS_SHA256.txt;
only Windows `Zone.Identifier` streams, `__pycache__` and intermediate Dune `_build` objects were
left out — `_build/default/main.exe` is kept at its original path).

## 1. Supplied structure
| Upload | Content |
|---|---|
| balloon_burst_with_live_telemetry.zip | `codes/` burst calculator (ascent/descent/balloon/parachute physics, Tawhiri wind adapter, `flight_model_paramaterized.run_flight`, `live_trajectory_manager.py`, Tkinter `gui.py`, GFS/CFS utilities), `live_trajectory/` V3 validation, `artifacts/` recorded complete-flight CSV/KML, `archive/legacy/` |
| SFT_forward_reverse_CUSF.zip | `simulation/flight_forward.py` (ascent → hold → descent), `flight_backtrack.py` (landing-target reverse + forward validation), own ascent/descent/wind modules; `legacy_netcdf/` |
| spb_diurnal_tawhiri_integration_clean.zip | Stage 5 SPB diurnal model (`spb_stage5_model.py`), `tawhiri_spb_adapter.py` (TMP-enabled), parameters, CLI, tests |
| tawhiri-data.zip | `tawhiri-downloader/` (OCaml/Dune, built `main.exe`, temperature extension), `tawhiri-engine/tawhiri-master/` (Flask API + Cython, cpython-310 builds), empty data dir |
| leaflet_predictor-master.zip **and** frontend.zip | **Byte-identical** (same MD5): CUSF jQuery/Leaflet predictor with a local Tawhiri proxy |
| Development history (.docx) | Project record through V4 validation |

## 2. Frontend
No React/Vite frontend existed: “frontend.zip” is the jQuery Leaflet predictor. It was preserved
unchanged (served at `/legacy-predictor/`) and its map icons are reused; a new React/Vite frontend
was created as the mission-control UI.

## 3. Backend / APIs / database
No HTTP API, task system or database existed. Interfaces were Python functions, CLIs and a Tkinter
GUI. The Tawhiri engine has its own Flask API (`/api/v1/`, `/api/datasetcheck`).

## 4–7. Model entry points (reused unchanged)
| Capability | File | Entry point |
|---|---|---|
| Burst calculator | codes/flight_model_paramaterized.py | `run_flight(parameters)` |
| Live re-forecast | codes/live_trajectory_manager.py | `LiveTrajectoryManager.update()` |
| Forward trajectory | simulation/flight_forward.py | `simulate_mission(...)`, `export_trajectory_kml` |
| Reverse trajectory | simulation/flight_backtrack.py | `backtrack_landing(...)` |
| Diurnal | spb_stage5_model.py + tawhiri_spb_adapter.py | `run_simulation(provider, Balloon, Mission)` |

## 8. Tawhiri Downloader
`tawhiri/tawhiri-downloader/_build/default/main.exe one -directory DIR -base-url nomads|aws-mirror
-log-level info YYYYMMDDHH` (also `daemon`). Writes `download-*` temp files, final file named
YYYYMMDDHH, 4-variable layout 12,704,889,600 bytes. Needs libeccodes at runtime.

## 9. Tawhiri Engine
Python/Cython package; `tawhiri-webapp runserver` serves `tawhiri.api:app` on :5000 with
`WIND_DATASET_DIR` from `TAWHIRI_SETTINGS`. The SFT models also import `tawhiri.dataset` /
`tawhiri.interpolate` directly. Compiled extensions are cpython-310.

## 10. Leaflet
Only the legacy predictor (jQuery, Leaflet 1.x, `js/pred/*.js`). Not componentised.

## 11. Telemetry
`LiveTrajectoryManager` (re-forecast from ascent telemetry) and V3 synthetic validation scripts.
No packet ingestion, transport, storage or alerting existed.

## 13–15. Reuse classification
* **Unchanged:** every file under backend/simulations, tawhiri/, legacy/.
* **Adapters (new):** backend/workers/* (call original functions; redirect the burst model's
  hard-coded Windows output paths at runtime), core/tawhiri_engine.py, core/tawhiri_downloader.py.
* **New:** FastAPI app, SQLite store, telemetry gateway, simulator, comparison, React frontend.

## 16. Integration conflicts found
1. **Module-name collision:** the burst package and the forward/reverse package both contain
   `ascent_model_time_dependent.py`, `descent_model_time_dependent.py`, `wind_model_time_dependent.py`,
   `descent_physics.py` with different contents → each model runs in its own worker process.
2. **Different ascent models:** forward/reverse ascent has `hold_duration_hours` (no burst); the burst
   ascent has `burst_altitude`/`start_time_s`. Kept as separate mission modes (as the forward/reverse README recommends).
3. **Atmosphere source differs:** burst & forward/reverse adapters use ISA T/P/ρ (winds from Tawhiri);
   diurnal uses Tawhiri TMP. Displayed as MODEL ESTIMATE vs FORECAST respectively.
4. **Lead-time bound differs:** forward/reverse adapter `< 192 h`; burst adapter `<= 192 h`; diurnal `<= 192`.
   The native interpolator is exclusive at 192 h (V4 Stage 6); the backend enforces `< 192 h` up front.
5. **Hard-coded Windows output paths** in `flight_model_paramaterized.py` → redirected per job at runtime.
6. **Tawhiri `fromtimestamp()`** uses server local time for dataset selection → run engine with TZ=UTC.
7. **Tawhiri reverse_profile** echoes the request time as `launch_estimate.datetime`; adapter reports the
   backtracked end time and keeps the original as `engine_reported_datetime`.
8. **Tawhiri reverse ≠ SFT reverse:** Tawhiri estimates a launch site from an ascending state; SFT solves
   landing-target problems. Comparison restricted to the ascent back-track.
9. **Singleton wind dataset:** model modules cache an opened cycle; per-job worker processes avoid the
   stale-singleton issue recorded in V4 Stage 6.
10. **Engine dependency** `magicmemoryview` (+ Flask, strict_rfc3339, ruaumoko for the HTTP API) must be
    present in the engine venv.
11. **Official logo** could not be downloaded from the build environment → placeholder + fetch script.
