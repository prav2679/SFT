# Change to the preserved scientific models (Revision 2)

Exactly one change was made to preserved model source. It is **additive, optional and behaviour-neutral by default**.

| File (identical in both packages) | Change |
|---|---|
| `backend/simulations/burst_calculator/codes/descent_model_time_dependent.py` | `simulate_descent(..., initial_vertical_velocity=0.0)` |
| `backend/simulations/trajectory_forward_reverse/simulation/descent_model_time_dependent.py` | same |

* The original code hard-coded `vertical_velocity = 0.0` at the start of the descent loop (parachute deploys from rest).
  A descent re-forecast from *measured* mid-descent telemetry needs the observed downward speed as the initial state,
  and the model gave no way to supply it. The new keyword defaults to `0.0`, so every existing caller is unchanged.
* Validation: non-finite or negative values raise `ValueError`.
* Regression proof: `backend/tests/golden/descent_default_golden.json` was generated from the **untouched original** (313 points,
  both packages), and `tests/test_units.py` asserts the modified model reproduces it exactly with the argument omitted or `0.0`.
* `docs/ORIGINALS_SHA256.txt` was updated for these two files only (old hash `3989d292…d312`, new hash `c20dd549…efdbc`);
  `scripts/verify_originals.py` passes. No other preserved file changed.
* Not changed on purpose: standalone CLI/GUI/test scripts and the `Balloon` dataclass default inside preserved sources still contain
  13.0827 / 80.2707. None is on an application execution path: the API validates and the diurnal worker re-checks that coordinates
  were supplied and arrive unchanged (see `tests/test_static_guards.py`).
