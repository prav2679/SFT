"""SQLite storage for missions, telemetry, alerts, predictions and simulations.

No database existed in the inspected project, so this structured store was
introduced (see docs/INTEGRATION_PLAN.md). All timestamps are stored as
ISO-8601 UTC strings, which sort lexicographically, enabling indexed
time-range queries.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterable

from config import DB_PATH

_LOCK = threading.RLock()

SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS missions (
    mission_id TEXT PRIMARY KEY,
    balloon_id TEXT NOT NULL,
    mission_name TEXT NOT NULL,
    mode TEXT NOT NULL CHECK (mode IN ('LIVE','SIMULATION')),
    launch_time TEXT,
    mission_status TEXT NOT NULL DEFAULT 'PRE-LAUNCH',
    flight_phase TEXT NOT NULL DEFAULT 'PRE-LAUNCH',
    phase_since TEXT,
    launch_latitude REAL,
    launch_longitude REAL,
    launch_altitude REAL,
    config_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS telemetry (
    telemetry_id INTEGER PRIMARY KEY AUTOINCREMENT,
    mission_id TEXT NOT NULL REFERENCES missions(mission_id),
    packet_id TEXT NOT NULL,
    timestamp_utc TEXT NOT NULL,
    received_utc TEXT NOT NULL,
    latitude REAL, longitude REAL, gps_altitude REAL,
    vertical_velocity REAL, ground_speed REAL, heading REAL,
    ambient_temperature REAL, atmospheric_pressure REAL,
    internal_gas_temperature REAL, envelope_temperature REAL,
    internal_pressure REAL, differential_pressure REAL,
    battery_voltage REAL, battery_current REAL,
    sensor_status TEXT,
    data_source TEXT NOT NULL CHECK (data_source IN ('MEASURED','SIMULATED')),
    quality TEXT NOT NULL CHECK (quality IN ('VALID','DEGRADED','INVALID','STALE')),
    quality_flags TEXT NOT NULL DEFAULT '[]',
    payload_json TEXT NOT NULL,
    UNIQUE (mission_id, packet_id)
);
CREATE INDEX IF NOT EXISTS ix_telemetry_mission_time ON telemetry (mission_id, timestamp_utc);
CREATE TABLE IF NOT EXISTS alerts (
    alert_id TEXT PRIMARY KEY,
    mission_id TEXT NOT NULL,
    timestamp_utc TEXT NOT NULL,
    category TEXT NOT NULL,
    severity TEXT NOT NULL CHECK (severity IN ('CRITICAL','WARNING','INFO')),
    parameter TEXT,
    measured_value REAL,
    threshold REAL,
    description TEXT NOT NULL,
    data_source TEXT,
    acknowledged INTEGER NOT NULL DEFAULT 0,
    acknowledged_at TEXT,
    acknowledged_by TEXT
);
CREATE INDEX IF NOT EXISTS ix_alerts_mission_time ON alerts (mission_id, timestamp_utc);
CREATE TABLE IF NOT EXISTS predictions (
    prediction_id INTEGER PRIMARY KEY AUTOINCREMENT,
    mission_id TEXT NOT NULL,
    prediction_set TEXT NOT NULL,
    timestamp_utc TEXT NOT NULL,
    predicted_latitude REAL, predicted_longitude REAL, predicted_altitude REAL,
    predicted_vertical_velocity REAL,
    predicted_wind_speed REAL, predicted_temperature REAL,
    phase TEXT,
    model_version TEXT,
    forecast_cycle TEXT
);
CREATE INDEX IF NOT EXISTS ix_pred_mission_set_time ON predictions (mission_id, prediction_set, timestamp_utc);
CREATE TABLE IF NOT EXISTS prediction_sets (
    prediction_set TEXT PRIMARY KEY,
    mission_id TEXT NOT NULL,
    created_utc TEXT NOT NULL,
    source TEXT NOT NULL,
    model_version TEXT,
    forecast_cycle TEXT,
    forecast_valid_from TEXT,
    forecast_valid_to TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS simulations (
    simulation_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    status TEXT NOT NULL,
    created_utc TEXT NOT NULL,
    started_utc TEXT, finished_utc TEXT,
    request_json TEXT NOT NULL,
    error TEXT,
    result_path TEXT
);
CREATE INDEX IF NOT EXISTS ix_sim_hash ON simulations (request_hash);
"""


