"""Telegram Bot API sender (multi-user broadcast).

Wysyła powiadomienia o ukończonych jobach do wszystkich aktywnych subskrybentów.
Każde powiadomienie zawiera summary message + 3 zbiorcze HTML files (sendDocument).

Wymaga: TELEGRAM_BOT_TOKEN w .env.
Używa requestów stdlib (urllib) — bez dodatkowych zależności.
"""
from __future__ import annotations

import json
import logging
import mimetypes
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("notify.telegram")


_TELEGRAM_API_BASE = "https://api.telegram.org"
_HTTP_TIMEOUT = int(os.getenv("TELEGRAM_HTTP_TIMEOUT", "30"))
_MAX_DOC_BYTES = 50 * 1024 * 1024  # 50 MB Telegram limit


def _bot_token() -> Optional[str]:
    return os.getenv("TELEGRAM_BOT_TOKEN", "").strip() or None


def is_configured() -> bool:
    return bool(_bot_token())


def _api_url(method: str) -> str:
    token = _bot_token()
    if not token:
        raise RuntimeError("Brak TELEGRAM_BOT_TOKEN w .env")
    return f"{_TELEGRAM_API_BASE}/bot{token}/{method}"


def _http_post_json(method: str, payload: dict, timeout: Optional[int] = None) -> dict:
    """POST application/json — dla wszystkich Bot API metod oprócz file upload."""
    url = _api_url(method)
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout or _HTTP_TIMEOUT) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if not data.get("ok"):
        raise RuntimeError(f"Telegram API {method} failed: {data}")
    return data


def _http_post_multipart(method: str, fields: dict, files: dict, timeout: Optional[int] = None) -> dict:
    """POST multipart/form-data — dla sendDocument file upload.

    fields: zwykłe pola formularza (chat_id, caption, parse_mode, ...)
    files:  {"document": ("filename.html", bytes_content, "text/html")}
    """
    url = _api_url(method)
    boundary = f"----TelegramBoundary{uuid.uuid4().hex}"
    body = bytearray()

    # zwykłe pola
    for name, value in fields.items():
        if value is None:
            continue
        body += f"--{boundary}\r\n".encode("utf-8")
        body += f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8")
        body += str(value).encode("utf-8")
        body += b"\r\n"

    # pliki
    for name, (filename, content, mime) in files.items():
        body += f"--{boundary}\r\n".encode("utf-8")
        body += (
            f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
        ).encode("utf-8")
        body += f"Content-Type: {mime}\r\n\r\n".encode("utf-8")
        body += content
        body += b"\r\n"

    body += f"--{boundary}--\r\n".encode("utf-8")

    req = urllib.request.Request(
        url,
        data=bytes(body),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout or _HTTP_TIMEOUT) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if not data.get("ok"):
        raise RuntimeError(f"Telegram API {method} failed: {data}")
    return data


def get_me() -> dict:
    """Sprawdza connectivity i zwraca informacje o bocie."""
    return _http_post_json("getMe", {}).get("result") or {}


def send_message(
    chat_id: int,
    text: str,
    *,
    parse_mode: str = "HTML",
    disable_web_page_preview: bool = True,
    reply_markup: Optional[dict] = None,
) -> dict:
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": disable_web_page_preview,
    }
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
    return _http_post_json("sendMessage", payload).get("result") or {}


def send_document(
    chat_id: int,
    file_path: str,
    *,
    caption: Optional[str] = None,
    parse_mode: str = "HTML",
    filename: Optional[str] = None,
    mime: Optional[str] = None,
) -> dict:
    """Wysyła plik (HTML/PDF/etc) jako Document.

    Telegram traktuje HTML jako Document (nie inline preview). User może go ściągnąć
    i otworzyć w przeglądarce.
    """
    p = Path(file_path)
    if not p.exists():
        raise FileNotFoundError(f"File not found: {file_path}")
    size = p.stat().st_size
    if size > _MAX_DOC_BYTES:
        raise RuntimeError(f"File too large for Telegram: {size} > {_MAX_DOC_BYTES}")

    content = p.read_bytes()
    filename = filename or p.name
    if not mime:
        mime = mimetypes.guess_type(filename)[0] or "application/octet-stream"

    fields: dict[str, Any] = {
        "chat_id": chat_id,
        "parse_mode": parse_mode,
    }
    if caption:
        # Telegram caption limit: 1024 znaki
        fields["caption"] = caption[:1020] + "…" if len(caption) > 1024 else caption
    files = {"document": (filename, content, mime)}
    return _http_post_multipart("sendDocument", fields, files).get("result") or {}


