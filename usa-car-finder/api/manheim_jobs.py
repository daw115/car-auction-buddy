"""
Kolejka zadań wyszukiwania dla rozszerzenia manheim-collector.

Backend nie może sam odpytać Manheima — sesję trzyma BidWise przez
chrome.debugger, a podpięcie się tam zamyka kartę (zmierzone: ~5 s). Odwracamy
więc kierunek: backend zostawia zadanie, rozszerzenie je odbiera i wykonuje
w kontekście zalogowanej strony, po czym odsyła wyniki na /api/manheim/ingest.

Kolejka jest w pamięci procesu i celowo malutka: zadanie żyje kilkadziesiąt
sekund, a nieodebrane wygasa. Trwałość byłaby tu zbędna — jak backend padnie,
wyszukiwanie i tak trzeba powtórzyć.
"""
import logging
import os
import threading
import time
import uuid
from typing import Any, Optional

logger = logging.getLogger("api.manheim_jobs")

_lock = threading.Lock()
_jobs: dict[str, dict] = {}


def job_ttl_seconds() -> float:
    return max(15.0, float(os.getenv("MANHEIM_JOB_TTL_SECONDS", "120")))


def lease_seconds() -> float:
    """Ile czekamy na rozszerzenie, zanim uznamy zadanie za porzucone.

    Rozszerzenie potrafi zniknąć w środku (service worker usypia, operator
    zamyka kartę), więc wydane zadanie musi móc wrócić do kolejki.
    """
    return max(10.0, float(os.getenv("MANHEIM_JOB_LEASE_SECONDS", "45")))


def _prune_locked() -> None:
    now = time.time()
    expired = [
        job_id
        for job_id, job in _jobs.items()
        if now - job["createdAt"] > job_ttl_seconds()
    ]
    for job_id in expired:
        _jobs.pop(job_id, None)

    # Zadanie wydane, ale nieodesłane w terminie — wraca do kolejki.
    for job in _jobs.values():
        if job["status"] == "running" and now - job["leasedAt"] > lease_seconds():
            logger.warning("[manheim-jobs] %s: brak odpowiedzi, wracam do kolejki", job["id"])
            job["status"] = "pending"


def create(keyword: str) -> str:
    job_id = str(uuid.uuid4())
    with _lock:
        _prune_locked()
        _jobs[job_id] = {
            "id": job_id,
            "keyword": keyword,
            "status": "pending",
            "createdAt": time.time(),
            "leasedAt": 0.0,
            "records": [],
            "error": None,
        }
    logger.info("[manheim-jobs] nowe zadanie %s: %r", job_id, keyword)
    return job_id


def next_pending() -> Optional[dict]:
    with _lock:
        _prune_locked()
        for job in sorted(_jobs.values(), key=lambda item: item["createdAt"]):
            if job["status"] == "pending":
                job["status"] = "running"
                job["leasedAt"] = time.time()
                return {"id": job["id"], "keyword": job["keyword"]}
    return None


def complete(job_id: str, records: list[dict], error: Optional[str] = None) -> bool:
    with _lock:
        job = _jobs.get(job_id)
        if job is None:
            return False
        job["records"] = records
        job["error"] = error
        job["status"] = "error" if error else "done"
    logger.info(
        "[manheim-jobs] %s zakończone: %d rekordów%s",
        job_id,
        len(records),
        f", błąd: {error}" if error else "",
    )
    return True


def get(job_id: str) -> Optional[dict]:
    with _lock:
        job = _jobs.get(job_id)
        return dict(job) if job else None


def status() -> dict[str, Any]:
    with _lock:
        _prune_locked()
        counts: dict[str, int] = {}
        for job in _jobs.values():
            counts[job["status"]] = counts.get(job["status"], 0) + 1
        return {"jobs": len(_jobs), "byStatus": counts}


def clear() -> None:
    with _lock:
        _jobs.clear()
