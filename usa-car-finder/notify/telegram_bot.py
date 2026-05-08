"""Telegram Bot polling worker — odbiera /start, /stop, /status, /help.

Działa jako background asyncio task uruchomiony w lifespan FastAPI. Pulluje
updates z `getUpdates` (long polling 30s) i obsługuje komendy:

- /start <CODE> — rejestracja (wymaga TELEGRAM_INVITE_CODE)
- /stop        — wypisanie się
- /status      — pokazuje preferencje
- /preferences — toggle done/error/cancelled
- /help        — lista komend

Kotwice offset trzymane w telegram_state (db) — przeżywa restart bota.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any, Optional

from notify import telegram as tg

logger = logging.getLogger("notify.telegram_bot")


_LONG_POLL_TIMEOUT = int(os.getenv("TELEGRAM_POLL_TIMEOUT", "30"))
_OFFSET_STATE_KEY = "polling_offset"


def _help_text() -> str:
    return (
        "🤖 <b>USA Car Finder — Bot powiadomień</b>\n\n"
        "Po rejestracji dostajesz na czacie raporty HTML po każdym ukończonym scrape:\n"
        "• 📄 Krótki raport klienta (POLECAM)\n"
        "• 📋 Pełny raport klienta (POLECAM)\n"
        "• 🔍 Raport brokerski (wszystkie + Otomoto)\n\n"
        "<b>Komendy:</b>\n"
        "• <code>/start KOD</code> — rejestracja (poproś admina o kod)\n"
        "• <code>/stop</code> — wypisz się\n"
        "• <code>/status</code> — sprawdź konfigurację\n"
        "• <code>/preferences done|error|cancelled on|off</code> — kontrola powiadomień\n"
        "• <code>/help</code> — ta lista"
    )


def _status_text(sub: dict) -> str:
    yn = lambda v: "✅" if v else "—"
    lines = [
        "📊 <b>Twoja konfiguracja</b>",
        "",
        f"<b>Aktywny:</b> {yn(sub.get('active'))}",
        f"<b>Powiadomienia DONE:</b> {yn(sub.get('notify_done'))}",
        f"<b>Powiadomienia ERROR:</b> {yn(sub.get('notify_error'))}",
        f"<b>Powiadomienia CANCELLED:</b> {yn(sub.get('notify_cancelled'))}",
        f"<b>Wysyłaj bundle HTML:</b> {yn(sub.get('send_bundles'))}",
        "",
        f"Odebrano: <b>{sub.get('total_received', 0)}</b> powiadomień",
    ]
    if sub.get("registered_at"):
        lines.append(f"Zarejestrowany: <code>{sub['registered_at']}</code>")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Routing komend
# ─────────────────────────────────────────────────────────────────────────────


def _handle_start(chat_id: int, args: str, user: dict) -> str:
    from api import telegram_database as tdb

    expected_code = os.getenv("TELEGRAM_INVITE_CODE", "").strip()
    if not expected_code:
        # brak kodu → otwarte dla wszystkich (dev mode)
        is_new = tdb.register(
            chat_id,
            username=user.get("username"),
            first_name=user.get("first_name"),
            last_name=user.get("last_name"),
        )
    else:
        provided = args.strip()
        if provided != expected_code:
            return (
                "🔒 <b>Nieprawidłowy kod zaproszenia</b>\n\n"
                "Aby się zarejestrować wyślij: <code>/start TWÓJ_KOD</code>\n"
                "(skontaktuj się z administratorem żeby dostać kod)"
            )
        is_new = tdb.register(
            chat_id,
            username=user.get("username"),
            first_name=user.get("first_name"),
            last_name=user.get("last_name"),
        )

    name = user.get("first_name") or user.get("username") or "broker"
    if is_new:
        return (
            f"✅ <b>Witaj, {tg._html_escape(name)}!</b>\n\n"
            "Zostałeś zarejestrowany. Po każdym ukończonym scrape "
            "otrzymasz na czacie 3 raporty HTML (klient krótki/pełny + broker).\n\n"
            f"Wpisz <code>/help</code> żeby zobaczyć dostępne komendy."
        )
    return (
        f"👋 Cześć z powrotem, {tg._html_escape(name)}!\n\n"
        "Twoje powiadomienia są ponownie aktywne.\n"
        f"Wpisz <code>/status</code> żeby zobaczyć preferencje."
    )


def _handle_stop(chat_id: int) -> str:
    from api import telegram_database as tdb

    if tdb.deactivate(chat_id):
        return (
            "👋 Zostałeś wypisany.\n\n"
            "Nie będziesz już otrzymywać powiadomień. "
            "Wyślij <code>/start KOD</code> żeby się ponownie zarejestrować."
        )
    return "ℹ️ Nie jesteś jeszcze zarejestrowany. Wyślij <code>/start KOD</code>."


def _handle_status(chat_id: int) -> str:
    from api import telegram_database as tdb

    sub = tdb.get_subscriber(chat_id)
    if not sub:
        return "ℹ️ Nie jesteś jeszcze zarejestrowany. Wyślij <code>/start KOD</code>."
    return _status_text(sub)


def _handle_preferences(chat_id: int, args: str) -> str:
    """Oczekuje: '<key> <on|off>' np. 'done on', 'error off', 'cancelled on'."""
    from api import telegram_database as tdb

    parts = args.strip().lower().split()
    if len(parts) != 2:
        return (
            "ℹ️ Użycie: <code>/preferences KEY VAL</code>\n\n"
            "<b>KEY:</b> done | error | cancelled | bundles\n"
            "<b>VAL:</b> on | off\n\n"
            "<i>Przykłady:</i>\n"
            "• <code>/preferences error off</code>\n"
            "• <code>/preferences cancelled on</code>"
        )
    key, val = parts
    if val not in ("on", "off"):
        return "ℹ️ VAL musi być <code>on</code> lub <code>off</code>."
    flag = val == "on"

    kw_map = {
        "done": "notify_done",
        "error": "notify_error",
        "cancelled": "notify_cancelled",
        "bundles": "send_bundles",
    }
    if key not in kw_map:
        return f"ℹ️ Nieznany KEY: <code>{key}</code>. Dostępne: done, error, cancelled, bundles."
    if not tdb.update_preferences(chat_id, **{kw_map[key]: flag}):
        return "❌ Nie znaleziono Twojej rejestracji. Wyślij <code>/start KOD</code>."
    sub = tdb.get_subscriber(chat_id) or {}
    return f"✅ Zaktualizowano: <b>{key}</b> = <b>{val}</b>\n\n" + _status_text(sub)


# ─────────────────────────────────────────────────────────────────────────────
# Polling loop
# ─────────────────────────────────────────────────────────────────────────────


def _process_update(update: dict) -> None:
    """Routes single update do odpowiedniego handlera."""
    msg = update.get("message") or update.get("edited_message")
    if not msg:
        return
    chat = msg.get("chat") or {}
    chat_id = chat.get("id")
    if not chat_id:
        return
    text = (msg.get("text") or "").strip()
    if not text.startswith("/"):
        # zwykła wiadomość — odpowiedz help'em
        try:
            tg.send_message(chat_id, _help_text())
        except Exception:
            logger.exception("[bot] send_message help failed")
        return

    user = msg.get("from") or {}

    # Parse: "/cmd@botname args" -> ("cmd", "args")
    head, _, args = text.partition(" ")
    cmd = head.lstrip("/").split("@", 1)[0].lower()

    try:
        if cmd == "start":
            reply = _handle_start(chat_id, args, user)
        elif cmd == "stop":
            reply = _handle_stop(chat_id)
        elif cmd == "status":
            reply = _handle_status(chat_id)
        elif cmd == "preferences":
            reply = _handle_preferences(chat_id, args)
        elif cmd == "help":
            reply = _help_text()
        else:
            reply = (
                f"❓ Nieznana komenda: <code>/{tg._html_escape(cmd)}</code>\n\n"
                + _help_text()
            )
        tg.send_message(chat_id, reply)
    except urllib.error.HTTPError as e:
        logger.warning(f"[bot] send_message HTTP {e.code}: {e.reason}")
    except Exception:
        logger.exception(f"[bot] handler failed for cmd={cmd}")


def _get_updates(offset: Optional[int]) -> list[dict]:
    """Long poll Telegram for new updates."""
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        return []
    params: dict[str, Any] = {
        "timeout": _LONG_POLL_TIMEOUT,
        "allowed_updates": json.dumps(["message"]),
    }
    if offset is not None:
        params["offset"] = offset
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"https://api.telegram.org/bot{token}/getUpdates?{qs}"
    try:
        with urllib.request.urlopen(url, timeout=_LONG_POLL_TIMEOUT + 10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        logger.warning(f"[bot] getUpdates HTTP {e.code}: {e.reason}")
        return []
    except Exception as e:
        logger.warning(f"[bot] getUpdates failed: {type(e).__name__}: {e}")
        return []
    if not data.get("ok"):
        logger.warning(f"[bot] getUpdates not ok: {data}")
        return []
    return data.get("result") or []


async def polling_loop() -> None:
    """Główna pętla pollingu — uruchamiana jako asyncio task w lifespan."""
    from api import telegram_database as tdb

    if not tg.is_configured():
        logger.info("[bot] TELEGRAM_BOT_TOKEN nie skonfigurowany — polling disabled")
        return

    tdb.init_db()
    last_offset_str = tdb.get_state(_OFFSET_STATE_KEY)
    offset: Optional[int] = int(last_offset_str) if last_offset_str else None

    try:
        me = await asyncio.to_thread(tg.get_me)
        logger.info(f"[bot] Connected as @{me.get('username')} (id={me.get('id')})")
    except Exception as e:
        logger.warning(f"[bot] getMe failed: {e} — polling abort")
        return

    logger.info(f"[bot] Polling started (offset={offset})")
    while True:
        try:
            updates = await asyncio.to_thread(_get_updates, offset)
        except asyncio.CancelledError:
            logger.info("[bot] Polling cancelled — shutting down")
            break
        except Exception:
            logger.exception("[bot] _get_updates exception")
            await asyncio.sleep(5)
            continue

        if not updates:
            # long poll wrócił pusty — czekaj 1s i ponownie
            await asyncio.sleep(1)
            continue

        max_id = offset or 0
        for upd in updates:
            uid = upd.get("update_id")
            if uid is not None and uid >= max_id:
                max_id = uid + 1
            try:
                await asyncio.to_thread(_process_update, upd)
            except Exception:
                logger.exception("[bot] _process_update exception")

        offset = max_id
        try:
            tdb.set_state(_OFFSET_STATE_KEY, str(offset))
        except Exception:
            logger.exception("[bot] failed to persist offset")
