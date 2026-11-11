"""Simulation mode: telemetry generated from SFT model output.

Flight states come from the EXISTING SFT models - a completed burst-calculator,
forward-trajectory or diurnal job, or the recorded model output shipped with
the burst calculator (artifacts/imported_outputs/complete_flight_trajectory.csv,
an actual run of flight_model_paramaterized for 2026-10-31, Chennai).

Every packet is tagged data_source=SIMULATED and goes through exactly the same
validation/alert pipeline as hardware telemetry, but only into SIMULATION
missions (the hub refuses to mix sources). Test scenarios only perturb
simulated packets. Payload-health values (battery, payload temperature,
uptime) are produced by a simple synthetic generator because no SFT model
covers them; the mission config records this.
"""
from __future__ import annotations

import asyncio
import csv
import json
import math
import random
from datetime import timedelta

import config
from core import db, tasks
from core.geo import geodesic_m
from core.predictions import store_prediction
from core.db import iso, parse_iso
from core.telemetry import hub

SCENARIOS = {
    "gps_loss": "GPS fix lost (no position) inside the window",
    "communication_interruption": "No packets transmitted inside the window",
    "battery_degradation": "Accelerated battery voltage decay (V/h, default 3)",
    "temperature_anomaly": "Payload/internal temperature offset (degC, default +55)",
    "pressure_anomaly": "Differential-pressure offset (Pa, default +1200) when modelled",
    "altitude_deviation": "Altitude offset ramp (m, default -1500)",
    "sensor_failure": "Barometer reports FAIL inside the window",
}


LAUNCH_MATCH_TOLERANCE_M = 5000.0


