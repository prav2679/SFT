"""Mission lifecycle used by mission-history management.

ACTIVE     - in flight (ASCENT/FLOAT/DESCENT) for a LIVE mission, or a simulation currently RUNNING/PAUSED.
             Active missions cannot be deleted; they must first be terminated (ground-segment abort).
COMPLETED  - landed, or a SIMULATION mission whose simulation is finished/stopped.
ABORTED    - terminated by the operator in the ground segment (no command is ever sent to the balloon).
PRE-LAUNCH - no flight started yet.
"""
from __future__ import annotations

import json

from core import simulator

FLIGHT = ("ASCENT", "FLOAT", "DESCENT")


def mission_type(row: dict, cfg: dict) -> str:
    kind = "Super-pressure float" if cfg.get("burst_expected") is False else "Latex burst"
    return f"{'Live' if row['mode'] == 'LIVE' else 'Simulation'} - {kind}"


def lifecycle(row: dict) -> dict:
    sim = simulator.status(row["mission_id"])
    sim_running = bool(sim) and sim.get("state") in ("RUNNING", "PAUSED")
    phase = row.get("flight_phase") or "PRE-LAUNCH"
    if phase == "ABORTED":
        status = "ABORTED"
    elif sim_running or (phase in FLIGHT and row["mode"] == "LIVE"):
        status = "ACTIVE"
    elif phase == "LANDED" or (phase in FLIGHT and row["mode"] == "SIMULATION"):
        status = "COMPLETED"
    else:
        status = "PRE-LAUNCH"
    return {"status": status, "active": status == "ACTIVE", "simulation_state": (sim or {}).get("state")}


def decorate(row: dict, cfg: dict | None = None) -> dict:
    cfg = cfg if cfg is not None else json.loads(row.get("config_json") or "{}")
    lc = lifecycle(row)
    row["lifecycle_status"], row["active"] = lc["status"], lc["active"]
    row["mission_type"] = mission_type(row, cfg)
    row["last_updated"] = row.get("updated_at") or row.get("created_at")
    return row
