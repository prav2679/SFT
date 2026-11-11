"""Worker: SPB Stage 5 diurnal model.

Uses the ORIGINAL ``spb_stage5_model`` (Balloon, Mission, run_simulation) and
``tawhiri_spb_adapter.TawhiriAtmosphere`` exactly as documented in the
package README "Frontend integration contract". Post-processing below only
*summarises* the model's own output rows; it introduces no new physics.
"""
from __future__ import annotations

import dataclasses
import math
import os
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import BACKEND_DIR, as_utc, norm_lon, prepare_paths, run  # noqa: E402

MODEL_DIR = BACKEND_DIR / "simulations" / "diurnal"
MODEL_VERSION = "SPB Stage 5 diurnal model (engineering prototype)"


def main(job):
    req = job.request
    prepare_paths(MODEL_DIR)
    from spb_stage5_model import Balloon, Mission, run_simulation
    from tawhiri_spb_adapter import TawhiriAtmosphere

    b_fields = {f.name for f in dataclasses.fields(Balloon)}
    m_fields = {f.name for f in dataclasses.fields(Mission)}
    b_over = {k: v for k, v in req.get("balloon", {}).items() if k in b_fields and v is not None}
    m_over = {k: v for k, v in req.get("mission", {}).items() if k in m_fields and v is not None}
    if "launch_time_utc" in m_over:
        m_over["launch_time_utc"] = as_utc(m_over["launch_time_utc"])
    m_over["forecast_cycle"] = os.environ["TAWHIRI_CYCLE"]
    m_over["dataset_dir"] = os.environ["TAWHIRI_DATA_DIR"]
    for key in ("initial_latitude_deg", "initial_longitude_deg"):      # never fall back to the model's dataclass default
        if b_over.get(key) is None:
            raise ValueError(f"{key} is required (no default location is ever used)")
    balloon = Balloon(**b_over)
    mission = Mission(**m_over)
    if (balloon.initial_latitude_deg, balloon.initial_longitude_deg) != (float(b_over["initial_latitude_deg"]),
                                                                          float(b_over["initial_longitude_deg"])):
        raise RuntimeError("Initial coordinates were altered between the request and the model")

    total_s = ((mission.target_float_altitude_m - balloon.launch_elevation_m)
               / mission.prescribed_ascent_rate_ms + mission.float_duration_h * 3600)
    start = mission.launch_time_utc

    atmosphere = TawhiriAtmosphere(cycle=mission.forecast_cycle, dataset_dir=mission.dataset_dir)

    def provider(lat, lon, alt, when):           # pass-through progress wrapper
        value = atmosphere(lat, lon, alt, when)
        elapsed = (when - start).total_seconds()
        job.progress(elapsed / max(total_s, 1.0), f"T+{elapsed/3600:.1f} h, {alt:,.0f} m")
        return value

    try:
        rows = run_simulation(provider, balloon, mission, output_csv=str(job.dir / "diurnal_simulation.csv"))
    finally:
        atmosphere.close()

    for r in rows:
        r["longitude_deg"] = norm_lon(r["longitude_deg"])
        r["is_day"] = bool(r["solar_disc_fraction"] > 0.0)

    return {
        "model": "diurnal_stage5",
        "model_version": MODEL_VERSION,
        "forecast_cycle": mission.forecast_cycle,
        "atmosphere_source": "Tawhiri TMP + native pressure-level axis (FORECAST); no ISA fallback.",
        "balloon": dataclasses.asdict(balloon),
        "mission": {k: (v.isoformat() if hasattr(v, "isoformat") else v)
                    for k, v in dataclasses.asdict(mission).items()},
        "analysis": analyse(rows, balloon),
        "limitations": [
            "Stage 5 is an engineering prototype, not flight-qualified.",
            "Ascent is prescribed; force-based vertical dynamics apply during float only.",
            "Compliant pressure-volume law is provisional; rigid mode is idealised.",
            "Thermal coefficients and PXO3 properties are not manufacturer-validated.",
            f"{balloon.max_differential_pressure_pa:.0f} Pa limit is nominal, not a certified structural limit.",
        ],
        "files": {"csv": "diurnal_simulation.csv"},
        "rows": rows,
    }


