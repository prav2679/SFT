"""Telemetry gateway: validation, quality, storage, phase, alerts, broadcast.

The backend is the ONLY communication gateway; the frontend never talks to
hardware. This module never issues control commands of any kind.

Quality states: VALID | DEGRADED | INVALID | STALE.
Value classes exposed to the UI: MEASURED | SIMULATED | MODEL ESTIMATE |
FORECAST | UNAVAILABLE. Missing sensor values are stored as NULL and shown as
N/A - they are never replaced by estimates. Derived quantities (e.g. heading
computed from successive GPS fixes) are listed in ``derived_fields`` and
classified MODEL ESTIMATE.
"""
from __future__ import annotations

import asyncio
import json
import math
import uuid
from collections import deque
from datetime import datetime, timedelta
from typing import Any

from core import db
from core.db import iso, parse_iso, utcnow

R_AIR = 287.05
G0 = 9.80665
EARTH_RADIUS = 6_371_000.0

# Canonical field catalogue: name -> (group, unit, label)
FIELDS: dict[str, tuple[str, str, str]] = {
    "latitude": ("navigation", "deg", "Latitude"),
    "longitude": ("navigation", "deg", "Longitude"),
    "gps_altitude": ("navigation", "m", "GPS altitude"),
    "vertical_velocity": ("navigation", "m/s", "Vertical velocity"),
    "ground_speed": ("navigation", "m/s", "Ground speed"),
    "heading": ("navigation", "deg", "Ground track"),
    "gps_satellites": ("navigation", "count", "GPS satellites"),
    "gps_hdop": ("navigation", "-", "GPS HDOP"),
    "ambient_temperature": ("atmospheric", "degC", "Ambient temperature"),
    "atmospheric_pressure": ("atmospheric", "hPa", "Atmospheric pressure"),
    "relative_humidity": ("atmospheric", "%", "Relative humidity"),
    "wind_speed": ("atmospheric", "m/s", "Wind speed"),
    "wind_direction_from": ("atmospheric", "deg", "Wind direction FROM"),
    "internal_gas_temperature": ("balloon", "degC", "Internal gas temperature"),
    "envelope_temperature": ("balloon", "degC", "Envelope temperature"),
    "internal_pressure": ("balloon", "hPa", "Internal pressure"),
    "differential_pressure": ("balloon", "Pa", "Differential pressure"),
    "balloon_volume": ("balloon", "m3", "Balloon volume"),
    "battery_voltage": ("payload", "V", "Battery voltage"),
    "battery_current": ("payload", "A", "Battery current"),
    "battery_percentage": ("payload", "%", "Battery percentage"),
    "payload_temperature": ("payload", "degC", "Payload temperature"),
    "system_uptime": ("payload", "s", "System uptime"),
    "cpu_temperature": ("payload", "degC", "CPU temperature"),
    "storage_free_pct": ("payload", "%", "Storage free"),
    "accel_x": ("imu", "m/s2", "Acceleration X"), "accel_y": ("imu", "m/s2", "Acceleration Y"),
    "accel_z": ("imu", "m/s2", "Acceleration Z"),
    "gyro_x": ("imu", "deg/s", "Angular velocity X"), "gyro_y": ("imu", "deg/s", "Angular velocity Y"),
    "gyro_z": ("imu", "deg/s", "Angular velocity Z"),
    "roll": ("imu", "deg", "Roll"), "pitch": ("imu", "deg", "Pitch"), "yaw": ("imu", "deg", "Yaw"),
}
UNIT_CONVERSIONS = {
    ("K", "degC"): lambda v: v - 273.15,
    ("Pa", "hPa"): lambda v: v / 100.0,
    ("hPa", "Pa"): lambda v: v * 100.0,
    ("kPa", "Pa"): lambda v: v * 1000.0,
    ("km/h", "m/s"): lambda v: v / 3.6,
    ("mV", "V"): lambda v: v / 1000.0,
}
DEFAULT_THRESHOLDS = {
    "differential_pressure_max_pa": 1500.0,      # SPB nominal (not certified) - spb_parameters.py
    "differential_pressure_warn_fraction": 0.85,
    "battery_warning_v": 7.0,                    # placeholder - configure for the actual battery
    "battery_critical_v": 6.6,                   # placeholder - configure for the actual battery
    "payload_temperature_max_c": 60.0,
    "payload_temperature_min_c": -40.0,
    "internal_gas_temperature_max_c": 60.0,
    "wind_speed_max_ms": 60.0,
    "rapid_altitude_loss_ms": -15.0,
    "altitude_deviation_warning_m": 1000.0,
    "gps_hdop_max": 5.0,
    "max_horizontal_speed_ms": 200.0,
    "max_vertical_speed_ms": 100.0,
}
DEFAULT_CONFIG = {
    "telemetry_interval_s": 10.0,
    "stale_after_s": 120.0,
    "future_tolerance_s": 120.0,
    "sensors": ["gps", "barometer", "ambient_temperature", "battery"],
    "burst_expected": True,      # False for super-pressure float missions
    "masses_kg": {"payload": None, "envelope": None, "helium": None},
    "reference_volume_m3": None,
    "thresholds": DEFAULT_THRESHOLDS,
}
PHASES = ["PRE-LAUNCH", "ASCENT", "FLOAT", "DESCENT", "LANDED", "ABORTED"]