def send_to_subscriber(
    chat_id: int,
    summary_text: str,
    files: list[tuple[str, str]],
    *,
    reply_markup: Optional[dict] = None,
    retry: int = 2,
) -> dict:
    """Wysyła do JEDNEGO subskrybenta: summary + N plików.

    files: [(file_path, caption), ...]
    Returns: {"sent_message": True/False, "sent_files": count, "errors": [...]}
    """
    result = {"sent_message": False, "sent_files": 0, "errors": []}

    # 1) Summary message (z opcjonalnym inline button)
    for attempt in range(retry + 1):
        try:
            send_message(chat_id, summary_text, reply_markup=reply_markup)
            result["sent_message"] = True
            break
        except urllib.error.HTTPError as e:
            if e.code == 429:
                # rate limit — exponential backoff
                wait = min(2 ** attempt, 10)
                logger.warning(f"[telegram] 429 rate limit chat={chat_id}, retry in {wait}s")
                time.sleep(wait)
                continue
            if e.code in (400, 403):
                # 400=bad chat / blocked, 403=user blocked bot
                err_msg = f"HTTP {e.code} chat={chat_id}: {e.reason}"
                result["errors"].append(err_msg)
                logger.warning(f"[telegram] {err_msg}")
                # nie próbuj kolejnych plików dla tego chatu
                return result
            result["errors"].append(f"HTTP {e.code}: {e.reason}")
        except Exception as e:
            result["errors"].append(f"{type(e).__name__}: {e}")
            if attempt == retry:
                return result
            time.sleep(1.0)

    # 2) Pliki HTML — sekwencyjnie z 1s delay między plikami
    for fp, caption in files:
        if not fp or not Path(fp).exists():
            logger.debug(f"[telegram] skip missing file: {fp}")
            continue
        for attempt in range(retry + 1):
            try:
                send_document(chat_id, fp, caption=caption)
                result["sent_files"] += 1
                time.sleep(0.5)  # bezpieczny throttle 2/s
                break
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    wait = min(2 ** attempt, 10)
                    logger.warning(f"[telegram] 429 doc upload chat={chat_id}, retry in {wait}s")
                    time.sleep(wait)
                    continue
                err_msg = f"sendDocument HTTP {e.code}: {e.reason}"
                result["errors"].append(err_msg)
                logger.warning(f"[telegram] {err_msg} file={fp}")
                break
            except Exception as e:
                result["errors"].append(f"sendDocument {type(e).__name__}: {e}")
                if attempt == retry:
                    break
                time.sleep(1.0)

    return result


def broadcast(
    summary_text: str,
    files: list[tuple[str, str]],
    *,
    notify_filter: str = "done",
    reply_markup: Optional[dict] = None,
    max_workers: int = 4,
) -> dict:
    """Broadcast do wszystkich aktywnych subskrybentów (równolegle).

    notify_filter: 'done' | 'error' | 'cancelled' — filtr po preferencjach usera.
    Zwraca: {"total": N, "delivered": K, "failed": [(chat_id, errors), ...]}.
    """
    from api import telegram_database as tdb

    if not is_configured():
        logger.info("[telegram] BOT_TOKEN nie skonfigurowany — pomijam broadcast")
        return {"total": 0, "delivered": 0, "failed": [], "skipped": "no_token"}

    flt = {"notify_done": False, "notify_error": False, "notify_cancelled": False}
    if notify_filter == "done":
        flt["notify_done"] = True
    elif notify_filter == "error":
        flt["notify_error"] = True
    elif notify_filter == "cancelled":
        flt["notify_cancelled"] = True

    subscribers = tdb.list_active_subscribers(**flt)
    if not subscribers:
        logger.info(f"[telegram] Brak subskrybentów dla filter={notify_filter}")
        return {"total": 0, "delivered": 0, "failed": []}

    logger.info(f"[telegram] Broadcast do {len(subscribers)} subskrybentów (filter={notify_filter})")

    failed = []
    delivered = 0

    def _send_one(sub: dict) -> tuple[int, dict]:
        cid = int(sub["chat_id"])
        try:
            res = send_to_subscriber(cid, summary_text, files, reply_markup=reply_markup)
            if res["sent_message"]:
                tdb.record_delivery(cid)
            return (cid, res)
        except Exception as e:
            logger.exception(f"[telegram] send_to_subscriber {cid} failed")
            return (cid, {"sent_message": False, "sent_files": 0, "errors": [str(e)]})

    with ThreadPoolExecutor(max_workers=max(1, max_workers)) as ex:
        for cid, res in ex.map(_send_one, subscribers):
            if res["sent_message"]:
                delivered += 1
            else:
                failed.append((cid, res.get("errors") or ["unknown"]))

    logger.info(f"[telegram] Broadcast: {delivered}/{len(subscribers)} delivered, {len(failed)} failed")
    return {
        "total": len(subscribers),
        "delivered": delivered,
        "failed": failed,
    }


