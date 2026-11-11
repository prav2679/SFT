"""Orchestrator for the ORIGINAL Tawhiri Downloader (OCaml/Dune, main.exe).

The downloader is NOT re-implemented. This module starts the preserved
executable with its documented command line:

    main.exe one -directory <TAWHIRI_DATA_DIR> -base-url nomads|aws-mirror \
                 -log-level info <YYYYMMDDHH>

and supervises it: progress/log capture, completion check, output-file
verification (size must equal the 4-variable layout), failure reporting and
avoidance of repeated downloads when a valid dataset already exists.
Downloader failures are reported as DOWNLOADER errors - never as engine
failures.
"""
from __future__ import annotations

import asyncio
import collections
import re
from datetime import datetime, timezone

import config
from core import weather
from core.db import iso, utcnow

CYCLE_RE = re.compile(r"^\d{10}$")


class DownloaderState:
    def __init__(self):
        self.status = "IDLE"          # IDLE|RUNNING|COMPLETED|FAILED|CANCELLED|SKIPPED_ALREADY_AVAILABLE
        self.cycle: str | None = None
        self.started: datetime | None = None
        self.finished: datetime | None = None
        self.return_code: int | None = None
        self.message = ""
        self.log = collections.deque(maxlen=400)
        self.proc: asyncio.subprocess.Process | None = None
        self.verification: dict | None = None

    def as_dict(self) -> dict:
        return {
            "status": self.status, "cycle": self.cycle, "started_utc": iso(self.started),
            "finished_utc": iso(self.finished), "return_code": self.return_code, "message": self.message,
            "verification": self.verification, "log_tail": list(self.log)[-60:],
            "executable": str(config.TAWHIRI_DOWNLOADER_EXE),
            "executable_present": config.TAWHIRI_DOWNLOADER_EXE.exists(),
            "base_url": config.TAWHIRI_DOWNLOADER_BASE_URL,
        }


STATE = DownloaderState()


def expected_latest_cycle(now: datetime | None = None) -> str:
    """Most recent 00/06/12/18Z cycle at least ~4.5 h old (GFS release latency)."""
    now = now or datetime.now(timezone.utc)
    t = now.replace(minute=0, second=0, microsecond=0)
    from datetime import timedelta
    t -= timedelta(hours=4, minutes=30)
    t = t.replace(hour=(t.hour // 6) * 6, minute=0)
    return t.strftime("%Y%m%d%H")


def verify(cycle: str) -> dict:
    match = next((d for d in weather.list_datasets() if d.cycle == cycle), None)
    if match is None:
        return {"ok": False, "reason": f"Dataset file {cycle} not found in {config.TAWHIRI_DATA_DIR}"}
    return {"ok": match.status == "VALID", "status": match.status, "size_bytes": match.size,
            "expected_size_bytes": config.DATASET_SIZE_BYTES, "path": str(match.path)}


async def start(cycle: str, force: bool = False) -> dict:
    if not CYCLE_RE.match(cycle or ""):
        raise ValueError("Forecast cycle must be YYYYMMDDHH")
    if int(cycle[-2:]) % 6:
        raise ValueError("GFS forecast cycles are 00, 06, 12 or 18 UTC")
    if STATE.status == "RUNNING":
        if STATE.cycle == cycle:
            return STATE.as_dict()
        raise RuntimeError(f"Downloader already running for cycle {STATE.cycle}")
    existing = verify(cycle)
    if existing.get("ok") and not force:
        STATE.status, STATE.cycle = "SKIPPED_ALREADY_AVAILABLE", cycle
        STATE.message = "A valid dataset for this cycle already exists - download not repeated."
        STATE.verification = existing
        return STATE.as_dict()
    if not config.TAWHIRI_DOWNLOADER_EXE.exists():
        STATE.status, STATE.cycle = "FAILED", cycle
        STATE.message = (f"Downloader executable not found at {config.TAWHIRI_DOWNLOADER_EXE}. Build it with "
                         "'dune build --profile=release main.exe' in tawhiri/tawhiri-downloader "
                         "(see its README) or set TAWHIRI_DOWNLOADER_EXE.")
        return STATE.as_dict()
    config.TAWHIRI_DATA_DIR.mkdir(parents=True, exist_ok=True)
    cmd = [str(config.TAWHIRI_DOWNLOADER_EXE), "one", "-directory", str(config.TAWHIRI_DATA_DIR),
           "-base-url", config.TAWHIRI_DOWNLOADER_BASE_URL, "-log-level", "info", cycle]
    STATE.__init__()
    STATE.status, STATE.cycle, STATE.started = "RUNNING", cycle, utcnow()
    STATE.message = "Downloader started"
    STATE.log.append("$ " + " ".join(cmd))
    try:
        STATE.proc = await asyncio.create_subprocess_exec(
            *cmd, cwd=str(config.TAWHIRI_DOWNLOADER_DIR),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    except OSError as exc:
        STATE.status, STATE.message, STATE.finished = "FAILED", f"Could not start downloader: {exc}", utcnow()
        return STATE.as_dict()
    asyncio.create_task(_supervise(cycle))
    return STATE.as_dict()


async def _supervise(cycle: str):
    proc = STATE.proc
    assert proc and proc.stdout
    log_file = open(config.LOG_DIR / f"tawhiri-download-{cycle}.log", "a", encoding="utf-8")
    try:
        async for raw in proc.stdout:
            line = raw.decode(errors="replace").rstrip()
            STATE.log.append(line)
            log_file.write(line + "\n")
            log_file.flush()
            if line:
                STATE.message = line[-200:]
        STATE.return_code = await proc.wait()
    finally:
        log_file.close()
    STATE.finished = utcnow()
    if STATE.status == "CANCELLED":
        return
    STATE.verification = verify(cycle)
    if STATE.return_code == 0 and STATE.verification.get("ok"):
        STATE.status, STATE.message = "COMPLETED", f"Cycle {cycle} downloaded and verified"
    else:
        STATE.status = "FAILED"
        STATE.message = (f"Downloader exited with code {STATE.return_code}; verification: "
                         f"{STATE.verification.get('status') or STATE.verification.get('reason')}")


async def cancel() -> dict:
    if STATE.status == "RUNNING" and STATE.proc and STATE.proc.returncode is None:
        STATE.status, STATE.message = "CANCELLED", "Cancelled by operator (SIGTERM sent)"
        STATE.proc.terminate()   # downloader handles SIGTERM via Signal.handle
    return STATE.as_dict()


def status() -> dict:
    d = STATE.as_dict()
    d["expected_latest_cycle"] = expected_latest_cycle()
    return d
