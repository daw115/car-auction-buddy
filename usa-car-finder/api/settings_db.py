"""SQLite store dla globalnych ustawień operatora (np. domyślne kryteria wyszukiwania).

Prosty key-value store — jeden wiersz per klucz, wartość jako JSON string.
Wzorzec mirrorowany z watch_queue_db.py (thread-lock + sqlite3.Row + proste CRUD).
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from pathlib import Path
from typing import Optional

_lock = threading.Lock()
_db_path: Optional[Path] = None


def _default_db_path() -> Path:
    return Path(os.getenv("SETTINGS_DB_PATH", "data/settings.db"))


def _connect() -> sqlite3.Connection:
    path = _db_path or _default_db_path()
    conn = sqlite3.connect(str(path), timeout=10.0)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Optional[Path] = None) -> None:
    global _db_path
    with _lock:
        _db_path = (db_path or _default_db_path()).resolve()
        _db_path.parent.mkdir(parents=True, exist_ok=True)
        with _connect() as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )"""
            )


def get(key: str) -> Optional[str]:
    with _lock, _connect() as conn:
        row = conn.execute("SELECT value_json FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value_json"] if row else None


def set(key: str, value_json: str, updated_at: str) -> None:
    with _lock, _connect() as conn:
        conn.execute(
            """INSERT INTO settings (key, value_json, updated_at) VALUES (?, ?, ?)
               ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json, updated_at = excluded.updated_at""",
            (key, value_json, updated_at),
        )


_AI_PROVIDER_OVERRIDES_KEY = "ai_provider_overrides"


def get_ai_provider_overrides() -> dict:
    """Zwraca {task_key: provider_name} nadpisań ustawionych z dashboardu.
    Brak klucza w wyniku = ta funkcja czyta z .env (domyślne zachowanie)."""
    raw = get(_AI_PROVIDER_OVERRIDES_KEY)
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def get_ai_provider_override(task_key: str) -> Optional[str]:
    """Provider wybrany z dashboardu dla danego zadania, albo None (= użyj .env).

    Odczyt jest synchroniczny (SQLite lokalny, <1ms) — bezpieczny do wołania
    bezpośrednio z funkcji dispatchujących provider (ai/*.py, report/*.py)
    bez zmiany ich na async.
    """
    return get_ai_provider_overrides().get(task_key) or None


def set_ai_provider_overrides(overrides: dict, updated_at: str) -> None:
    set(_AI_PROVIDER_OVERRIDES_KEY, json.dumps(overrides), updated_at)


_AI_MODEL_OVERRIDES_KEY = "ai_model_overrides"


def get_ai_model_overrides() -> dict:
    """Zwraca {provider_name: model_name} — np. {'kiro': 'claude-sonnet-5'}.
    Globalne per-provider (nie per-zadanie), bo model env vars (KIRO_MODEL,
    GEMINI_MODEL, ANTHROPIC_MODEL) są już współdzielone przez wszystkie
    zadania w kodzie — to odzwierciedla istniejącą architekturę."""
    raw = get(_AI_MODEL_OVERRIDES_KEY)
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def get_ai_model_override(provider: str) -> Optional[str]:
    """Model wybrany z dashboardu dla danego providera, albo None (= użyj .env)."""
    return get_ai_model_overrides().get(provider) or None


def set_ai_model_overrides(overrides: dict, updated_at: str) -> None:
    set(_AI_MODEL_OVERRIDES_KEY, json.dumps(overrides), updated_at)


_PIPELINE_FILTER_OVERRIDES_KEY = "pipeline_filter_overrides"


def get_pipeline_filter_overrides() -> dict:
    """Zwraca {filter_key: bool} nadpisań filtrów systemowych (scraper) —
    np. {'seller_insurance_only': False, 'exclude_convertible': True}.
    Brak klucza = ta funkcja czyta z .env (domyślne zachowanie)."""
    raw = get(_PIPELINE_FILTER_OVERRIDES_KEY)
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def get_pipeline_filter_override(filter_key: str) -> Optional[bool]:
    """Wartość bool wybrana z dashboardu dla danego filtra, albo None (= użyj .env)."""
    overrides = get_pipeline_filter_overrides()
    if filter_key not in overrides:
        return None
    return bool(overrides[filter_key])


def set_pipeline_filter_overrides(overrides: dict, updated_at: str) -> None:
    set(_PIPELINE_FILTER_OVERRIDES_KEY, json.dumps(overrides), updated_at)
