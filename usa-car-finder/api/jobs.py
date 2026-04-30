"""In-memory job store for /search async execution + SSE streaming.

Lokalny FastAPI obsługuje pojedynczy proces; wystarczy dict + asyncio.Queue per job.
"""
import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Optional

logger = logging.getLogger("api.jobs")

JobStatus = str  # "queued" | "running" | "done" | "error" | "cancelled"
PhaseStatus = str  # "running" | "done" | "blocked" | "error" | "skipped" | "cancelled"


@dataclass
class Phase:
    name: str
    status: PhaseStatus = "running"
    info: dict = field(default_factory=dict)
    started_at: str = field(default_factory=lambda: datetime.utcnow().isoformat(timespec="seconds"))
    finished_at: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "status": self.status,
            "info": self.info,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


@dataclass
class Job:
    id: str
    status: JobStatus = "queued"
    phases: list[Phase] = field(default_factory=list)
    result: Optional[dict] = None
    error: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat(timespec="seconds"))
    finished_at: Optional[str] = None
    cancel_requested: bool = False
    task: Optional[asyncio.Task] = None
    criteria_hash: Optional[str] = None
    request_snapshot: Optional[dict] = None
    _queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    _subscribers: int = 0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "status": self.status,
            "phases": [p.to_dict() for p in self.phases],
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at,
            "finished_at": self.finished_at,
            "cancel_requested": self.cancel_requested,
            "criteria_hash": self.criteria_hash,
        }

    def to_db_row(self) -> dict:
        import json as _json
        return {
            "id": self.id,
            "status": self.status,
            "phases_json": _json.dumps([p.to_dict() for p in self.phases], ensure_ascii=False),
            "result_json": _json.dumps(self.result, ensure_ascii=False) if self.result is not None else None,
            "error": self.error,
            "created_at": self.created_at,
            "finished_at": self.finished_at,
            "cancel_requested": 1 if self.cancel_requested else 0,
            "criteria_hash": self.criteria_hash,
            "request_json": _json.dumps(self.request_snapshot, ensure_ascii=False) if self.request_snapshot else None,
        }


_jobs: dict[str, Job] = {}
_lock = asyncio.Lock()


def create_job(criteria_hash: Optional[str] = None, request_snapshot: Optional[dict] = None) -> Job:
    job = Job(id=uuid.uuid4().hex[:12], criteria_hash=criteria_hash, request_snapshot=request_snapshot)
    _jobs[job.id] = job
    _persist(job)
    return job


def _persist(job: Job) -> None:
    """Synchroniczny upsert do SQLite — wołany z asyncio przez to_thread w mark_*"""
    try:
        from api import job_db
        job_db.persist_job(job.to_db_row())
    except Exception:
        logger.exception("persist_job failed for %s", job.id)


def hydrate_jobs_from_db() -> int:
    """Po starcie API: ładuje persystowane joby (status final) jako read-only.

    'queued'/'running' z poprzedniego procesu były właśnie oznaczone jako
    'interrupted' przez mark_orphaned_running_as_interrupted, więc hydratujemy
    je w stanie końcowym. Bez asyncio.task — task=None, _queue puste.
    """
    import json as _json
    try:
        from api import job_db
        rows = job_db.load_all_rows()
    except Exception:
        logger.exception("hydrate_jobs_from_db failed")
        return 0

    loaded = 0
    for row in rows:
        if row["id"] in _jobs:
            continue
        phases = []
        try:
            for ph in _json.loads(row.get("phases_json") or "[]"):
                phases.append(Phase(
                    name=ph["name"], status=ph.get("status", "done"),
                    info=ph.get("info") or {},
                    started_at=ph.get("started_at") or row["created_at"],
                    finished_at=ph.get("finished_at"),
                ))
        except Exception:
            phases = []
        result = _json.loads(row["result_json"]) if row.get("result_json") else None
        request_snapshot = _json.loads(row["request_json"]) if row.get("request_json") else None
        job = Job(
            id=row["id"],
            status=row["status"],
            phases=phases,
            result=result,
            error=row.get("error"),
            created_at=row["created_at"],
            finished_at=row.get("finished_at"),
            cancel_requested=bool(row.get("cancel_requested")),
            criteria_hash=row.get("criteria_hash"),
            request_snapshot=request_snapshot,
        )
        _jobs[job.id] = job
        loaded += 1
    return loaded


