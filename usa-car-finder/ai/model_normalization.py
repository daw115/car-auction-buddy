"""Cache + weryfikacja normalizacji nazw modeli aut do formatu Copart/IAAI.

Klient pisze "BMW M440i coupé" — Copart/IAAI listują to jako "4 Series".
Pierwsza weryfikacja idzie do Anthropic Claude (przez RouteAI), wynik zapisujemy
w SQLite. Kolejne wystąpienia tej samej pary (make, original_text) = cache HIT, $0.

Tabela `model_normalizations` w `data/app.db`:
- make            TEXT  ('BMW')
- original_text   TEXT  ('BMW M440i coupé (2020-2022)' — oryginał od klienta)
- normalized_model TEXT ('4 Series')
- reason          TEXT  ('M440i to trim, nie model w Copart/IAAI')
- provider        TEXT  ('anthropic' / 'gemini')
- llm_model       TEXT  ('claude-sonnet-4-6')
- created_at      TEXT  ISO timestamp
- verified_count  INTEGER ile razy ten mapping został potwierdzony

UNIQUE(make, original_text) — idempotent upsert.
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sqlite3
import threading
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Optional

import anthropic
from dotenv import load_dotenv

logger = logging.getLogger("ai.model_normalization")

_ENV_FILE = Path(__file__).parent.parent / ".env"
if _ENV_FILE.exists():
    load_dotenv(_ENV_FILE, override=True)

_db_path: Optional[Path] = None
_lock = threading.Lock()
_initialized = False


def _default_db_path() -> Path:
    return Path(os.getenv("APP_DATABASE_PATH", "./data/app.db"))


def init_db(db_path: Optional[Path] = None) -> None:
    """Idempotentnie tworzy tabelę model_normalizations w app.db."""
    global _db_path, _initialized
    with _lock:
        _db_path = (db_path or _default_db_path()).resolve()
        _db_path.parent.mkdir(parents=True, exist_ok=True)
        with _connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS model_normalizations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    make TEXT NOT NULL,
                    original_text TEXT NOT NULL,
                    normalized_model TEXT NOT NULL,
                    reason TEXT,
                    provider TEXT,
                    llm_model TEXT,
                    verified_count INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(make, original_text)
                );
                CREATE INDEX IF NOT EXISTS idx_modnorm_make
                    ON model_normalizations(make COLLATE NOCASE);
                """
            )
        _initialized = True
        logger.info("[model_normalization] Zainicjalizowano %s", _db_path)


def _connect() -> sqlite3.Connection:
    if _db_path is None:
        raise RuntimeError("model_normalization.init_db() must be called first")
    conn = sqlite3.connect(str(_db_path), timeout=10.0)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_init() -> bool:
    if _initialized:
        return True
    try:
        init_db()
        return _initialized
    except Exception:
        logger.exception("[model_normalization] lazy init failed")
        return False


def _normalize_keys(make: str, original_text: str) -> tuple[str, str]:
    return (make or "").strip(), (original_text or "").strip()


def lookup(make: str, original_text: str) -> Optional[dict]:
    """Cache lookup. Zwraca dict {normalized_model, reason, provider, ...} albo None."""
    if not _initialized and not _ensure_init():
        return None
    make_n, orig_n = _normalize_keys(make, original_text)
    if not make_n or not orig_n:
        return None
    try:
        with _lock, _connect() as conn:
            row = conn.execute(
                "SELECT * FROM model_normalizations WHERE "
                "make = ? COLLATE NOCASE AND original_text = ? COLLATE NOCASE",
                (make_n, orig_n),
            ).fetchone()
    except Exception:
        logger.exception("[model_normalization] lookup failed")
        return None
    if not row:
        return None
    logger.info("[model_normalization] HIT %s :: %s -> %s", make_n, orig_n[:40], row["normalized_model"])
    return {k: row[k] for k in row.keys()}