# ─────────────────────────────────────────────────────────────────────────────
# High-level helper: powiadomienie o zakończonym jobie
# ─────────────────────────────────────────────────────────────────────────────


def _format_status_emoji(status: str) -> str:
    return {
        "done": "✅",
        "error": "❌",
        "cancelled": "🚫",
        "interrupted": "⚠️",
    }.get(status, "ℹ️")


def _build_inline_keyboard(record_id: Optional[int], ui_base_url: Optional[str] = None) -> Optional[dict]:
    if not record_id:
        return None
    base = ui_base_url or os.getenv("TELEGRAM_UI_BASE_URL", "").strip()
    if not base:
        return None
    base = base.rstrip("/")
    return {
        "inline_keyboard": [
            [{"text": "🔗 Otwórz w UI", "url": f"{base}?record_id={record_id}"}]
        ]
    }


def notify_job_completion(
    *,
    status: str,
    title: str,
    record_id: Optional[int] = None,
    job_id: Optional[str] = None,
    collected_count: int = 0,
    polecam_count: int = 0,
    ryzyko_count: int = 0,
    duration_seconds: Optional[float] = None,
    error: Optional[str] = None,
    bundle_paths: Optional[dict[str, str]] = None,
) -> dict:
    """Wysyła powiadomienie o zakończonym jobie do wszystkich subskrybentów.

    bundle_paths: {"client_short_bundle": "/path/...html",
                   "client_bundle": "/path/...html",
                   "broker_bundle": "/path/...html"}
    """
    if not is_configured():
        return {"skipped": "no_token"}

    emoji = _format_status_emoji(status)
    lines = [
        f"{emoji} <b>Scraping {status}</b>",
        "",
        f"📋 <b>{title or '?'}</b>",
    ]
    if status == "done":
        lines.append(f"🔍 Lotów: <b>{collected_count}</b> · POLECAM: <b>{polecam_count}</b> · RYZYKO: <b>{ryzyko_count}</b>")
    if duration_seconds is not None:
        mins, secs = divmod(int(duration_seconds), 60)
        lines.append(f"⏱️ Czas: <b>{mins}m {secs}s</b>")
    if record_id:
        lines.append(f"📊 Rekord: <b>#{record_id}</b>")
    if error:
        # Telegram message limit 4096 — przytnij error
        err_short = error[:300] + "…" if len(error) > 300 else error
        lines.append("")
        lines.append(f"<i>Błąd:</i> <code>{_html_escape(err_short)}</code>")

    summary = "\n".join(lines)

    # Pliki do wysłki (tylko bundle, opcja 2A)
    files: list[tuple[str, str]] = []
    bp = bundle_paths or {}
    bundle_definitions = [
        ("client_short_bundle", "📄 Krótki raport klienta (POLECAM)"),
        ("client_bundle", "📋 Pełny raport klienta (POLECAM)"),
        ("broker_bundle", "🔍 Raport brokerski (wszystkie + Otomoto)"),
    ]
    for key, caption in bundle_definitions:
        path = bp.get(key)
        if path and Path(path).exists():
            files.append((path, caption))

    reply_markup = _build_inline_keyboard(record_id)

    return broadcast(
        summary,
        files,
        notify_filter=status if status in ("done", "error", "cancelled") else "done",
        reply_markup=reply_markup,
    )


def _html_escape(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
