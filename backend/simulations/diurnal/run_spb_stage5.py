"""Command-line runner for the Stage 5 diurnal SPB model."""
import argparse
from pathlib import Path

from spb_stage5_model import (
    Balloon, Mission, run_simulation, make_tawhiri_provider
)


def main():
    parser = argparse.ArgumentParser(
        description="Run the Stage 5 SPB diurnal trajectory model"
    )
    parser.add_argument("--output", default="outputs/spb_stage5_72h.csv")
    parser.add_argument("--h-internal", type=float, default=5.0)
    parser.add_argument(
        "--envelope-mode", choices=["compliant", "rigid"], default="compliant"
    )
    parser.add_argument("--outer-dt", type=float, default=30.0)
    parser.add_argument("--inner-dt", type=float, default=1.0)
    parser.add_argument("--cycle", default="2026103100")
    parser.add_argument("--dataset-dir", default="../tawhiri-data")
    args = parser.parse_args()

    mission = Mission(
        outer_timestep_s=args.outer_dt,
        inner_timestep_s=args.inner_dt,
        forecast_cycle=args.cycle,
        dataset_dir=args.dataset_dir,
    )
    balloon = Balloon(
        internal_heat_transfer_w_m2k=args.h_internal,
        envelope_mode=args.envelope_mode,
    )

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    provider = make_tawhiri_provider(mission)
    try:
        rows = run_simulation(provider, balloon, mission, str(output))
    finally:
        provider.close()

    float_rows = [row for row in rows if row["phase"] == "float"]
    if not float_rows:
        print("WARNING: no float records were produced.")
        return

    print(f"Envelope model: {args.envelope_mode}")
    print(f"Completed: {len(rows)} total records; {len(float_rows)} float records")
    print(f"Output: {output.resolve()}")
    print(
        f"Float altitude: {min(r['altitude_m'] for r in float_rows):.1f} to "
        f"{max(r['altitude_m'] for r in float_rows):.1f} m"
    )
    print(
        f"Float vertical speed: {min(r['vertical_speed_ms'] for r in float_rows):.4f} to "
        f"{max(r['vertical_speed_ms'] for r in float_rows):.4f} m/s"
    )
    print(
        "Maximum |dP|: "
        f"{max(abs(r['differential_pressure_pa']) for r in rows):.1f} Pa"
    )
    ratios = [r["buoyancy_to_weight_ratio"] for r in float_rows]
    print(
        f"Float buoyancy/weight ratio: {min(ratios):.4f} to {max(ratios):.4f}"
    )
    print("No artificial vertical-velocity clipping is applied.")


if __name__ == "__main__":
    main()