def store(
    make: str,
    original_text: str,
    normalized_model: str,
    *,
    reason: Optional[str] = None,
    provider: Optional[str] = None,
    llm_model: Optional[str] = None,
) -> None:
    """Upsert normalizacji. Jeśli istnieje — increment verified_count + updated_at."""
    if not _initialized and not _ensure_init():
        return
    make_n, orig_n = _normalize_keys(make, original_text)
    if not make_n or not orig_n or not normalized_model:
        return
    now = datetime.utcnow().isoformat(timespec="seconds")
    try:
        with _lock, _connect() as conn:
            # Sprawdź czy istnieje (case-insensitive)
            existing = conn.execute(
                "SELECT id, normalized_model, verified_count FROM model_normalizations "
                "WHERE make = ? COLLATE NOCASE AND original_text = ? COLLATE NOCASE",
                (make_n, orig_n),
            ).fetchone()
            if existing:
                # Update verified_count i ewentualnie normalized_model jeśli się zmienił
                if existing["normalized_model"] != normalized_model:
                    logger.warning(
                        "[model_normalization] CONFLICT: %s '%s' bylo '%s', teraz '%s' (zachowuje stare)",
                        make_n, orig_n, existing["normalized_model"], normalized_model,
                    )
                    # Nie nadpisujemy — zachowujemy pierwotne mapping (deterministic)
                    conn.execute(
                        "UPDATE model_normalizations SET verified_count = verified_count + 1, "
                        "updated_at = ? WHERE id = ?",
                        (now, existing["id"]),
                    )
                else:
                    conn.execute(
                        "UPDATE model_normalizations SET verified_count = verified_count + 1, "
                        "updated_at = ? WHERE id = ?",
                        (now, existing["id"]),
                    )
            else:
                conn.execute(
                    "INSERT INTO model_normalizations "
                    "(make, original_text, normalized_model, reason, provider, llm_model, "
                    " verified_count, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)",
                    (make_n, orig_n, normalized_model, reason, provider, llm_model, now, now),
                )
                logger.info(
                    "[model_normalization] STORE %s '%s' -> '%s' (provider=%s)",
                    make_n, orig_n[:40], normalized_model, provider,
                )
    except Exception:
        logger.exception("[model_normalization] store failed")


