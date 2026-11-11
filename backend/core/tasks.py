"""Asynchronous simulation task manager.

* Every simulation runs in the background; the API returns a simulation_id.
* Identical requests (same kind + inputs + forecast cycle) are de-duplicated:
  a queued/running job is re-used, and a completed job's cached result is
  returned unless ``force`` is set.
* Model workers run as subprocesses (see workers/_common.py) so they can be
  cancelled, time-limited and isolated.
* Progress is read from the worker's progress.json.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import uuid
from pathlib import Path
from typing import Awaitable, Callable

import config
from core import db

WORKERS_DIR = config.BACKEND_DIR / "workers"
ACTIVE = ("QUEUED", "RUNNING")


class Task:
    def __init__(self, sim_id: str, kind: str, request: dict, request_hash: str):
        self.id = sim_id
        self.kind = kind
        self.request = request
        self.hash = request_hash
        self.dir = config.RESULTS_DIR / sim_id
        self.proc: asyncio.subprocess.Process | None = None
        self.future: asyncio.Task | None = None
        self.cancel_requested = False
        self.mission_id: str | None = None          # set for per-mission jobs (re-forecasts); deleted with the mission
        self.on_complete: Callable[["Task", dict], dict | None] | None = None   # server-side post-processing


class TaskManager:
    def __init__(self):
        self.tasks: dict[str, Task] = {}
        self.sem = asyncio.Semaphore(config.MAX_CONCURRENT_SIMULATIONS)

    # ------------------------------------------------------------ lifecycle
    def recover(self):
        db.execute("UPDATE simulations SET status='INTERRUPTED', error='Backend restarted during execution' "
                   "WHERE status IN ('QUEUED','RUNNING')")

    @staticmethod
    def hash_request(kind: str, request: dict) -> str:
        blob = json.dumps({"kind": kind, "request": request}, sort_keys=True, default=str)
        return hashlib.sha256(blob.encode()).hexdigest()

    def _existing(self, h: str, force: bool) -> dict | None:
        row = db.query_one("SELECT * FROM simulations WHERE request_hash=? ORDER BY created_utc DESC LIMIT 1", (h,))
        if not row:
            return None
        if row["status"] in ACTIVE and row["simulation_id"] in self.tasks:
            return row
        if row["status"] == "COMPLETED" and not force and Path(row["result_path"] or "").exists():
            return row
        return None

    def _create(self, kind: str, request: dict, force: bool, mission_id: str | None = None) -> tuple[Task, bool]:
        h = self.hash_request(kind, request)
        existing = self._existing(h, force)
        if existing:
            task = self.tasks.get(existing["simulation_id"]) or Task(existing["simulation_id"], kind, request, h)
            return task, True
        sim_id = f"{kind}-{uuid.uuid4().hex[:10]}"
        task = Task(sim_id, kind, request, h)
        task.mission_id = mission_id
        task.dir.mkdir(parents=True, exist_ok=True)
        (task.dir / "request.json").write_text(json.dumps(request, default=str, indent=2), encoding="utf-8")
        db.execute("INSERT INTO simulations (simulation_id, kind, request_hash, status, created_utc, request_json, "
                   "mission_id) VALUES (?,?,?,?,?,?,?)",
                   (sim_id, kind, h, "QUEUED", db.iso(db.utcnow()), db.dumps(request), mission_id))
        self.tasks[sim_id] = task
        return task, False

    # ------------------------------------------------------------ submit
    def submit_worker(self, kind: str, worker: str, request: dict, env: dict, force: bool = False,
                      timeout: float | None = None, mission_id: str | None = None,
                      on_complete: Callable[["Task", dict], dict | None] | None = None) -> dict:
        task, reused = self._create(kind, request, force, mission_id)
        if not reused:
            task.on_complete = on_complete
            task.future = asyncio.create_task(self._run_worker(task, worker, env, timeout or config.SIM_TIMEOUT_S))
        return {**self.status(task.id), "reused": reused}

    def submit_coroutine(self, kind: str, request: dict,
                         fn: Callable[[Task], Awaitable[dict]], force: bool = False) -> dict:
        task, reused = self._create(kind, request, force)
        if not reused:
            task.future = asyncio.create_task(self._run_coroutine(task, fn))
        return {**self.status(task.id), "reused": reused}

    async def _run_worker(self, task: Task, worker: str, env: dict, timeout: float):
        async with self.sem:
            if task.cancel_requested:
                return self._finish(task, "CANCELLED", "Cancelled before start")
            self._mark(task, "RUNNING")
            try:
                task.proc = await asyncio.create_subprocess_exec(
                    config.SFT_MODEL_PYTHON, str(WORKERS_DIR / worker), str(task.dir),
                    env=env, cwd=str(task.dir),
                    stdout=asyncio.subprocess.DEVNULL, stderr=open(task.dir / "worker_stderr.log", "wb"))
            except OSError as exc:
                return self._finish(task, "FAILED", f"Could not start model interpreter "
                                                    f"{config.SFT_MODEL_PYTHON}: {exc}")
            try:
                code = await asyncio.wait_for(task.proc.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                task.proc.kill()
                return self._finish(task, "FAILED", f"Simulation exceeded timeout of {timeout:.0f} s")
            if task.cancel_requested:
                return self._finish(task, "CANCELLED", "Cancelled by operator")
            if code == 0 and (task.dir / "result.json").exists():
                return self._finish(task, "COMPLETED", None)
            err = self._read_json(task.dir / "error.json") or {}
            if not err:
                tail = (task.dir / "worker_stderr.log").read_text(errors="replace")[-2000:]
                err = {"error_type": "WORKER_CRASH", "message": tail or f"Worker exited with code {code}"}
            return self._finish(task, "FAILED", json.dumps(err))

    async def _run_coroutine(self, task: Task, fn):
        async with self.sem:
            self._mark(task, "RUNNING")
            try:
                result = await fn(task)
                (task.dir / "result.json").write_text(json.dumps(result, default=str), encoding="utf-8")
                self._finish(task, "COMPLETED", None)
            except asyncio.CancelledError:
                self._finish(task, "CANCELLED", "Cancelled by operator")
            except Exception as exc:  # noqa: BLE001
                code = getattr(exc, "code", "ERROR")
                self._finish(task, "FAILED", json.dumps({"error_type": code, "message": str(exc),
                                                         "details": getattr(exc, "details", {})}))

    def _mark(self, task: Task, status: str):
        db.execute("UPDATE simulations SET status=?, started_utc=? WHERE simulation_id=?",
                   (status, db.iso(db.utcnow()), task.id))

    def _finish(self, task: Task, status: str, error: str | None):
        result_path = str(task.dir / "result.json") if status == "COMPLETED" else None
        db.execute("UPDATE simulations SET status=?, finished_utc=?, error=?, result_path=? WHERE simulation_id=?",
                   (status, db.iso(db.utcnow()), error, result_path, task.id))
        if status == "COMPLETED" and task.on_complete:
            # Server-side post-processing (e.g. storing a revised prediction version) must not depend on the
            # browser polling. Its outcome is recorded beside the job so the UI can show it.
            try:
                outcome = task.on_complete(task, self._read_json(task.dir / "result.json") or {}) or {}
                post = {"status": "OK", **outcome}
            except Exception as exc:  # noqa: BLE001
                post = {"status": "FAILED", "error": str(exc)}
            (task.dir / "post_process.json").write_text(json.dumps(post, default=str), encoding="utf-8")

    # ------------------------------------------------------------ queries
    @staticmethod
    def _read_json(path: Path):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def status(self, sim_id: str) -> dict:
        row = db.query_one("SELECT * FROM simulations WHERE simulation_id=?", (sim_id,))
        if not row:
            raise KeyError(sim_id)
        d = config.RESULTS_DIR / sim_id
        progress = self._read_json(d / "progress.json")
        err = row.get("error")
        try:
            err = json.loads(err) if err else None
        except ValueError:
            err = {"message": err}
        return {"simulation_id": sim_id, "kind": row["kind"], "status": row["status"],
                "created_utc": row["created_utc"], "started_utc": row["started_utc"],
                "finished_utc": row["finished_utc"], "progress": progress, "error": err,
                "mission_id": row.get("mission_id"), "post_process": self._read_json(d / "post_process.json"),
                "request": json.loads(row["request_json"])}

    def result(self, sim_id: str) -> dict | None:
        row = db.query_one("SELECT result_path, status FROM simulations WHERE simulation_id=?", (sim_id,))
        if not row or row["status"] != "COMPLETED":
            return None
        return self._read_json(Path(row["result_path"]))

    def file(self, sim_id: str, name: str) -> Path | None:
        p = (config.RESULTS_DIR / sim_id / name).resolve()
        if config.RESULTS_DIR.resolve() not in p.parents or not p.exists():
            return None
        return p

    def list(self, kind: str | None = None, limit: int = 50) -> list[dict]:
        sql = "SELECT simulation_id, kind, status, created_utc, finished_utc FROM simulations"
        params: tuple = ()
        if kind:
            sql += " WHERE kind=?"
            params = (kind,)
        return db.query(sql + " ORDER BY created_utc DESC LIMIT ?", params + (limit,))

    def cancel(self, sim_id: str) -> dict:
        task = self.tasks.get(sim_id)
        if not task:
            raise KeyError(sim_id)
        task.cancel_requested = True
        if task.proc and task.proc.returncode is None:
            task.proc.terminate()
        elif task.future and not task.future.done():
            task.future.cancel()
        return self.status(sim_id)

    def delete(self, sim_id: str):
        self.cancel(sim_id) if sim_id in self.tasks else None
        shutil.rmtree(config.RESULTS_DIR / sim_id, ignore_errors=True)
        db.execute("DELETE FROM simulations WHERE simulation_id=?", (sim_id,))

    def active_count(self) -> int:
        return db.query_one("SELECT COUNT(*) AS n FROM simulations WHERE status IN ('QUEUED','RUNNING')")["n"]


manager: TaskManager | None = None


def get_manager() -> TaskManager:
    global manager
    if manager is None:
        manager = TaskManager()
    return manager
