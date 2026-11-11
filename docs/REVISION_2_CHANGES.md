# SFT Balloon GNC Mission Control — Revision 2 (corrections & enhancements)

Improvement of the existing application; nothing was rebuilt. Scientific models are untouched except one additive optional
argument (see `MODEL_CHANGES.md`).

## 1. Modified files
Backend: `api/routes/{burst,diurnal,missions,telemetry}.py`, `api/schemas.py`, `core/{comparison,db,simulator,tasks,telemetry}.py`,
`workers/diurnal_worker.py`, `tests/test_api.py`, both `descent_model_time_dependent.py` (additive kwarg), `docs/ORIGINALS_SHA256.txt`.
Frontend: `index.html`, `package.json`(+lock), `vite.config.js`, `src/App.jsx`, `context/{AppContext,TelemetryContext}.jsx`,
`navigation/TopNavigation.jsx`, `components/Common/ui.jsx`, `components/Map/{MapLayers.jsx,MissionMap.jsx,mapStore.js}`,
`pages/BurstTelemetry/{BurstCalculator,BurstTelemetryPage,MissionOverview,PredictionComparison}.jsx`, `pages/Diurnal/DiurnalPage.jsx`,
`pages/Trajectory/TrajectoryPage.jsx`, `services/apiClient.js`, `styles/theme.css`; `frontend/dist` rebuilt.

## 2. New files
Backend: `core/{geo,predictions,reforecast,manual_telemetry,flight_view,lifecycle}.py`, `workers/telemetry_reforecast_worker.py`,
`tests/{conftest,helpers,test_coordinates,test_history,test_reforecast,test_units,test_static_guards}.py`,
`tests/support/{fake_tawhiri_wind.py,run_worker.py,python_fake_wind.sh,descent_golden.py}`, `tests/golden/descent_default_golden.json`.
Frontend: `pages/BurstTelemetry/{MissionHistory,TelemetryUpdate}.jsx`, `hooks/useJobWatch.js`, `utils/{coordinates,telemetryValidation}.js`,
`src/__tests__/{units.test.js,components.test.jsx}`, `public/assets/branding/{sft-logo.jpg,sft-logo-original.jpg,favicon-32/64/192.png}`.
Docs: `docs/MODEL_CHANGES.md`, this file.

## 3. Database migration (`PRAGMA user_version` 0 → 1, `core/db.py::MIGRATIONS`)
Applied once, atomically, on start-up; idempotent; existing rows kept.
* `missions.updated_at` (back-filled from `created_at`; touched on PATCH).
* `simulations.mission_id` + index (re-forecast jobs belong to a mission and are deleted with it).
* `prediction_sets`: `version`, `kind` (ORIGINAL / REVISED / ATTACHED), `parent_set`, `anchor_telemetry_id`, `anchor_timestamp`,
  `anchor_phase`. Back-fill: earliest set per mission → V1 ORIGINAL, later ones → ATTACHED V2…
* `telemetry`: `entry_method`, `superseded_by`, `corrects_telemetry_id`, `correction_reason`.
* Triggers: `predictions` and `prediction_sets` can never be UPDATEd, and only deleted together with their mission; telemetry observation
  columns can never be UPDATEd (only the `superseded_by` audit link). Table `_mission_deletion` is the delete-time allow-list.

## 4. API
New: `POST /api/telemetry/manual/{mission}`, `GET /api/telemetry/phase-preview/{mission}`, `GET /api/telemetry/versions/{mission}`,
`GET /api/telemetry/flight-view/{mission}?version=`, `DELETE /api/missions?scope=completed|all[&confirm=true]`.
Extended (same paths): `DELETE /api/missions/{id}` (transactional cascade, 409 `MISSION_ACTIVE`), `GET /api/missions` (+`lifecycle_status`,
`active`, `mission_type`, `last_updated`, `packet_count`, `prediction_versions`), `POST /api/missions` (launch lat/lon now required → 422),
`POST /api/missions/{id}/abort` (also stops a running simulation), `POST /api/telemetry/reforecast/{mission}` (phase-aware, stores a version;
legacy `telemetry`-override body still runs the old ascent-only job), `GET /api/telemetry/comparison/{mission}?prediction_set=` (default =
immutable original; geodesic errors), job status (+`mission_id`, `post_process`), `GET /api/burst/defaults` and `/api/diurnal/defaults`
(no coordinates), `POST /api/diurnal/run` (422 without initial lat/lon), simulation start (refuses a source launched >5 km from the mission).
Telemetry ingest now also rejects any second record with an existing timestamp (409, explicit correction workflow required) and flags
altitudes outside −500…60 000 m as `IMPOSSIBLE_ALTITUDE`/INVALID.

