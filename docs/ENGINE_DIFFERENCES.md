# Custom SFT model vs Tawhiri engine

| Aspect | Custom SFT model | Tawhiri engine |
|---|---|---|
| Weather input | Tawhiri CUSF binary via `make_interpolator` (U/V) | Same binary via the engine's wind model |
| Atmosphere | ISA T/P/ρ in the burst & forward/reverse adapters; Tawhiri TMP in the diurnal model | Engine-internal density model for descent |
| Vertical motion | Constant ascent; parachute descent from drag physics (mass, diameter, Cd) | Constant ascent; sea-level descent rate scaled with density |
| Balloon physics | Burst model tracks gas-law volume/diameter (burst at commanded altitude); hold model idealised; diurnal has full thermal/envelope model | None (kinematic profiles) |
| Profiles | Burst flight (ascent→burst→descent); hold mission (ascent→hold→descent) | standard_profile; float_profile (no descent); reverse_profile |
| Time resolution | User steps (ascent 10–60 s, descent 1–10 s) | RK4, 60 s output |
| Forecast coverage | lead time 0 ≤ t < 192 h | same dataset, chosen by `dataset` parameter |
| Reverse | Landing target → launch (descent, hold, ascent back-tracked) + forward validation | Launch-site estimate from an ascending state |

## Comparisons performed by “Compare engines”
* Burst flight ↔ standard_profile — full flight, including landing point.
* Hold mission ↔ float_profile — ascent + hold only (Tawhiri float has no descent).
* Reverse ↔ reverse_profile seeded with the SFT forward-validation hold-start state — ascent back-track only.

Tawhiri output contains no winds, so the “wind data” view compares SFT-sampled wind speed with Tawhiri's
horizontal drift speed derived from consecutive output points, and labels it as such.