def haversine(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS * math.asin(min(1.0, math.sqrt(a)))


def bearing(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def _num(v):
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


ALTITUDE_MIN_M = -500.0          # below the lowest land surface (Dead Sea shore ~ -430 m)
ALTITUDE_MAX_M = 60000.0         # above any latex / super-pressure balloon float altitude supported by the models


def detect_phase(vertical_velocity: float | None, altitude: float | None, launch_altitude: float = 0.0,
                 current_phase: str | None = None, max_altitude: float | None = None) -> dict:
    """Classify ONE observed state (used for manual telemetry where no packet history exists).

    ASCENT  : climbing faster than 1 m/s
    DESCENT : sinking faster than 2 m/s
    FLOAT   : |vz| <= 1 m/s and more than 5 km above the launch altitude
    LANDED  : |vz| < 0.3 m/s within 100 m of launch altitude after having flown
    Anything else is ambiguous and returns phase=None, so the operator must choose explicitly.
    """
    if vertical_velocity is None or altitude is None:
        return {"phase": None, "reason": "vertical velocity and altitude are required for automatic detection"}
    above = altitude - (launch_altitude or 0.0)
    if vertical_velocity > 1.0:
        return {"phase": "ASCENT", "reason": f"climbing at {vertical_velocity:+.2f} m/s"}
    if vertical_velocity < -2.0:
        return {"phase": "DESCENT", "reason": f"sinking at {vertical_velocity:+.2f} m/s"}
    if abs(vertical_velocity) <= 1.0 and above > 5000:
        return {"phase": "FLOAT", "reason": f"|vz| {abs(vertical_velocity):.2f} m/s at {above:,.0f} m above launch"}
    if abs(vertical_velocity) < 0.3 and above <= 100 and (max_altitude or 0) - (launch_altitude or 0) > 1000:
        return {"phase": "LANDED", "reason": "stationary near launch altitude after flight"}
    if current_phase in ("ASCENT", "FLOAT", "DESCENT"):
        return {"phase": None, "reason": f"ambiguous (vz {vertical_velocity:+.2f} m/s, {above:,.0f} m above launch); "
                                         f"mission is currently {current_phase} - choose the phase explicitly"}
    return {"phase": None, "reason": "ambiguous state - choose the phase explicitly"}


class PacketRejected(Exception):
    def __init__(self, reason: str, code: str):
        super().__init__(reason)
        self.code = code


class MissionState:
    def __init__(self, mission: dict):
        self.mission_id = mission["mission_id"]
        self.mode = mission["mode"]
        self.config = merge_config(json.loads(mission.get("config_json") or "{}"))
        self.launch = (mission.get("launch_latitude"), mission.get("launch_longitude"))
        self.launch_alt = mission.get("launch_altitude") or 0.0
        self.phase = mission.get("flight_phase") or "PRE-LAUNCH"
        self.phase_since = mission.get("phase_since")
        self.history: deque[dict] = deque(maxlen=30)
        self.last: dict | None = None
        self.last_received: datetime | None = None
        self.last_ts: datetime | None = None
        self.connection = "DISCONNECTED"
        self.active_rules: set[str] = set()
        self.max_alt: float | None = None
        self.distance_travelled = 0.0
        self.packet_count = 0
        self.prediction: list[dict] | None = None
        self.prediction_set: str | None = None
        self.subscribers: set = set()


def merge_config(cfg: dict) -> dict:
    out = json.loads(json.dumps(DEFAULT_CONFIG))
    for k, v in (cfg or {}).items():
        if k == "thresholds" and isinstance(v, dict):
            out["thresholds"].update({kk: vv for kk, vv in v.items() if vv is not None})
        elif k == "masses_kg" and isinstance(v, dict):
            out["masses_kg"].update(v)
        else:
            out[k] = v
    return out


class TelemetryHub:
    def __init__(self):
        self.states: dict[str, MissionState] = {}
        self._monitor_task: asyncio.Task | None = None

    # ----------------------------------------------------------- missions
    def state(self, mission_id: str) -> MissionState:
        st = self.states.get(mission_id)
        if st is None:
            m = db.query_one("SELECT * FROM missions WHERE mission_id=?", (mission_id,))
            if not m:
                raise KeyError(mission_id)
            st = MissionState(m)
            last = db.query_one("SELECT * FROM telemetry WHERE mission_id=? AND quality!='INVALID' "
                                "AND superseded_by IS NULL ORDER BY timestamp_utc DESC LIMIT 1", (mission_id,))
            if last:
                st.last = self._row_to_packet(last)
                st.last_ts = parse_iso(last["timestamp_utc"])
                st.last_received = parse_iso(last["received_utc"])
                agg = db.query_one("SELECT MAX(gps_altitude) AS mx, COUNT(*) AS n FROM telemetry WHERE mission_id=?",
                                   (mission_id,))
                st.max_alt, st.packet_count = agg["mx"], agg["n"]
                st.distance_travelled = st.last["payload"].get("_distance_travelled_m") or 0.0
            self._load_prediction(st)
            self.states[mission_id] = st
        return st

    def reload(self, mission_id: str):
        old = self.states.pop(mission_id, None)
        st = self.state(mission_id)
        if old:
            st.subscribers = old.subscribers
            st.connection = old.connection
            st.active_rules = old.active_rules
        return st

    def _load_prediction(self, st: MissionState):
        from core import predictions
        ps = predictions.original_set(st.mission_id)
        if ps:
            st.prediction_set = ps["prediction_set"]
            st.prediction = db.query("SELECT timestamp_utc, predicted_latitude, predicted_longitude, "
                                     "predicted_altitude FROM predictions WHERE prediction_set=? "
                                     "ORDER BY timestamp_utc", (ps["prediction_set"],))
            for p in st.prediction:
                p["_t"] = parse_iso(p["timestamp_utc"]).timestamp()

    # ----------------------------------------------------------- ingestion
    async def ingest(self, packet: dict[str, Any]) -> dict:
        try:
            result = self._ingest(packet)
        except PacketRejected as exc:
            return {"accepted": False, "code": exc.code, "reason": str(exc)}
        await self._broadcast_after_ingest(result)
        return {"accepted": True, "packet_id": result["packet"]["packet_id"], "quality": result["packet"]["quality"],
                "quality_flags": result["packet"]["quality_flags"], "live": result["live"],
                "telemetry_id": result["packet"].get("telemetry_id")}

    def _ingest(self, packet: dict) -> dict:
        now = utcnow()
        for key in ("mission_id", "packet_id", "timestamp_utc", "data_source"):
            if packet.get(key) in (None, ""):
                raise PacketRejected(f"Malformed packet: missing '{key}'", "MALFORMED")
        mission_id = str(packet["mission_id"])
        try:
            st = self.state(mission_id)
        except KeyError:
            raise PacketRejected(f"Unknown mission {mission_id}", "UNKNOWN_MISSION")
        source = str(packet["data_source"]).upper()
        if source not in ("MEASURED", "SIMULATED"):
            raise PacketRejected("data_source must be MEASURED or SIMULATED", "MALFORMED")
        expected = "SIMULATED" if st.mode == "SIMULATION" else "MEASURED"
        if source != expected:
            raise PacketRejected(f"{source} packet rejected: mission {mission_id} is a {st.mode} mission. "
                                 "Simulated and measured telemetry are never mixed.", "SOURCE_MISMATCH")
        try:
            ts = parse_iso(packet["timestamp_utc"])
        except (TypeError, ValueError):
            raise PacketRejected("Invalid timestamp_utc (ISO-8601 UTC required)", "BAD_TIMESTAMP")
        cfg = st.config
        if source == "MEASURED" and ts > now + timedelta(seconds=cfg["future_tolerance_s"]):
            raise PacketRejected(f"Impossible timestamp {iso(ts)} is in the future", "BAD_TIMESTAMP")
        if ts.year < 2000:
            raise PacketRejected("Impossible timestamp (before 2000)", "BAD_TIMESTAMP")
        packet_id = str(packet["packet_id"])
        if db.query_one("SELECT 1 FROM telemetry WHERE mission_id=? AND packet_id=?", (mission_id, packet_id)):
            raise PacketRejected(f"Duplicate packet_id {packet_id}", "DUPLICATE")
        manual = packet.get("entry_method") == "MANUAL"
        target = None
        if packet.get("correction_of") is not None:         # explicit correction workflow (never silent)
            target = db.query_one("SELECT telemetry_id, superseded_by FROM telemetry WHERE mission_id=? AND telemetry_id=?",
                                  (mission_id, packet["correction_of"]))
            if not target:
                raise PacketRejected("correction_of does not refer to a telemetry record of this mission", "BAD_CORRECTION")
            if target["superseded_by"] is not None:
                raise PacketRejected("That telemetry record has already been corrected", "BAD_CORRECTION")
            if not str(packet.get("correction_reason") or "").strip():
                raise PacketRejected("A correction requires a written reason (audit trail)", "BAD_CORRECTION")
        clash = db.query_one("SELECT telemetry_id FROM telemetry WHERE mission_id=? AND timestamp_utc=? "
                             "AND superseded_by IS NULL AND telemetry_id IS NOT ?",
                             (mission_id, iso(ts), target["telemetry_id"] if target else None))
        if clash:
            raise PacketRejected(f"Conflicting record: telemetry {clash['telemetry_id']} already exists for "
                                 f"{iso(ts)}. Historical observations are never overwritten - use the explicit "
                                 "correction workflow to replace it.", "DUPLICATE")

        raw = packet.get("payload") or {}
        if not isinstance(raw, dict):
            raise PacketRejected("payload must be an object", "MALFORMED")
        units = packet.get("units") or {}
        flags: list[str] = []
        payload: dict[str, Any] = {}
        for name, (_, unit, _) in FIELDS.items():
            if name not in raw:
                continue
            v = _num(raw[name])
            if raw[name] is not None and v is None:
                flags.append(f"NON_NUMERIC:{name}")
            given = units.get(name)
            if v is not None and given and given != unit:
                conv = UNIT_CONVERSIONS.get((given, unit))
                if conv is None:
                    raise PacketRejected(f"Unsupported unit '{given}' for {name} (expected {unit})", "BAD_UNITS")
                v = conv(v)
            payload[name] = v
        payload["gps_fix"] = raw.get("gps_fix")
        payload["sensor_status"] = raw.get("sensor_status") if isinstance(raw.get("sensor_status"), dict) else None
        payload["termination_confirmed"] = bool(raw.get("termination_confirmed", False))
        derived: list[str] = []

        quality = "VALID"
        lat, lon = payload.get("latitude"), payload.get("longitude")
        if lat is not None and not -90 <= lat <= 90 or lon is not None and not -180 <= lon <= 180:
            flags.append("INVALID_COORDINATES")
            payload["latitude"] = payload["longitude"] = None
            quality = "INVALID"
        if payload["gps_fix"] is False:
            flags.append("GPS_NO_FIX")
            payload["latitude"] = payload["longitude"] = payload["gps_altitude"] = None
            quality = "DEGRADED" if quality == "VALID" else quality
        hdop = payload.get("gps_hdop")
        if hdop is not None and hdop > cfg["thresholds"]["gps_hdop_max"]:
            flags.append("GPS_HDOP_HIGH")
            quality = "DEGRADED" if quality == "VALID" else quality
        if payload["sensor_status"] and any(str(v).upper() in ("FAIL", "FAULT", "ERROR")
                                            for v in payload["sensor_status"].values()):
            flags.append("SENSOR_FAULT")
            quality = "DEGRADED" if quality == "VALID" else quality

        alt_v = payload.get("gps_altitude")
        if alt_v is not None and not ALTITUDE_MIN_M <= alt_v <= ALTITUDE_MAX_M:
            flags.append("IMPOSSIBLE_ALTITUDE")
            payload["gps_altitude"] = None
            quality = "INVALID"

        live = True
        if st.last_ts and ts < st.last_ts and target is not None:
            flags.append("CORRECTION_OF_HISTORICAL_RECORD")       # explicit correction: stored in order, not "live"
            live = False
        elif st.last_ts and ts < st.last_ts:
            flags.append("OUT_OF_ORDER")
            quality, live = "STALE", False
        elif source == "MEASURED" and not manual and (now - ts).total_seconds() > cfg["stale_after_s"]:
            flags.append("STALE_TIMESTAMP")
            quality = "STALE"

        if quality == "INVALID":
            live = False         # stored for audit, never becomes the live state

        # Derived navigation (MODEL ESTIMATE) from the previous valid fix.
        prev = st.last if live else None
        if prev and payload.get("latitude") is not None and prev["payload"].get("latitude") is not None:
            dt = (ts - parse_iso(prev["timestamp_utc"])).total_seconds()
            if dt > 0:
                d = haversine(prev["payload"]["latitude"], prev["payload"]["longitude"],
                              payload["latitude"], payload["longitude"])
                if d / dt > cfg["thresholds"]["max_horizontal_speed_ms"]:
                    flags.append("UNREALISTIC_HORIZONTAL_JUMP")
                    quality = "DEGRADED" if quality == "VALID" else quality
                else:
                    st.distance_travelled += d
                if payload.get("ground_speed") is None:
                    payload["ground_speed"] = d / dt
                    derived.append("ground_speed")
                if payload.get("heading") is None and d > 1.0:
                    payload["heading"] = bearing(prev["payload"]["latitude"], prev["payload"]["longitude"],
                                                 payload["latitude"], payload["longitude"])
                    derived.append("heading")
                if payload.get("gps_altitude") is not None and prev["payload"].get("gps_altitude") is not None:
                    vz = (payload["gps_altitude"] - prev["payload"]["gps_altitude"]) / dt
                    if abs(vz) > cfg["thresholds"]["max_vertical_speed_ms"]:
                        flags.append("UNREALISTIC_VERTICAL_JUMP")
                        quality = "DEGRADED" if quality == "VALID" else quality
                    elif payload.get("vertical_velocity") is None:
                        payload["vertical_velocity"] = vz
                        derived.append("vertical_velocity")
        if payload.get("wind_direction_from") is not None:
            payload["wind_direction_toward"] = (payload["wind_direction_from"] + 180) % 360
            derived.append("wind_direction_toward")
        if payload.get("latitude") is not None and st.launch[0] is not None:
            payload["distance_from_launch_m"] = haversine(st.launch[0], st.launch[1],
                                                          payload["latitude"], payload["longitude"])
            derived.append("distance_from_launch_m")
        payload["_distance_travelled_m"] = st.distance_travelled
        derived.append("_distance_travelled_m")
        self._buoyancy_estimate(st, payload, derived)

        record = {
            "mission_id": mission_id, "packet_id": packet_id, "timestamp_utc": iso(ts),
            "received_utc": iso(now), "data_source": source, "quality": quality,
            "quality_flags": flags, "derived_fields": derived, "payload": payload,
        }
        tid = db.execute(
            "INSERT INTO telemetry (mission_id, packet_id, timestamp_utc, received_utc, latitude, longitude, "
            "gps_altitude, vertical_velocity, ground_speed, heading, ambient_temperature, atmospheric_pressure, "
            "internal_gas_temperature, envelope_temperature, internal_pressure, differential_pressure, "
            "battery_voltage, battery_current, sensor_status, data_source, quality, quality_flags, payload_json, "
            "entry_method, corrects_telemetry_id, correction_reason) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (mission_id, packet_id, iso(ts), iso(now), payload.get("latitude"), payload.get("longitude"),
             payload.get("gps_altitude"), payload.get("vertical_velocity"), payload.get("ground_speed"),
             payload.get("heading"), payload.get("ambient_temperature"), payload.get("atmospheric_pressure"),
             payload.get("internal_gas_temperature"), payload.get("envelope_temperature"),
             payload.get("internal_pressure"), payload.get("differential_pressure"),
             payload.get("battery_voltage"), payload.get("battery_current"),
             json.dumps(payload.get("sensor_status")), source, quality, json.dumps(flags),
             json.dumps({"payload": payload, "derived_fields": derived}),
             "MANUAL" if manual else "API", target["telemetry_id"] if target else None,
             (str(packet.get("correction_reason")).strip() if target else None)))
        record["telemetry_id"] = tid
        record["entry_method"] = "MANUAL" if manual else "API"
        if target:                                    # audit link only; the old observation itself is untouched
            db.execute("UPDATE telemetry SET superseded_by=? WHERE telemetry_id=?", (tid, target["telemetry_id"]))

        events, alerts = [], []
        if target:
            events.append(self._event(st, "TELEMETRY", f"Telemetry record {target['telemetry_id']} corrected by "
                                      f"{tid}: {str(packet.get('correction_reason')).strip()}", iso(ts), source))
        st.packet_count += 1
        st.last_received = now
        if live:
            if st.packet_count == 1:
                events.append(self._event(st, "MISSION", "Mission telemetry started", iso(ts), source))
            st.last, st.last_ts = record, ts
            st.history.append(record)
            alt = payload.get("gps_altitude")
            if alt is not None:
                st.max_alt = alt if st.max_alt is None else max(st.max_alt, alt)
            events += self._update_phase(st, record)
            alerts += self._evaluate_alerts(st, record)
        return {"state": st, "packet": record, "live": live, "events": events, "alerts": alerts}

    def _buoyancy_estimate(self, st: MissionState, p: dict, derived: list):
        """Gross/net lift MODEL ESTIMATE - only when every input is available."""
        m = st.config.get("masses_kg") or {}
        vol, pres, temp = p.get("balloon_volume"), p.get("atmospheric_pressure"), p.get("ambient_temperature")
        if None in (vol, pres, temp) or not all(m.get(k) for k in ("payload", "envelope", "helium")):
            return
        rho = pres * 100.0 / (R_AIR * (temp + 273.15))
        gross = rho * vol * G0
        total = m["payload"] + m["envelope"] + m["helium"]
        p["est_air_density"] = rho
        p["est_gross_lift_n"] = gross
        p["est_system_weight_n"] = total * G0
        p["est_net_lift_n"] = gross - total * G0
        p["est_vertical_acceleration_ms2"] = (gross - total * G0) / total
        derived += ["est_air_density", "est_gross_lift_n", "est_system_weight_n", "est_net_lift_n",
                    "est_vertical_acceleration_ms2"]

    # ----------------------------------------------------------- phase
    def _update_phase(self, st: MissionState, rec: dict) -> list[dict]:
        if st.phase in ("ABORTED", "LANDED"):
            return []
        hist = [h for h in st.history if h["payload"].get("vertical_velocity") is not None]
        vz = [h["payload"]["vertical_velocity"] for h in hist[-6:]]
        alt = rec["payload"].get("gps_altitude")
        if not vz or alt is None:
            return []
        new = st.phase
        above_launch = alt - (st.launch_alt or 0.0)
        if st.phase == "PRE-LAUNCH" and len(vz) >= 2 and min(vz[-2:]) > 1.0 and above_launch > 50:
            new = "ASCENT"
        elif st.phase in ("ASCENT", "FLOAT") and len(vz) >= 3 and max(vz[-3:]) < -2.0 \
                and st.max_alt is not None and st.max_alt - alt > 200:
            new = "DESCENT"
        elif st.phase == "ASCENT" and len(vz) >= 6 and max(abs(v) for v in vz) < 0.5 and above_launch > 5000:
            new = "FLOAT"
        elif st.phase == "FLOAT" and len(vz) >= 3 and min(vz[-3:]) > 1.0:
            new = "ASCENT"
        elif st.phase == "DESCENT" and len(vz) >= 5 and max(abs(v) for v in vz[-5:]) < 0.3 and above_launch < 3000:
            new = "LANDED"
        if new == st.phase:
            return []
        return [self.set_phase(st, new, rec["timestamp_utc"], rec["data_source"])]

    def set_phase(self, st: MissionState, phase: str, when: str, source: str | None = None) -> dict:
        old = st.phase
        st.phase, st.phase_since = phase, when
        status = "ACTIVE" if phase in ("ASCENT", "FLOAT", "DESCENT") else phase
        db.execute("UPDATE missions SET flight_phase=?, phase_since=?, mission_status=? WHERE mission_id=?",
                   (phase, when, status, st.mission_id))
        labels = {"ASCENT": "Ascent started", "FLOAT": "Float phase entered", "DESCENT": "Descent started",
                  "LANDED": "Landing detected", "ABORTED": "Mission aborted by operator"}
        return self._event(st, "FLIGHT_PHASE", f"{labels.get(phase, phase)} (from {old})", when, source)

    # ----------------------------------------------------------- alerts
    def _event(self, st, category, description, when, source, severity="INFO", parameter=None,
               value=None, threshold=None) -> dict:
        alert = {"alert_id": f"AL-{uuid.uuid4().hex[:10].upper()}", "mission_id": st.mission_id,
                 "timestamp_utc": when, "category": category, "severity": severity, "parameter": parameter,
                 "measured_value": value, "threshold": threshold, "description": description,
                 "data_source": source, "acknowledged": 0}
        db.execute("INSERT INTO alerts (alert_id, mission_id, timestamp_utc, category, severity, parameter, "
                   "measured_value, threshold, description, data_source, acknowledged) VALUES (?,?,?,?,?,?,?,?,?,?,0)",
                   (alert["alert_id"], st.mission_id, when, category, severity, parameter, value, threshold,
                    description, source))
        return alert

    def _rule(self, st, key, violated, **alert_kwargs) -> list[dict]:
        if violated and key not in st.active_rules:
            st.active_rules.add(key)
            return [self._event(st, **alert_kwargs)]
        if not violated:
            st.active_rules.discard(key)
        return []

    def _evaluate_alerts(self, st: MissionState, rec: dict) -> list[dict]:
        p, th, ts, src = rec["payload"], st.config["thresholds"], rec["timestamp_utc"], rec["data_source"]
        out: list[dict] = []
        dp = p.get("differential_pressure")
        if dp is not None:
            lim = th["differential_pressure_max_pa"]
            out += self._rule(st, "dp_crit", dp > lim, category="PRESSURE", severity="CRITICAL",
                              parameter="differential_pressure", value=dp, threshold=lim, when=ts, source=src,
                              description=f"Differential pressure {dp:.0f} Pa exceeds configured limit {lim:.0f} Pa")
            warn = lim * th["differential_pressure_warn_fraction"]
            out += self._rule(st, "dp_warn", warn < dp <= lim, category="PRESSURE", severity="WARNING",
                              parameter="differential_pressure", value=dp, threshold=warn, when=ts, source=src,
                              description=f"Differential pressure {dp:.0f} Pa approaching limit (warn at {warn:.0f} Pa)")
        bv = p.get("battery_voltage")
        if bv is not None:
            out += self._rule(st, "batt_crit", bv < th["battery_critical_v"], category="POWER", severity="CRITICAL",
                              parameter="battery_voltage", value=bv, threshold=th["battery_critical_v"], when=ts,
                              source=src, description=f"Battery critically low: {bv:.2f} V")
            out += self._rule(st, "batt_warn", th["battery_critical_v"] <= bv < th["battery_warning_v"],
                              category="POWER", severity="WARNING", parameter="battery_voltage", value=bv,
                              threshold=th["battery_warning_v"], when=ts, source=src,
                              description=f"Low battery: {bv:.2f} V")
        vz = p.get("vertical_velocity")
        if vz is not None:
            # Unexpected = during FLOAT, or during ASCENT when the mission does not expect a burst (SPB).
            unexpected_phase = st.phase == "FLOAT" or (st.phase == "ASCENT" and not st.config.get("burst_expected", True))
            out += self._rule(st, "rapid_loss", vz < th["rapid_altitude_loss_ms"] and unexpected_phase,
                              category="FLIGHT", severity="CRITICAL", parameter="vertical_velocity", value=vz,
                              threshold=th["rapid_altitude_loss_ms"], when=ts, source=src,
                              description=f"Unexpected rapid altitude loss: {vz:.1f} m/s during {st.phase}")
        if "SENSOR_FAULT" in rec["quality_flags"]:
            failed = [k for k, v in (p.get("sensor_status") or {}).items() if str(v).upper() in ("FAIL", "FAULT", "ERROR")]
            out += self._rule(st, "sensor_fault:" + ",".join(sorted(failed)), True, category="SENSOR",
                              severity="CRITICAL", parameter="sensor_status", when=ts, source=src,
                              description=f"Critical sensor failure reported: {', '.join(failed)}")
        else:
            for k in [r for r in st.active_rules if r.startswith("sensor_fault:")]:
                st.active_rules.discard(k)
        pt = p.get("payload_temperature")
        if pt is not None:
            out += self._rule(st, "ptemp", pt > th["payload_temperature_max_c"] or pt < th["payload_temperature_min_c"],
                              category="THERMAL", severity="WARNING", parameter="payload_temperature", value=pt,
                              threshold=th["payload_temperature_max_c"] if pt > 0 else th["payload_temperature_min_c"],
                              when=ts, source=src, description=f"Payload temperature out of range: {pt:.1f} degC")
        gt = p.get("internal_gas_temperature")
        if gt is not None:
            out += self._rule(st, "gtemp", gt > th["internal_gas_temperature_max_c"], category="THERMAL",
                              severity="WARNING", parameter="internal_gas_temperature", value=gt,
                              threshold=th["internal_gas_temperature_max_c"], when=ts, source=src,
                              description=f"Excessive internal gas temperature: {gt:.1f} degC")
        gps_bad = "GPS_NO_FIX" in rec["quality_flags"] or "GPS_HDOP_HIGH" in rec["quality_flags"]
        out += self._rule(st, "gps", gps_bad, category="NAVIGATION", severity="WARNING", parameter="gps",
                          when=ts, source=src, description="GPS quality degradation (no fix or high HDOP)")
        ws = p.get("wind_speed")
        if ws is not None:
            out += self._rule(st, "wind", ws > th["wind_speed_max_ms"], category="ENVIRONMENT", severity="WARNING",
                              parameter="wind_speed", value=ws, threshold=th["wind_speed_max_ms"], when=ts,
                              source=src, description=f"Wind speed {ws:.1f} m/s outside configured limit")
        dev = self.altitude_deviation(st, rec)
        if dev is not None:
            lim = th["altitude_deviation_warning_m"]
            out += self._rule(st, "alt_dev", abs(dev) > lim, category="FLIGHT", severity="WARNING",
                              parameter="altitude_deviation", value=dev, threshold=lim, when=ts, source=src,
                              description=f"Unexpected altitude deviation from prediction: {dev:+.0f} m")
        if p.get("termination_confirmed"):
            out += self._rule(st, "termination", True, category="FLIGHT", severity="CRITICAL",
                              parameter="termination_confirmed", when=ts, source=src,
                              description="Confirmed flight termination event reported by onboard system")
        return out

    def altitude_deviation(self, st: MissionState, rec: dict) -> float | None:
        alt = rec["payload"].get("gps_altitude")
        if alt is None or not st.prediction:
            return None
        t = parse_iso(rec["timestamp_utc"]).timestamp()
        pred = st.prediction
        if t < pred[0]["_t"] or t > pred[-1]["_t"]:
            return None          # outside prediction validity - never extrapolated
        lo, hi = 0, len(pred) - 1
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if pred[mid]["_t"] <= t:
                lo = mid
            else:
                hi = mid
        a, b = pred[lo], pred[hi]
        f = 0.0 if b["_t"] == a["_t"] else (t - a["_t"]) / (b["_t"] - a["_t"])
        return alt - (a["predicted_altitude"] + f * (b["predicted_altitude"] - a["predicted_altitude"]))

    # ----------------------------------------------------------- connection
    def connection_status(self, st: MissionState) -> str:
        if st.last_received is None:
            return "DISCONNECTED"
        age = (utcnow() - st.last_received).total_seconds()
        interval = float(st.config.get("telemetry_interval_s") or 10.0)
        degraded_quality = st.last and st.last["quality"] in ("DEGRADED", "STALE")
        if age <= 3 * interval and not degraded_quality:
            return "CONNECTED"
        if age <= 6 * interval:
            return "DEGRADED"
        return "DISCONNECTED"

    def snapshot(self, mission_id: str) -> dict:
        st = self.state(mission_id)
        st.connection = self.connection_status(st)
        age = (utcnow() - st.last_received).total_seconds() if st.last_received else None
        return {"mission_id": mission_id, "mode": st.mode, "connection": st.connection,
                "last_received_utc": iso(st.last_received), "seconds_since_last_packet": age,
                "flight_phase": st.phase, "phase_since": st.phase_since, "max_altitude": st.max_alt,
                "packet_count": st.packet_count, "distance_travelled_m": st.distance_travelled,
                "latest": st.last, "prediction_set": st.prediction_set,
                "active_alert_rules": sorted(st.active_rules)}

    async def monitor(self):
        """Background loop: connection-state transitions -> events + broadcast."""
        while True:
            await asyncio.sleep(2.0)
            for st in list(self.states.values()):
                new = self.connection_status(st)
                if new == st.connection:
                    continue
                old, st.connection = st.connection, new
                msgs = [{"type": "status", **self.snapshot(st.mission_id)}]
                if st.packet_count:
                    when = iso(utcnow())
                    if new == "DISCONNECTED":
                        ev = self._event(st, "COMMS", "Telemetry connection lost", when, None, severity="WARNING")
                        msgs.append({"type": "alert", "alert": ev})
                    elif new == "CONNECTED" and old == "DISCONNECTED":
                        ev = self._event(st, "COMMS", "Telemetry connection restored", when, None)
                        msgs.append({"type": "alert", "alert": ev})
                for m in msgs:
                    await self.broadcast(st.mission_id, m)

    # ----------------------------------------------------------- broadcast
    async def _broadcast_after_ingest(self, result: dict):
        st, rec = result["state"], result["packet"]
        st.connection = self.connection_status(st)
        msg = {"type": "telemetry", "mission_id": st.mission_id, "packet_id": rec["packet_id"],
               "timestamp_utc": rec["timestamp_utc"], "data_source": rec["data_source"],
               "quality": rec["quality"], "quality_flags": rec["quality_flags"],
               "derived_fields": rec["derived_fields"], "payload": rec["payload"], "live": result["live"],
               "status": {"connection": st.connection, "flight_phase": st.phase, "phase_since": st.phase_since,
                          "max_altitude": st.max_alt, "packet_count": st.packet_count}}
        await self.broadcast(st.mission_id, msg)
        for a in result["events"] + result["alerts"]:
            await self.broadcast(st.mission_id, {"type": "alert", "alert": a})

    async def broadcast(self, mission_id: str, message: dict):
        st = self.states.get(mission_id)
        if not st or not st.subscribers:
            return
        text = json.dumps(message, default=str)
        dead = []
        for ws in list(st.subscribers):
            try:
                await ws.send_text(text)
            except Exception:  # noqa: BLE001
                dead.append(ws)
        for ws in dead:
            st.subscribers.discard(ws)

    # ----------------------------------------------------------- reads
    @staticmethod
    def _row_to_packet(row: dict) -> dict:
        body = json.loads(row["payload_json"])
        return {"mission_id": row["mission_id"], "packet_id": row["packet_id"],
                "timestamp_utc": row["timestamp_utc"], "received_utc": row["received_utc"],
                "data_source": row["data_source"], "quality": row["quality"],
                "quality_flags": json.loads(row["quality_flags"]),
                "derived_fields": body.get("derived_fields", []), "payload": body.get("payload", {}),
                "telemetry_id": row.get("telemetry_id"), "entry_method": row.get("entry_method", "API"),
                "superseded_by": row.get("superseded_by")}

    def history(self, mission_id: str, start: str | None, end: str | None, limit: int, offset: int,
                include_invalid: bool = True, include_superseded: bool = False) -> dict:
        sql = "SELECT * FROM telemetry WHERE mission_id=?"
        if not include_superseded:
            sql += " AND superseded_by IS NULL"
        params: list = [mission_id]
        if start:
            sql += " AND timestamp_utc >= ?"
            params.append(iso(parse_iso(start)))
        if end:
            sql += " AND timestamp_utc <= ?"
            params.append(iso(parse_iso(end)))
        if not include_invalid:
            sql += " AND quality != 'INVALID'"
        total = db.query_one(sql.replace("SELECT *", "SELECT COUNT(*) AS n"), params)["n"]
        rows = db.query(sql + " ORDER BY timestamp_utc ASC LIMIT ? OFFSET ?", params + [limit, offset])
        return {"total": total, "offset": offset, "limit": limit, "items": [self._row_to_packet(r) for r in rows]}


hub = TelemetryHub()
