# SFT backend and live telemetry cleanup review

## Scope
This is a cleaned working copy of the uploaded `codes.zip`. The original archive was not modified.
The cleanup removes only generated Windows Zone.Identifier metadata and Python bytecode caches,
removes one byte-for-byte duplicate manager copy from the active tree, and relocates non-source
trajectory outputs out of the Python source directory. Historical/uncertain code is retained under
`archive/legacy/` rather than deleted.

## Active Python modules retained
- `codes/parameter_validation.py`
- `codes/balloon_physics.py`
- `codes/ascent_model_time_dependent.py`
- `codes/descent_physics.py`
- `codes/descent_model_time_dependent.py`
- `codes/wind_model_time_dependent.py`
- `codes/cusf_wind.py`
- `codes/flight_model_paramaterized.py`
- `codes/live_trajectory_manager.py`
- `codes/compare_sondehub.py`
- `codes/processgfs.py`
- `codes/process_existing_cfs.py`
- `codes/download_gfs_time_series.py`
- `codes/gfs_cusf_full.py`
- `codes/plot_model.py`
- `codes/gui.py`

## Live telemetry
- Kept `live_trajectory/test_live_simulation.py` and `test_live_simulation_v3.py`.
- Kept `live_trajectory/results/` and `live_trajectory/v3_validation/`.
- `live_trajectory/live_trajectory_manager_v2.py` was byte-for-byte identical to
  `codes/live_trajectory_manager.py`; the duplicate copy was omitted from the active tree.
- The separate `live_controller.py` was retained as `archive/legacy/live_controller_v1.py`
  pending confirmation that no external launcher imports it.

## Relocated outputs
The two complete-flight outputs accidentally stored under `codes/` with an embedded Windows
absolute-path filename were copied to `artifacts/imported_outputs/` with normal filenames.
They are data artifacts, not Python modules.

## Retained for review, not assumed obsolete
- `archive/legacy/ascent_model_time_dependent.py.pre_live_backup`
- `archive/legacy/live_controller_v1.py`
- GFS/CFS and GRIB/NetCDF utilities remain in `codes/`; their role should be confirmed against
  the actual deployment workflow before removing them.

## Checks performed
- 18 active/legacy Python source files parsed successfully with Python AST syntax parsing.
- The two live trajectory manager files were confirmed byte-for-byte identical.
- No runtime/integration tests were executed as part of this file-structure pass.
- Tawhiri package availability, forecast dataset availability, GRIB dependencies, API imports,
  and GUI startup still need environment-level verification.

## Before deployment
1. Confirm the actual app entrypoint and import paths.
2. Search the full repository for imports of `live_controller` and any legacy script.
3. Verify GFS/CFS utilities are not required by a separate data-preparation workflow.
4. Replace hard-coded Windows output paths with configuration only after confirming the
   frontend/backend output contract.
5. Run the V4 regression checks and a local end-to-end flight simulation from this cleaned copy.