def list_all(make: Optional[str] = None, limit: int = 100) -> list[dict]:
    """Lista znanych normalizacji. Filter by make optional."""
    if not _initialized and not _ensure_init():
        return []
    try:
        with _lock, _connect() as conn:
            if make:
                rows = conn.execute(
                    "SELECT * FROM model_normalizations WHERE make = ? COLLATE NOCASE "
                    "ORDER BY verified_count DESC, updated_at DESC LIMIT ?",
                    (make, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM model_normalizations "
                    "ORDER BY verified_count DESC, updated_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [{k: r[k] for k in r.keys()} for r in rows]
    except Exception:
        logger.exception("[model_normalization] list_all failed")
        return []


def delete_entry(entry_id: int) -> bool:
    """Usuwa pojedynczy wpis cache (force re-verification przy następnym wystąpieniu)."""
    if not _initialized and not _ensure_init():
        return False
    try:
        with _lock, _connect() as conn:
            cur = conn.execute("DELETE FROM model_normalizations WHERE id = ?", (entry_id,))
            return (cur.rowcount or 0) > 0
    except Exception:
        logger.exception("[model_normalization] delete failed")
        return False


def stats() -> dict:
    if not _initialized and not _ensure_init():
        return {"initialized": False}
    try:
        with _lock, _connect() as conn:
            total = conn.execute("SELECT COUNT(*) AS c FROM model_normalizations").fetchone()["c"]
            by_make = {
                r["make"]: r["c"]
                for r in conn.execute(
                    "SELECT make, COUNT(*) AS c FROM model_normalizations "
                    "GROUP BY make COLLATE NOCASE ORDER BY c DESC"
                ).fetchall()
            }
            top_used = [
                {k: r[k] for k in r.keys()}
                for r in conn.execute(
                    "SELECT make, original_text, normalized_model, verified_count "
                    "FROM model_normalizations ORDER BY verified_count DESC LIMIT 10"
                ).fetchall()
            ]
        return {
            "initialized": True,
            "total": total,
            "by_make": by_make,
            "top_used": top_used,
        }
    except Exception:
        logger.exception("[model_normalization] stats failed")
        return {"initialized": True, "error": "stats_failed"}


# ============================================================================
# Verification via Anthropic Claude (RouteAI proxy)
# ============================================================================

VERIFY_SYSTEM_PROMPT = """You are a JSON extraction API. You always respond with raw JSON object only, no prose, no markdown."""


VERIFY_USER_TEMPLATE = """Jesteś ekspertem od bazy aut Copart i IAAI. Zweryfikuj czy `model` jest poprawnym modelem listingowym w Copart/IAAI dla danej marki, a jeśli nie — zwróć bazową nazwę.

Marka: {make}
Klient napisał: {original_text}
{raw_model_line}
WYMAGANY OUTPUT (raw JSON, pierwszy znak `{{`, ostatni `}}`):
{{
  "normalized_model": "4 Series",
  "reason": "M440i to trim/wariant; Copart i IAAI listują pod 4 Series",
  "is_normalized": true
}}

ZASADY:
- "is_normalized": true gdy zmieniasz input, false gdy oryginalna nazwa była poprawna.
- Gdy uważasz że oryginalna nazwa modelu JEST POPRAWNA → `normalized_model` = ta sama wartość, `is_normalized` = false.
- Bez markdown, bez ```json``` tagów, bez prozy.
- Pierwszy znak `{{`, ostatni `}}`. Nic więcej.
"""


def _parse_normalize_response(raw: str, raw_model: Optional[str], provider: str, model_name: str) -> Optional[dict]:
    """Wspólny parser odpowiedzi LLM (dowolny provider) — strip markdown, loose JSON, heurystyka prozy."""
    raw = (raw or "").strip()
    if raw.startswith("```json"):
        raw = raw[7:]
    elif raw.startswith("```"):
        raw = raw[3:]
    if raw.endswith("```"):
        raw = raw[:-3]
    raw = raw.strip()

    data = None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # Fallback 1: regex-wyciągnij pierwszy {...} z prozy.
        # Niektóre proxy (oneprovider) zwraca "Tak, model X3 jest poprawny..."
        # zamiast czystego JSON. Wyciągamy JSON jeśli jest gdziekolwiek.
        match = re.search(r'\{[^{}]*"normalized_model"[^{}]*\}', raw, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(0))
            except json.JSONDecodeError:
                pass

    if data is None:
        # Fallback 2: heurystyka treści — gdy LLM mówi prozą że oryginalny model
        # jest poprawny ("Tak, X3 jest poprawny dla BMW..."), traktuj jako
        # is_normalized=false z tym samym modelem. Tylko gdy raw_model jest podany.
        raw_lower = raw.lower()
        confirm_keywords = ("poprawny", "jest ok", "valid", "is correct", "zgodny", "akceptowalny", "uznawany")
        if raw_model and any(k in raw_lower for k in confirm_keywords):
            logger.info(
                "[model_normalization] LLM zwrócił prozę z afirmacją — heurystyka: %r poprawny",
                raw_model,
            )
            return {
                "normalized_model": raw_model.strip(),
                "reason": "Heurystyka: LLM odpowiedział prozą potwierdzającą oryginalny model",
                "is_normalized": False,
                "provider": provider,
                "llm_model": model_name,
            }
        logger.warning("[model_normalization] JSON parse failed (no fallback match); raw=%r", raw[:200])
        return None

    return {
        "normalized_model": str(data.get("normalized_model", "")).strip() or None,
        "reason": str(data.get("reason", "")).strip() or None,
        "is_normalized": bool(data.get("is_normalized", False)),
        "provider": provider,
        "llm_model": model_name,
    }


def _verify_with_anthropic_impl(make: str, original_text: str, raw_model: Optional[str] = None) -> Optional[dict]:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        logger.warning("[model_normalization] Brak ANTHROPIC_API_KEY — nie mogę zweryfikować")
        return None

    base_url = os.getenv("ANTHROPIC_BASE_URL") or None
    timeout = int(os.getenv("ANTHROPIC_TIMEOUT_SECONDS", "60"))
    model_name = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")

    kwargs = {"api_key": api_key, "timeout": timeout, "max_retries": 1}
    if base_url:
        kwargs["base_url"] = base_url
    client = anthropic.Anthropic(**kwargs)

    raw_model_line = f"Sparsowany model: {raw_model}\n" if raw_model else ""
    user_msg = VERIFY_USER_TEMPLATE.format(
        make=make,
        original_text=original_text,
        raw_model_line=raw_model_line,
    )

    try:
        resp = client.messages.create(
            model=model_name,
            max_tokens=300,
            system=VERIFY_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
        )
    except Exception as exc:
        logger.warning("[model_normalization] Anthropic verify failed: %s", exc)
        return None

    chunks = [b.text for b in resp.content if b.type == "text"]
    return _parse_normalize_response("".join(chunks), raw_model, "anthropic", model_name)


def _verify_with_gemini_impl(make: str, original_text: str, raw_model: Optional[str] = None) -> Optional[dict]:
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        logger.warning("[model_normalization] Brak GEMINI_API_KEY — nie mogę zweryfikować")
        return None

    model_name = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    timeout = int(os.getenv("GEMINI_TIMEOUT_SECONDS", "60"))
    raw_model_line = f"Sparsowany model: {raw_model}\n" if raw_model else ""
    user_msg = VERIFY_USER_TEMPLATE.format(
        make=make,
        original_text=original_text,
        raw_model_line=raw_model_line,
    )
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
    payload = {
        "system_instruction": {"parts": [{"text": VERIFY_SYSTEM_PROMPT}]},
        "contents": [{"role": "user", "parts": [{"text": user_msg}]}],
        "generationConfig": {
            "maxOutputTokens": 300,
            "temperature": 0.1,
            "responseMimeType": "application/json",
            "thinkingConfig": {"thinkingBudget": int(os.getenv("GEMINI_THINKING_BUDGET", "0"))},
        },
    }
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        logger.warning("[model_normalization] Gemini verify failed: %s", exc)
        return None

    candidates = data.get("candidates") or []
    if not candidates:
        logger.warning("[model_normalization] Gemini brak candidates")
        return None
    parts = (candidates[0].get("content") or {}).get("parts") or []
    raw = "".join(p.get("text", "") for p in parts if p.get("text"))
    if not raw:
        logger.warning("[model_normalization] Gemini pusta odpowiedź")
        return None
    return _parse_normalize_response(raw, raw_model, "gemini", model_name)


def _verify_with_kiro_impl(make: str, original_text: str, raw_model: Optional[str] = None) -> Optional[dict]:
    """Kiro CLI headless (KIRO_API_KEY, kiro.dev/docs/cli/headless) — subprocess, tekst-only."""
    api_key = os.getenv("KIRO_API_KEY")
    if not api_key:
        logger.warning("[model_normalization] Brak KIRO_API_KEY — nie mogę zweryfikować")
        return None

    cli_path = os.getenv("KIRO_CLI_PATH", os.path.expanduser("~/.local/bin/kiro-cli"))
    effort = os.getenv("KIRO_EFFORT", "low")
    timeout = int(os.getenv("KIRO_TIMEOUT_SECONDS", "60"))
    model_name = _resolve_kiro_model()
    raw_model_line = f"Sparsowany model: {raw_model}\n" if raw_model else ""
    user_msg = VERIFY_USER_TEMPLATE.format(
        make=make,
        original_text=original_text,
        raw_model_line=raw_model_line,
    )
    prompt = f"{VERIFY_SYSTEM_PROMPT}\n\n{user_msg}"
    env = {**os.environ, "KIRO_API_KEY": api_key}
    try:
        result = subprocess.run(
            [cli_path, "chat", "--no-interactive", "--trust-tools=", "-w", "never",
             "--effort", effort, "--model", model_name, prompt],
            capture_output=True, text=True, timeout=timeout, env=env,
        )
    except Exception as exc:
        logger.warning("[model_normalization] Kiro verify failed: %s", exc)
        return None

    if result.returncode != 0:
        logger.warning("[model_normalization] Kiro CLI exit %d: %s", result.returncode, result.stderr[:200])
        return None

    raw = re.sub(r"\x1b\[[0-9;?]*[a-zA-Z]", "", result.stdout).strip()
    if not raw:
        logger.warning("[model_normalization] Kiro CLI pusta odpowiedź")
        return None
    return _parse_normalize_response(raw, raw_model, "kiro", model_name)


_NORMALIZE_PROVIDERS = {
    "gemini": _verify_with_gemini_impl,
    "kiro": _verify_with_kiro_impl,
    "anthropic": _verify_with_anthropic_impl,
}


def _resolve_kiro_model() -> str:
    """Model Kiro: nadpisanie z dashboardu ma pierwszeństwo przed .env KIRO_MODEL."""
    try:
        from api.settings_db import get_ai_model_override
        override = get_ai_model_override("kiro")
        if override:
            return override
    except Exception:
        pass
    return os.getenv("KIRO_MODEL", "claude-haiku-4.5")


def _resolve_normalize_provider() -> str:
    """Nadpisanie z dashboardu (settings_db) ma pierwszeństwo przed .env."""
    try:
        from api.settings_db import get_ai_provider_override
        override = get_ai_provider_override("model_normalization_ai_provider")
        if override:
            return override.lower()
    except Exception:
        pass
    return (os.getenv("MODEL_NORMALIZATION_AI_PROVIDER", "gemini") or "gemini").lower()


def verify_with_anthropic(make: str, original_text: str, raw_model: Optional[str] = None) -> Optional[dict]:
    """Provider dispatch (nazwa historyczna z czasów Anthropic-only — zostawiona
    dla kompatybilności z wywołującym w api/main.py).

    Wybór providera: MODEL_NORMALIZATION_AI_PROVIDER (default 'gemini').
    Fallback do Anthropic, gdy skonfigurowany provider nie zwróci wyniku i jest klucz.

    Zwraca dict {normalized_model, reason, is_normalized, provider, llm_model}
    albo None gdy wszystkie próby padną. Wynik NIE jest automatycznie
    zapisywany — wywołujący odpowiedzialny za store().
    """
    provider = _resolve_normalize_provider()
    impl = _NORMALIZE_PROVIDERS.get(provider, _verify_with_gemini_impl)

    result = impl(make, original_text, raw_model)
    if result is not None:
        return result
    if provider != "anthropic" and os.getenv("ANTHROPIC_API_KEY"):
        logger.info("[model_normalization] %s nie zwrócił wyniku — fallback Anthropic", provider)
        return _verify_with_anthropic_impl(make, original_text, raw_model)
    return None


def normalize_with_cache(make: str, original_text: str, raw_model: Optional[str] = None) -> dict:
    """Główna funkcja — cache HIT albo Anthropic verify + store.

    Returns dict:
      {
        "make": "BMW",
        "original_text": "BMW M440i coupé",
        "normalized_model": "4 Series",
        "reason": "...",
        "source": "cache" | "llm" | "fallback",
        "verified_count": 5,        # gdy cache HIT
        "is_normalized": true
      }
    """
    if not _initialized:
        _ensure_init()

    cached = lookup(make, original_text)
    if cached:
        # Cache HIT — incrementuje verified_count (statystyka uzycia)
        try:
            now = datetime.utcnow().isoformat(timespec="seconds")
            with _lock, _connect() as conn:
                conn.execute(
                    "UPDATE model_normalizations SET verified_count = verified_count + 1, "
                    "updated_at = ? WHERE id = ?",
                    (now, cached["id"]),
                )
        except Exception:
            logger.exception("[model_normalization] increment failed (non-fatal)")

        return {
            "make": make,
            "original_text": original_text,
            "normalized_model": cached["normalized_model"],
            "reason": cached.get("reason"),
            "source": "cache",
            "verified_count": cached.get("verified_count", 1) + 1,
            "is_normalized": (
                str(raw_model or "").strip().lower() != str(cached["normalized_model"]).strip().lower()
                if raw_model
                else False
            ),
        }

    # Cache miss — verify with Anthropic
    verified = verify_with_anthropic(make, original_text, raw_model)
    if verified and verified.get("normalized_model"):
        store(
            make=make,
            original_text=original_text,
            normalized_model=verified["normalized_model"],
            reason=verified.get("reason"),
            provider=verified.get("provider"),
            llm_model=verified.get("llm_model"),
        )
        return {
            "make": make,
            "original_text": original_text,
            "normalized_model": verified["normalized_model"],
            "reason": verified.get("reason"),
            "source": "llm",
            "verified_count": 1,
            "is_normalized": verified.get("is_normalized", False),
        }

    # LLM padło — fallback do raw_model albo original_text
    fallback = raw_model or original_text
    return {
        "make": make,
        "original_text": original_text,
        "normalized_model": fallback,
        "reason": "LLM weryfikacja niedostępna — używam bezpośrednio",
        "source": "fallback",
        "verified_count": 0,
        "is_normalized": False,
    }