def load_source(source: str) -> tuple[list[dict], dict]:
    """Return (points, meta). Points use the shared trajectory format."""
    if source == "recorded":
        pts = []
        with open(config.RECORDED_MODEL_OUTPUT_CSV, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                g = lambda k: float(r[k]) if r.get(k) not in (None, "") else None  # noqa: E731
                vz = g("ascent_rate") if r["phase"] != "descent" else (-g("vertical_velocity_mps") if g("vertical_velocity_mps") is not None else None)
                pts.append({"t": r["datetime_utc"], "lat": g("latitude"), "lon": g("longitude"),
                            "alt": g("altitude_m"), "phase": r["phase"], "wind_u": g("wind_u"),
                            "wind_v": g("wind_v"), "wind_speed": g("wind_speed"), "temperature_c": g("temperature_C"),
                            "pressure_hpa": g("pressure_hpa"), "volume_m3": g("volume_m3"), "vz": vz})
        return pts, {"model_version": "SFT flight_model_paramaterized - recorded output (2026-10-31 run)",
                     "forecast_cycle": "2026103100", "label": "Recorded SFT burst-calculator output"}
    kind, _, sim_id = source.partition(":")
    res = tasks.get_manager().result(sim_id)
    if not res:
        raise ValueError(f"Simulation {sim_id} has no completed result")
    if "rows" in res:   # diurnal
        pts = [{"t": r["time_utc"], "lat": r["latitude_deg"], "lon": r["longitude_deg"], "alt": r["altitude_m"],
                "phase": r["phase"], "vz": r["vertical_speed_ms"], "wind_u": r["u_wind_ms"], "wind_v": r["v_wind_ms"],
                "wind_speed": math.hypot(r["u_wind_ms"], r["v_wind_ms"]),
                "temperature_c": r["air_temperature_k"] - 273.15, "pressure_hpa": r["air_pressure_pa"] / 100,
                "gas_temp_c": r["helium_temperature_k"] - 273.15, "env_temp_c": r["envelope_temperature_k"] - 273.15,
                "dp_pa": r["differential_pressure_pa"], "volume_m3": r["envelope_volume_m3"]} for r in res["rows"]]
    else:
        pts = res["trajectory"]
    pts = [p for p in pts if p.get("t")]
    # Drop exact duplicate timestamps (burst/descent boundary record is shared).
    dedup, seen = [], set()
    for p in pts:
        if p["t"] not in seen:
            seen.add(p["t"])
            dedup.append(p)
    return dedup, {"model_version": res.get("model_version"), "forecast_cycle": res.get("forecast_cycle"),
                   "label": f"{kind} job {sim_id}"}


def _interp(pts, ts, i):
    while i + 1 < len(pts) and pts[i + 1]["_t"] <= ts:
        i += 1
    a = pts[i]
    b = pts[min(i + 1, len(pts) - 1)]
    f = 0.0 if b["_t"] == a["_t"] else (ts - a["_t"]) / (b["_t"] - a["_t"])
    out = {}
    for k in set(a) | set(b):
        va, vb = a.get(k), b.get(k)
        if isinstance(va, (int, float)) and isinstance(vb, (int, float)) and k != "_t":
            out[k] = va + f * (vb - va)
        else:
            out[k] = va
    return out, i


class SimRun:
    def __init__(self, mission_id: str, points: list[dict], meta: dict, opts: dict):
        self.mission_id = mission_id
        self.points = points
        for p in points:
            p["_t"] = parse_iso(p["t"]).timestamp()
        self.meta = meta
        self.speed = max(0.1, float(opts.get("speed", 10.0)))
        self.interval = max(1.0, float(opts.get("interval_s", 10.0)))
        self.gps_noise = max(0.0, float(opts.get("gps_noise_m", 0.0)))
        self.scenarios = opts.get("scenarios", [])
        self.prelaunch_s = float(opts.get("prelaunch_s", 60.0))
        self.state = "READY"
        self.seq = 0
        self.sim_t = points[0]["_t"] - self.prelaunch_s
        self.task: asyncio.Task | None = None
        self.paused = asyncio.Event()
        self.paused.set()
        self.rng = random.Random(opts.get("seed", 42))
        self.last_result = None

    def _active(self, kind, frac):
        for s in self.scenarios:
            if s.get("type") == kind and s.get("start", 0) <= frac <= s.get("end", 1):
                return s
        return None

    def _packet(self, p: dict, frac: float, elapsed_h: float) -> dict | None:
        if self._active("communication_interruption", frac):
            return None
        lat, lon, alt = p["lat"], p["lon"], p["alt"]
        if self.gps_noise:
            dn, de = self.rng.gauss(0, self.gps_noise), self.rng.gauss(0, self.gps_noise)
            lat += math.degrees(dn / 6_371_000)
            lon += math.degrees(de / (6_371_000 * max(math.cos(math.radians(lat)), 1e-6)))
        dev = self._active("altitude_deviation", frac)
        if dev:
            span = max(dev.get("end", 1) - dev.get("start", 0), 1e-6)
            alt += float(dev.get("magnitude", -1500.0)) * min(1.0, (frac - dev.get("start", 0)) / span)
        payload = {"latitude": lat, "longitude": lon, "gps_altitude": alt, "gps_fix": True, "gps_satellites": 9,
                   "gps_hdop": 1.1}
        if self._active("gps_loss", frac):
            payload.update({"gps_fix": False, "gps_satellites": 2, "gps_hdop": 25.0})
        if p.get("temperature_c") is not None:
            payload["ambient_temperature"] = p["temperature_c"]
        if p.get("pressure_hpa") is not None:
            payload["atmospheric_pressure"] = p["pressure_hpa"]
        if p.get("wind_u") is not None and p.get("wind_v") is not None:
            u, v = p["wind_u"], p["wind_v"]
            payload["wind_speed"] = math.hypot(u, v)
            payload["wind_direction_from"] = (math.degrees(math.atan2(-u, -v)) + 360) % 360
        for src, dst in (("gas_temp_c", "internal_gas_temperature"), ("env_temp_c", "envelope_temperature"),
                         ("dp_pa", "differential_pressure"), ("volume_m3", "balloon_volume")):
            if p.get(src) is not None:
                payload[dst] = p[src]
        pa = self._active("pressure_anomaly", frac)
        if pa and payload.get("differential_pressure") is not None:
            payload["differential_pressure"] += float(pa.get("magnitude", 1200.0))
        # Synthetic payload-health generator (no SFT model covers these).
        batt = 8.4 - 0.12 * elapsed_h
        bd = self._active("battery_degradation", frac)
        if bd:
            batt -= float(bd.get("magnitude", 3.0)) * max(0.0, (frac - bd.get("start", 0))) * (self.duration_h or 1)
        payload["battery_voltage"] = max(5.0, batt)
        payload["battery_current"] = 0.42
        ptemp = 22.0 - 0.0009 * max(alt, 0)
        ta = self._active("temperature_anomaly", frac)
        if ta:
            ptemp += float(ta.get("magnitude", 55.0))
            if payload.get("internal_gas_temperature") is not None:
                payload["internal_gas_temperature"] += float(ta.get("magnitude", 55.0))
        payload["payload_temperature"] = ptemp
        payload["system_uptime"] = elapsed_h * 3600 + self.prelaunch_s
        if self._active("sensor_failure", frac):
            payload["sensor_status"] = {"gps": "OK", "barometer": "FAIL"}
        self.seq += 1
        return {"mission_id": self.mission_id, "packet_id": f"SIM-{self.seq:06d}",
                "timestamp_utc": iso(parse_iso(p["t"])) if "t" in p else None,
                "data_source": "SIMULATED", "payload": payload}

    @property
    def duration_h(self):
        return (self.points[-1]["_t"] - self.points[0]["_t"]) / 3600

    async def run(self):
        self.state = "RUNNING"
        idx = 0
        t_start, t_end = self.points[0]["_t"], self.points[-1]["_t"]
        launch_iso = self.points[0]["t"]
        try:
            while self.sim_t <= t_end:
                await self.paused.wait()
                if self.sim_t < t_start:     # pre-launch: on the pad
                    p = dict(self.points[0])
                    p["vz"] = 0.0
                else:
                    p, idx = _interp(self.points, self.sim_t, idx)
                p["t"] = iso(parse_iso(launch_iso) + timedelta(seconds=self.sim_t - t_start))
                frac = max(0.0, (self.sim_t - t_start) / max(t_end - t_start, 1))
                pkt = self._packet(p, frac, max(0.0, (self.sim_t - t_start) / 3600))
                if pkt:
                    self.last_result = await hub.ingest(pkt)
                self.sim_t += self.interval
                await asyncio.sleep(self.interval / self.speed)
            self.state = "COMPLETED (source trajectory ended - terminal model state, not confirmed touchdown)"
        except asyncio.CancelledError:
            self.state = "STOPPED"

    def status(self) -> dict:
        t0, t1 = self.points[0]["_t"], self.points[-1]["_t"]
        return {"mission_id": self.mission_id, "state": self.state, "packets_sent": self.seq,
                "speed": self.speed, "interval_s": self.interval, "gps_noise_m": self.gps_noise,
                "source": self.meta.get("label"), "scenarios": self.scenarios,
                "progress": max(0.0, min(1.0, (self.sim_t - t0) / max(t1 - t0, 1))),
                "sim_time_utc": iso(parse_iso(self.points[0]["t"]) + timedelta(seconds=self.sim_t - t0)),
                "last_ingest": self.last_result}


RUNS: dict[str, SimRun] = {}


async def start(mission_id: str, opts: dict) -> dict:
    if mission_id in RUNS and RUNS[mission_id].state == "RUNNING":
        raise RuntimeError("Simulation already running for this mission")
    st = hub.state(mission_id)
    if st.mode != "SIMULATION":
        raise ValueError("Simulated telemetry can only be generated for SIMULATION missions")
    points, meta = load_source(opts.get("source", "recorded"))
    if len(points) < 2:
        raise ValueError("Source trajectory too short")
    # The simulated telemetry replays the source trajectory unchanged. Refuse a source that was NOT launched from
    # this mission's launch coordinates instead of silently replaying another location (e.g. the recorded Chennai run).
    m = db.query_one("SELECT launch_latitude, launch_longitude FROM missions WHERE mission_id=?", (mission_id,))
    p0 = points[0]
    if m and m["launch_latitude"] is not None and p0.get("lat") is not None:
        off = geodesic_m(m["launch_latitude"], m["launch_longitude"], p0["lat"], p0["lon"])
        if off > LAUNCH_MATCH_TOLERANCE_M:
            raise ValueError(
                f"Source trajectory starts at {p0['lat']:.4f}, {p0['lon']:.4f} which is {off / 1000:.1f} km from this "
                f"mission's launch point ({m['launch_latitude']:.4f}, {m['launch_longitude']:.4f}). Run the burst "
                "calculator / forward trajectory with the mission's launch coordinates and use that job as the source.")
    if opts.get("attach_prediction", True):
        store_prediction(mission_id, points, source=f"Simulation baseline - {meta['label']}",
                         model_version=meta.get("model_version"), forecast_cycle=meta.get("forecast_cycle"),
                         metadata={"note": "Baseline = unperturbed model output used to drive the simulation",
                                   **({"simulation_id": opts["source"].partition(":")[2]} if ":" in str(opts.get("source", "")) else {})})
        hub.reload(mission_id)
    run = SimRun(mission_id, points, meta, opts)
    RUNS[mission_id] = run
    run.task = asyncio.create_task(run.run())
    return run.status()


def pause(mission_id: str, paused: bool) -> dict:
    run = RUNS[mission_id]
    if paused:
        run.paused.clear()
        run.state = "PAUSED"
    else:
        run.paused.set()
        run.state = "RUNNING"
    return run.status()


def stop(mission_id: str) -> dict:
    run = RUNS[mission_id]
    if run.task and not run.task.done():
        run.task.cancel()
    run.state = "STOPPED"
    return run.status()


def status(mission_id: str) -> dict | None:
    run = RUNS.get(mission_id)
    return run.status() if run else None
