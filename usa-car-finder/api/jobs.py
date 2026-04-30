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
        }


_jobs: dict[str, Job] = {}
_lock = asyncio.Lock()


def create_job() -> Job:
    job = Job(id=uuid.uuid4().hex[:12])
    _jobs[job.id] = job
    return job


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
        try:
            asyncio.run_coroutine_threadsafe(_publish(job, event), loop)
        except RuntimeError:
            logger.debug("progress callback called outside loop", exc_info=True)

    return _cb


async def mark_running(job: Job) -> None:
    job.status = "running"
    await _publish(job, {"type": "status", "status": "running"})


async def mark_done(job: Job, result: dict) -> None:
    job.status = "done"
    job.result = result
    job.finished_at = datetime.utcnow().isoformat(timespec="seconds")
    await _publish(job, {"type": "status", "status": "done"})
    await _publish(job, {"type": "__end__"})


async def mark_error(job: Job, error: str) -> None:
    job.status = "error"
    job.error = error
    job.finished_at = datetime.utcnow().isoformat(timespec="seconds")
    await _publish(job, {"type": "status", "status": "error", "error": error})
    await _publish(job, {"type": "__end__"})


async def mark_cancelled(job: Job) -> None:
    job.status = "cancelled"
    job.finished_at = datetime.utcnow().isoformat(timespec="seconds")
    for phase in job.phases:
        if phase.status == "running":
            phase.status = "cancelled"
            phase.finished_at = job.finished_at
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