## 5. Re-forecast workflow
1. Operator submits telemetry (UI form or `POST /api/telemetry/manual`; hardware keeps using `/ingest`). Validation: timestamp, lat/lon ranges,
   altitude −500…60 000 m, |vz| limit, optional fields, phase vs vertical-velocity consistency, duplicates (409), out-of-order (stored,
   flagged, never live, never an anchor), future time for MEASURED missions.
2. Phase = automatic (vz/altitude rules, previewed live in the form) or manual override.
3. The record is stored immutably; mission phase updates; a background job starts (`reforecast` worker, own process, never blocks the UI).
4. Worker starts the **existing** models from the observed state — ASCENT/burst: `LiveTrajectoryManager`; ASCENT or FLOAT/hold:
   `flight_forward.simulate_mission` launched from the observed state; DESCENT: `simulate_descent` from observed altitude, position and downward
   speed. Descent telemetry never reaches an ascent model and vice-versa. Weather: the original prediction’s forecast cycle; if it does not cover
   the window the job fails with an explicit message (no silent substitution).
5. On completion the server stores a new REVISED version (V2, V3, …; parent = previous version, anchored to the telemetry record) and pushes
   `prediction_version` over the WebSocket. Re-submitting the same telemetry never duplicates a version. V1 is never touched.
6. Map: original (blue, dashed) · actual (green, solid) · revised (amber, dashed, begins at the anchor). Comparison panel: landing points,
   WGS-84 geodesic differences, remaining duration, landing time, displacement, error-vs-time chart.

## 6. Test results
* Backend `pytest`: **31 passed** (5 original — one adapted to the no-default-coordinates rule — plus 26 new).
* Frontend `vitest`: **12 passed**. `vite build` succeeds. `scripts/verify_originals.py`: passes.
* The new backend tests execute the **real SFT worker processes** (burst, forward, reverse, re-forecast) with a **synthetic wind adapter**
  (`tests/support/fake_tawhiri_wind.py`) standing in for the Tawhiri engine and the 12.7 GB dataset (a sparse file of the exact size stands in for a
  valid forecast cycle). They validate plumbing, phase handling and coordinate propagation — **not** forecast accuracy.

## 7. Status
**Implemented and validated (automated):** mission history API/UI logic (cascade delete, active protection, clear completed/all, other mission
intact, shared weather + calculator jobs untouched); manual telemetry validation, duplicate/out-of-order/correction rules; ascent, float and
descent re-forecasts from observed state with the real models; versions V1…Vn with DB-enforced immutability; geodesic maths (Vincenty reference
value 54 972.271 m); coordinate propagation for burst / forward / reverse with Chennai, Sydney and Reykjavik; migration of a pre-existing DB;
colour palette, legend definitions, dashed/solid styles, branding assets/aspect ratio, dialog flows (jsdom).

**Implemented but not fully validated:** all visual map behaviour (casing, 4.5 px lines, arrows, badge/pulse markers, legend toggles, satellite/street
contrast, logo legibility in light/dark) — no browser was available, so it is verified by build + DOM tests only, **please eyeball it**; the manual form
and comparison panel in a real browser; real Tawhiri-driven re-forecasts; WebSocket `prediction_version` refresh; diurnal run with user coordinates
(API validation tested; the worker needs the compiled Tawhiri adapter, not available here).

**Not implemented / not applicable:** login screen and sidebar (the app has neither — logo is in the top bar, each workspace header, the loading screen and
the favicon); re-forecast of super-pressure *thermal* state (the diurnal model is not re-initialised); a transparent-background logo (the supplied file is
an opaque black JPEG despite its `.png` name).

## 8. Limitations
* FLOAT is the existing idealised ascent→hold→descent model started 0.5 m below the observed altitude (model requires target > launch); needs a planned float
  end (taken from the original’s hold segment or entered).
* Measured vertical velocity is used as the constant ascent rate only when 0.5–15 m/s (otherwise the planned rate, with a warning).
* Models advance positions on a spherical Earth; reported errors are WGS-84 geodesic.
* LIVE missions in flight stay ACTIVE until LANDED/ABORTED — a lost-signal mission must be terminated manually before deletion.
* A simulation-mode mission can no longer replay the recorded Chennai run unless launched within 5 km of it.
* The UI says “SUSAN FUTURE TECHNOLOGY” as specified; the supplied artwork reads “Susan Future Technologies”.
* The favicon is an exact pixel crop of the emblem from the supplied file (the full logo is wide); swap `favicon-*.png` if a dedicated icon exists.

## 9. Run
```
# backend (serves the built UI on http://127.0.0.1:8000)
scripts/start_backend.sh            # or: cd backend && uvicorn main:app --host 127.0.0.1 --port 8000
# frontend dev server with hot reload (proxies /api and /ws to :8000)
scripts/start_frontend_dev.sh       # or: cd frontend && npm install && npm run dev     (build: npm run build)
# tests
cd backend && python -m pytest -q tests          # needs: pip install fastapi uvicorn httpx pydantic pytest numpy pillow
cd frontend && npm test
```
