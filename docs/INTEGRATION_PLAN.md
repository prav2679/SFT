# Stage 2 — Integration plan (as implemented)

## Principles
Adapters and API boundaries only; no physics in the frontend; no duplicated engines; every displayed
value classified MEASURED / SIMULATED / MODEL ESTIMATE / FORECAST / UNAVAILABLE.

## Backend components (new)
| File | Role |
|---|---|
| config.py | All paths via env vars (original Tawhiri locations usable in place) |
| core/db.py | SQLite: missions, telemetry, alerts, predictions, prediction_sets, simulations (UTC ISO timestamps, time indexes) |
| core/tasks.py | Async background jobs, request de-duplication/caching, progress, cancellation, timeout |
| core/weather.py | Dataset discovery, size validation, coverage window check (refuses incomplete/missing data) |
| core/tawhiri_engine.py | HTTP adapter to the original engine + conversion to shared trajectory format |
| core/tawhiri_downloader.py | Supervisor for the original OCaml downloader (logs, verification, no repeat downloads) |
| core/telemetry.py | Gateway: validation, units, duplicate/stale/out-of-order, quality, derived values, phase, alerts, WebSocket |
| core/comparison.py | Prediction storage; time-aligned comparison (no extrapolation) |
| core/simulator.py | Simulation-mode telemetry from SFT model output + test scenarios |
| workers/*.py | One isolated process per model run; call original functions |

## API (summary — full schema at /docs)
`/api/burst/run|{id}|results|export/{csv,kml}` · `/api/trajectory/forward|reverse|engines|{id}` (engine = sft/tawhiri/compare) ·
`/api/diurnal/run|defaults|{id}` · `/api/telemetry/ingest|latest|history|status|alerts|predictions|comparison|reforecast` ·
`/api/missions[...]` incl. `/simulation/start|pause|resume|stop` and `/predictions` · `/api/tawhiri/status|download|predict` ·
`/api/system/status` · `/ws/telemetry/{mission_id}`.

## Frontend (new)
React 18 + Vite, Leaflet (one shared instance, `components/Map/mapStore.js`), uPlot charts.
Top navigation with mission / weather / simulation status, UTC clock, settings, theme toggle.
All workspaces stay mounted so results and map layers persist when switching.

## Risks / open items
* Real hardware packet format is not yet defined — map it to `/api/telemetry/ingest` in the ground-station software.
* Battery thresholds are placeholders; configure per mission (Settings → Alert thresholds).
* Diurnal parameters are largely assumed (spb_parameters.py) — calibrate before operational use.
* No validated burst-probability, ballast or venting model exists; the UI states this explicitly.
* LiveTrajectoryManager V2 supports ASCENT telemetry only (original limitation, surfaced in UI).
* Real-world accuracy remains unvalidated (no SFT flight dataset), consistent with the V4 record.