# --------------------------------------------------------------------------
# Versioned migrations (PRAGMA user_version). Each step is applied exactly once,
# inside one transaction, and only ever ADDS columns/tables/triggers - existing
# rows are preserved and back-filled, never rewritten.
# --------------------------------------------------------------------------
MIGRATIONS: list[tuple[int, str, list[str]]] = [
    (1, "mission history management, telemetry reforecast versions, audit columns", [
        "ALTER TABLE missions ADD COLUMN updated_at TEXT",
        "ALTER TABLE simulations ADD COLUMN mission_id TEXT",
        "CREATE INDEX IF NOT EXISTS ix_sim_mission ON simulations (mission_id)",
        "ALTER TABLE prediction_sets ADD COLUMN version INTEGER",
        "ALTER TABLE prediction_sets ADD COLUMN kind TEXT NOT NULL DEFAULT 'ATTACHED'",
        "ALTER TABLE prediction_sets ADD COLUMN parent_set TEXT",
        "ALTER TABLE prediction_sets ADD COLUMN anchor_telemetry_id INTEGER",
        "ALTER TABLE prediction_sets ADD COLUMN anchor_timestamp TEXT",
        "ALTER TABLE prediction_sets ADD COLUMN anchor_phase TEXT",
        "ALTER TABLE telemetry ADD COLUMN entry_method TEXT NOT NULL DEFAULT 'API'",
        "ALTER TABLE telemetry ADD COLUMN superseded_by INTEGER",
        "ALTER TABLE telemetry ADD COLUMN corrects_telemetry_id INTEGER",
        "ALTER TABLE telemetry ADD COLUMN correction_reason TEXT",
        # Back-fill: updated_at from created_at; earliest prediction set per mission becomes V1 ORIGINAL,
        # later ones keep kind ATTACHED with increasing version numbers (nothing is deleted or altered otherwise).
        "UPDATE missions SET updated_at = created_at WHERE updated_at IS NULL",
        """UPDATE prediction_sets SET version = (
               SELECT COUNT(*) FROM prediction_sets b WHERE b.mission_id = prediction_sets.mission_id
               AND (b.created_utc < prediction_sets.created_utc
                    OR (b.created_utc = prediction_sets.created_utc AND b.rowid <= prediction_sets.rowid)))
           WHERE version IS NULL""",
        "UPDATE prediction_sets SET kind='ORIGINAL' WHERE version = 1",
        "CREATE TABLE IF NOT EXISTS _mission_deletion (mission_id TEXT PRIMARY KEY)",
        # Immutability guarantees enforced by the database itself.
        """CREATE TRIGGER IF NOT EXISTS trg_predictions_immutable_upd BEFORE UPDATE ON predictions
           BEGIN SELECT RAISE(ABORT, 'IMMUTABLE: prediction rows can never be modified'); END""",
        """CREATE TRIGGER IF NOT EXISTS trg_predictions_immutable_del BEFORE DELETE ON predictions
           WHEN NOT EXISTS (SELECT 1 FROM _mission_deletion WHERE mission_id = OLD.mission_id)
           BEGIN SELECT RAISE(ABORT, 'IMMUTABLE: prediction rows are deleted only with their mission'); END""",
        """CREATE TRIGGER IF NOT EXISTS trg_pred_sets_immutable_upd BEFORE UPDATE ON prediction_sets
           BEGIN SELECT RAISE(ABORT, 'IMMUTABLE: prediction versions can never be modified'); END""",
        """CREATE TRIGGER IF NOT EXISTS trg_pred_sets_immutable_del BEFORE DELETE ON prediction_sets
           WHEN NOT EXISTS (SELECT 1 FROM _mission_deletion WHERE mission_id = OLD.mission_id)
           BEGIN SELECT RAISE(ABORT, 'IMMUTABLE: prediction versions are deleted only with their mission'); END""",
        # Historical observations: only the audit link `superseded_by` may ever change.
        """CREATE TRIGGER IF NOT EXISTS trg_telemetry_immutable BEFORE UPDATE OF
               mission_id, packet_id, timestamp_utc, received_utc, latitude, longitude, gps_altitude,
               vertical_velocity, ground_speed, heading, ambient_temperature, atmospheric_pressure,
               internal_gas_temperature, envelope_temperature, internal_pressure, differential_pressure,
               battery_voltage, battery_current, sensor_status, data_source, quality, quality_flags,
               payload_json, entry_method, corrects_telemetry_id, correction_reason ON telemetry
           BEGIN SELECT RAISE(ABORT, 'IMMUTABLE: historical telemetry observations are never modified'); END""",
    ]),
]


