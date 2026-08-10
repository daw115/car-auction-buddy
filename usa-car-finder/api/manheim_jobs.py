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
import json
import logging
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("api.manheim_jobs")

_lock = threading.Lock()
_jobs: dict[str, dict] = {}
# Szablony żądań podpatrzone przez kolektor — na dysku, nie tylko w pamięci.
# Sama pamięć procesu nie wystarcza: każdy deploy i restart usługi kasowałby je,
# a wtedy zlecenia padają aż ktoś ręcznie wyszuka coś w przeglądarce.
_templates: dict[str, dict] = {}
_templates_loaded = False


def templates_path() -> Path:
    return Path(os.getenv("MANHEIM_TEMPLATES_PATH", "./data/manheim_templates.json"))


def _load_templates_locked() -> None:
    """Wczytuje szablony z dysku raz na proces."""
    global _templates_loaded
    if _templates_loaded:
        return
    _templates_loaded = True
    path = templates_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if isinstance(data, dict):
        _templates.update(
            {k: v for k, v in data.items() if isinstance(v, dict) and v.get("url")}
        )
        logger.info("[manheim-jobs] wczytano szablony: %s", ", ".join(sorted(_templates)))


def _save_templates_locked() -> None:
    """Szablon niesie nagłówki autoryzacji strony, więc plik tylko dla właściciela."""
    path = templates_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(_templates, ensure_ascii=False), encoding="utf-8")
        path.chmod(0o600)
    except OSError as exc:
        logger.warning("[manheim-jobs] nie zapisałem szablonów do %s: %s", path, exc)


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


def store_templates(templates: dict) -> int:
    """Zapamiętuje szablony przysłane przez kolektor. Zwraca ile znanych."""
    with _lock:
        _load_templates_locked()
        changed = False
        for name, template in (templates or {}).items():
            if isinstance(template, dict) and template.get("url"):
                _templates[name] = template
                changed = True
        if changed:
            _save_templates_locked()
        return len(_templates)


def templates() -> dict[str, dict]:
    with _lock:
        _load_templates_locked()
        return dict(_templates)


def next_pending() -> Optional[dict]:
    with _lock:
        _load_templates_locked()
        _prune_locked()
        for job in sorted(_jobs.values(), key=lambda item: item["createdAt"]):
            if job["status"] == "pending":
                job["status"] = "running"
                job["leasedAt"] = time.time()
                # Szablony jadą razem ze zleceniem — hook w świeżo otwartej
                # karcie nie ma jeszcze własnych, a bez nich nie powtórzy
                # zapytania.
                return {
                    "id": job["id"],
                    "keyword": job["keyword"],
                    "templates": dict(_templates),
                }
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
        _load_templates_locked()
        _prune_locked()
        counts: dict[str, int] = {}
        for job in _jobs.values():
            counts[job["status"]] = counts.get(job["status"], 0) + 1
        return {
            "jobs": len(_jobs),
            "byStatus": counts,
            # Bez szablonu kolektor nie powtórzy wyszukiwania, więc to pierwsza
            # rzecz do sprawdzenia, gdy zlecenia zaczynają wracać puste.
            "templates": sorted(_templates),
        }


def clear() -> None:
    global _templates_loaded
    with _lock:
        _jobs.clear()
        _templates.clear()
        _templates_loaded = True  # test nie ma wczytywać stanu z dysku