def analyse(rows, balloon):
    """Summaries of the model output (no additional physics)."""
    events, segments = [], []
    prev = None
    for r in rows:
        if prev is not None and r["is_day"] != prev["is_day"]:
            events.append({"type": "SUNRISE" if r["is_day"] else "SUNSET", "time_utc": r["time_utc"],
                           "altitude_m": r["altitude_m"]})
        prev = r
    floats = [r for r in rows if r["phase"] == "float"]
    if not floats:
        return {"events": events, "segments": [], "interpretations": [
            {"level": "WARNING", "text": "No float records were produced; diurnal behaviour cannot be assessed."}]}

    # Split float records into contiguous day/night segments.
    cur = None
    for r in floats:
        if cur is None or cur["is_day"] != r["is_day"]:
            cur = {"is_day": r["is_day"], "rows": []}
            segments.append(cur)
        cur["rows"].append(r)

    seg_out = []
    for s in segments:
        rs = s["rows"]
        peak_sun = max(rs, key=lambda x: x["solar_elevation_deg"])
        peak_he = max(rs, key=lambda x: x["helium_temperature_k"])
        peak_alt = max(rs, key=lambda x: x["altitude_m"])
        out = {
            "period": "DAY" if s["is_day"] else "NIGHT",
            "start_utc": rs[0]["time_utc"], "end_utc": rs[-1]["time_utc"],
            "altitude_min_m": min(x["altitude_m"] for x in rs),
            "altitude_max_m": max(x["altitude_m"] for x in rs),
            "altitude_mean_m": statistics.fmean(x["altitude_m"] for x in rs),
            "helium_temp_max_k": peak_he["helium_temperature_k"],
            "helium_temp_min_k": min(x["helium_temperature_k"] for x in rs),
            "superheat_mean_k": statistics.fmean(x["helium_temperature_k"] - x["air_temperature_k"] for x in rs),
            "dp_max_pa": max(x["differential_pressure_pa"] for x in rs),
            "dp_min_pa": min(x["differential_pressure_pa"] for x in rs),
            "vertical_speed_std_ms": statistics.pstdev(x["vertical_speed_ms"] for x in rs) if len(rs) > 1 else 0.0,
        }
        if s["is_day"] and len(rs) > 10:
            t0 = as_utc(peak_sun["time_utc"])
            out["thermal_lag_helium_min"] = (as_utc(peak_he["time_utc"]) - t0).total_seconds() / 60
            out["thermal_lag_altitude_min"] = (as_utc(peak_alt["time_utc"]) - t0).total_seconds() / 60
        seg_out.append(out)

    dp_all = [r["differential_pressure_pa"] for r in rows]
    dp_max, dp_min = max(dp_all), min(dp_all)
    alt_f = [r["altitude_m"] for r in floats]
    excursion = max(alt_f) - min(alt_f)
    days = [s for s in seg_out if s["period"] == "DAY"]
    nights = [s for s in seg_out if s["period"] == "NIGHT"]
    interp = []

    def add(level, text, basis):
        interp.append({"level": level, "text": text, "basis": basis})

    if days and nights:
        dmean = statistics.fmean(s["altitude_mean_m"] for s in days)
        nmean = statistics.fmean(s["altitude_mean_m"] for s in nights)
        diff = dmean - nmean
        if diff > 0:
            add("INFO", f"Model shows the balloon floating higher by day than by night (mean difference {diff:,.0f} m).",
                "Mean float altitude of DAY vs NIGHT segments (solar_disc_fraction > 0).")
        else:
            add("INFO", f"Model does not show higher daytime float (day-night mean difference {diff:,.0f} m).",
                "Mean float altitude of DAY vs NIGHT segments.")
        add("INFO", f"Mean helium superheat: day {statistics.fmean(s['superheat_mean_k'] for s in days):+.1f} K, "
                    f"night {statistics.fmean(s['superheat_mean_k'] for s in nights):+.1f} K.",
            "helium_temperature_k - air_temperature_k averaged per segment.")
    lags = [s["thermal_lag_helium_min"] for s in days if "thermal_lag_helium_min" in s]
    if lags:
        add("INFO", f"Thermal lag: helium temperature peaks on average {statistics.fmean(lags):.0f} min after peak "
                    "solar elevation.", "Time difference between maximum solar elevation and maximum helium temperature per day segment.")
    add("WARNING" if excursion > 1000 else "INFO",
        f"Float altitude range over the simulation: {min(alt_f):,.0f} to {max(alt_f):,.0f} m (excursion {excursion:,.0f} m).",
        "Min/max altitude of float records; >1000 m flagged as a potential altitude excursion.")
    limit = balloon.max_differential_pressure_pa
    if dp_max > limit:
        add("CRITICAL", f"Peak differential pressure {dp_max:,.0f} Pa exceeds the nominal limit {limit:,.0f} Pa.",
            "max(differential_pressure_pa) vs Balloon.max_differential_pressure_pa (nominal, not certified).")
    elif dp_max > 0.85 * limit:
        add("WARNING", f"Peak differential pressure {dp_max:,.0f} Pa is within 15% of the nominal limit {limit:,.0f} Pa.",
            "max(differential_pressure_pa) vs 85% of nominal limit.")
    else:
        add("INFO", f"Peak differential pressure {dp_max:,.0f} Pa (margin {limit - dp_max:,.0f} Pa to nominal limit).",
            "max(differential_pressure_pa).")
    if dp_min < 0:
        add("WARNING", f"Differential pressure falls to {dp_min:,.0f} Pa (under-pressurised / slack envelope) - "
                       "super-pressure float is not maintained at those times.", "min(differential_pressure_pa) < 0.")
    stable = [s for s in seg_out if s["vertical_speed_std_ms"] < 0.05]
    if stable:
        add("INFO", f"{len(stable)} of {len(seg_out)} float segments show stable float "
                    "(vertical-speed standard deviation < 0.05 m/s).", "pstdev(vertical_speed_ms) per segment.")
    return {
        "events": events, "segments": seg_out, "interpretations": interp,
        "summary": {"float_altitude_min_m": min(alt_f), "float_altitude_max_m": max(alt_f),
                    "dp_max_pa": dp_max, "dp_min_pa": dp_min, "dp_limit_pa": limit,
                    "records": len(rows), "float_records": len(floats)},
        "advisories": {
            "available": False,
            "reason": "The backend contains no validated ballast or venting model. No ballast or venting "
                      "quantities are calculated or recommended.",
        },
    }


if __name__ == "__main__":
    run(main)