def _migrate(conn: sqlite3.Connection) -> list[int]:
    applied = []
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    for version, _desc, statements in MIGRATIONS:
        if version <= current:
            continue
        try:
            conn.execute("BEGIN IMMEDIATE")
            for stmt in statements:
                conn.execute(stmt)
            conn.execute(f"PRAGMA user_version = {int(version)}")
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        applied.append(version)
    return applied


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_iso(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


_CONN: sqlite3.Connection | None = None


def init_db() -> None:
    global _CONN
    with _LOCK:
        _CONN = _connect()
        _CONN.isolation_level = None          # explicit transaction control during migration
        _CONN.executescript(SCHEMA)
        _migrate(_CONN)
        _CONN.isolation_level = ""            # restore default (implicit BEGIN before DML)


@contextmanager
def tx():
    with _LOCK:
        assert _CONN is not None, "init_db() not called"
        try:
            yield _CONN
            _CONN.commit()
        except Exception:
            _CONN.rollback()
            raise


def query(sql: str, params: Iterable[Any] = ()) -> list[dict]:
    with tx() as c:
        return [dict(r) for r in c.execute(sql, tuple(params)).fetchall()]


def query_one(sql: str, params: Iterable[Any] = ()) -> dict | None:
    rows = query(sql, params)
    return rows[0] if rows else None


def execute(sql: str, params: Iterable[Any] = ()) -> int:
    with tx() as c:
        cur = c.execute(sql, tuple(params))
        return cur.lastrowid


def executemany(sql: str, rows: list[tuple]) -> None:
    with tx() as c:
        c.executemany(sql, rows)


def dumps(obj: Any) -> str:
    return json.dumps(obj, default=str, allow_nan=False)


# --------------------------------------------------------------------------
# Mission deletion (single transaction, explicit cascade)
# --------------------------------------------------------------------------
def delete_mission_records(mission_ids: list[str]) -> dict:
    """Delete missions and EVERYTHING recorded for them, atomically.

    Removes: telemetry, alerts + events (events are alert rows), original and revised prediction
    versions with their point rows, per-mission simulation (re-forecast) job rows, and the mission rows.
    Never touches shared weather datasets or burst/forward calculator jobs that are not tied to a mission.
    Returns counts and the job ids whose result directories the caller should remove from disk.
    """
    counts = {"telemetry": 0, "alerts": 0, "predictions": 0, "prediction_sets": 0, "simulations": 0, "missions": 0}
    job_ids: list[str] = []
    if not mission_ids:
        return {"counts": counts, "job_ids": job_ids}
    with tx() as c:
        for mid in mission_ids:
            c.execute("INSERT OR IGNORE INTO _mission_deletion (mission_id) VALUES (?)", (mid,))
        try:
            for mid in mission_ids:
                job_ids += [r[0] for r in c.execute("SELECT simulation_id FROM simulations WHERE mission_id=?", (mid,))]
                counts["simulations"] += c.execute("DELETE FROM simulations WHERE mission_id=?", (mid,)).rowcount
                counts["telemetry"] += c.execute("DELETE FROM telemetry WHERE mission_id=?", (mid,)).rowcount
                counts["alerts"] += c.execute("DELETE FROM alerts WHERE mission_id=?", (mid,)).rowcount
                counts["predictions"] += c.execute("DELETE FROM predictions WHERE mission_id=?", (mid,)).rowcount
                counts["prediction_sets"] += c.execute("DELETE FROM prediction_sets WHERE mission_id=?", (mid,)).rowcount
                counts["missions"] += c.execute("DELETE FROM missions WHERE mission_id=?", (mid,)).rowcount
        finally:
            c.execute("DELETE FROM _mission_deletion")
    return {"counts": counts, "job_ids": job_ids}
