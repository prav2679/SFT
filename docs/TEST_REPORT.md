# Integration test report (build environment, 2 Nov 2026)

Environment: Ubuntu 24, Python 3.12. The preserved engine's Cython extensions were compiled in a
scratch copy (the shipped engine tree is untouched). A **synthetic test dataset** of the exact
4-variable size (sparse file; ISA geopotential heights and temperatures, constant winds 5–7.4 m/s
east, 2 m/s north, hours 0–24) was used. It is a test fixture, not forecast data; numbers below
verify integration, not physical accuracy.

## Model workers via the API (all COMPLETED)
| Test | Result |
|---|---|
| Burst calculator (V4 baseline parameters) | 3,776 points, burst at 4,770.25 s / 32,000 m — identical count/timing to the recorded V4 output |
| Forward hold mission (25 km, 2 h hold) | 703 points, ascent → hold → landing |
| Reverse (target 13.08 N 80.27 E, 09:00Z) | candidate launch 12.902 N 79.745 E 06:15Z; forward-validated landing error 320 m |
| Diurnal Stage 5 (8 h float, compliant) | 565 records; float 26,971–26,989 m; ΔP −255…864 Pa; interpretations generated |
| Live re-forecast (LiveTrajectoryManager) | complete_to_landing |
| Missing weather data | 409 WEATHER_DATA_UNAVAILABLE before any model starts |
| Missing engine dependency | reported as TAWHIRI_ENGINE_UNAVAILABLE with root cause |

## Tawhiri engine (original api.py, Flask; test-only elevation stub for Ruaumoko)
| Comparison | Result |
|---|---|
| Burst flight vs standard_profile | landing difference 2.86 km; flight-time difference 486 s (descent models differ); max ascent separation 90 m |
| Hold mission vs float_profile | end-of-hold difference 207 m |
| Reverse vs reverse_profile | launch estimates 41 m apart; launch-time quirk corrected |

## Downloader orchestration
Original `main.exe` invoked with documented arguments; failure (missing libeccodes in the build
sandbox) reported as a DOWNLOADER failure with log tail; valid existing cycle → SKIPPED (no repeat
download); invalid 03Z cycle rejected.

## Telemetry & simulation (automated: backend/tests/test_api.py — 5 passed)
Duplicate, future-timestamp and mixed-source packets rejected; K→°C conversion; invalid coordinates
stored as INVALID and never live; battery CRITICAL alert; simulation reaches DESCENT; injected altitude
deviation raises an alert and appears in prediction-vs-actual statistics; no false rapid-loss alert at
a latex burst.

## Frontend
Production build clean; headless-browser screenshots of all three workspaces with no JavaScript errors.
Map tiles were not loadable offline in the sandbox (expected).

## Not tested here
Real GFS download, real forecast data, real Ruaumoko elevation dataset, real hardware telemetry,
multi-day 72 h diurnal run on real data. Run these on the WSL environment before operational use.