def find_reusable_job(criteria_hash: str, ttl_seconds: int) -> Optional[Job]:
    """Zwraca job nadający się do re-use lub None.

    Najpierw szuka in-memory (świeżych), potem DB (po restarcie).
    """
    if not criteria_hash:
        return None

    # in-memory: running zawsze, done w oknie TTL
    now = datetime.utcnow()
    candidates_running = [j for j in _jobs.values() if j.criteria_hash == criteria_hash and j.status == "running"]
    if candidates_running:
        return max(candidates_running, key=lambda j: j.created_at)

    candidates_done = [j for j in _jobs.values() if j.criteria_hash == criteria_hash and j.status == "done" and j.finished_at]
    fresh = [j for j in candidates_done
             if (now - datetime.fromisoformat(j.finished_at)).total_seconds() <= ttl_seconds]
    if fresh:
        return max(fresh, key=lambda j: j.finished_at or "")

    # fallback: DB (np. po restarcie joba 'done' jeszcze nie ma w pamięci, dopóki ktoś go nie pobierze)
    try:
        from api import job_db
        row = job_db.find_reusable_row(criteria_hash, ttl_seconds)
    except Exception:
        logger.exception("find_reusable_row failed")
        row = None
    if row is None:
        return None
    # hydratuj pojedynczy rekord
    hydrate_jobs_from_db()
    return _jobs.get(row["id"])


def get_job(job_id: str) -> Optional[Job]:
    return _jobs.get(job_id)


async def _publish(job: Job, event: dict) -> None:
    await job._queue.put(event)


def progress_callback(job: Job) -> Callable[[str, dict], None]:
    """Zwraca synchroniczny callback do przekazania scraperowi.

    Scraper woła go bez awaita; my schedulujemy publikację na event loopie joba.
    """
    loop = asyncio.get_running_loop()

    def _cb(phase_name: str, info: Optional[dict] = None) -> None:
        info = info or {}
        status: PhaseStatus = info.pop("_status", "running")
        finished = info.pop("_finished", False)
        existing = next((p for p in job.phases if p.name == phase_name), None)
        if existing is None:
            existing = Phase(name=phase_name, status=status, info=info)
            job.phases.append(existing)
        else:
            existing.status = status
            if info:
                existing.info.update(info)
        if finished or status in ("done", "blocked", "error", "skipped"):
            existing.finished_at = datetime.utcnow().isoformat(timespec="seconds")
        event = {"type": "phase", "phase": existing.to_dict()}
        # Persist faz tylko gdy faza się skończyła (started/intermediate update'y nie warto bić DB)
        if finished or status in ("done", "blocked", "error", "skipped", "cancelled"):
            _persist(job)
        try:
            asyncio.run_coroutine_threadsafe(_publish(job, event), loop)
        except RuntimeError:
            logger.debug("progress callback called outside loop", exc_info=True)

    return _cb


async def mark_running(job: Job) -> None:
    job.status = "running"
    _persist(job)
    await _publish(job, {"type": "status", "status": "running"})


async def mark_done(job: Job, result: dict) -> None:
    job.status = "done"
    job.result = result
    job.finished_at = datetime.utcnow().isoformat(timespec="seconds")
    _persist(job)
    await _publish(job, {"type": "status", "status": "done"})
    await _publish(job, {"type": "__end__"})


async def mark_error(job: Job, error: str) -> None:
    job.status = "error"
    job.error = error
    job.finished_at = datetime.utcnow().isoformat(timespec="seconds")
    _persist(job)
    await _publish(job, {"type": "status", "status": "error", "error": error})
    await _publish(job, {"type": "__end__"})


async def mark_cancelled(job: Job) -> None:
    job.status = "cancelled"
    job.finished_at = datetime.utcnow().isoformat(timespec="seconds")
    for phase in job.phases:
        if phase.status == "running":
            phase.status = "cancelled"
            phase.finished_at = job.finished_at
    _persist(job)
    await _publish(job, {"type": "status", "status": "cancelled"})
    await _publish(job, {"type": "__end__"})


def request_cancel(job: Job) -> bool:
    """Oznacza job jako anulowany i ubija task. Zwraca True jeśli było co anulować."""
    if job.status in ("done", "error", "cancelled"):
        return False
    job.cancel_requested = True
    if job.task is not None and not job.task.done():
        job.task.cancel()
        return True
    return False


async def stream_events(job: Job):
    """Async generator dla SSE — emituje wszystkie dotychczasowe fazy + nowe.

    Po otrzymaniu zdarzenia "__end__" generator kończy.
    """
    job._subscribers += 1
    try:
        # replay aktualnego stanu, żeby klient łączący się późno dostał pełen obraz
        yield {"type": "status", "status": job.status}
        for phase in job.phases:
            yield {"type": "phase", "phase": phase.to_dict()}
        if job.status in ("done", "error"):
            yield {"type": "__end__"}
            return

        while True:
            event = await job._queue.get()
            if event.get("type") == "__end__":
                yield event
                return
            yield event
    finally:
        job._subscribers -= 1
