"""Odczyt otwartej rozmowy z WhatsApp Web w przeglądarce operatora.

Tylko czyta. Niczego nie wysyła, nie otwiera i nie zmienia — treść wiadomości
idzie do brokera, a on decyduje, co z nią zrobić.

Dlaczego surowe CDP zamiast Playwrighta: `connect_over_cdp` przyłącza się do
całej przeglądarki i tworzy sesje do wszystkich kart. Karta Manheima ma zajęty
jedyny slot `chrome.debugger` przez BidWise'a — podpięcie się pod nią zamyka ją
w kilka sekund (zmierzone). Tutaj otwieramy websocket wyłącznie do karty
WhatsAppa i żadna inna nie jest dotykana.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

DEBUG_URL = os.getenv("OPERATOR_CHROME_CDP_URL", "http://127.0.0.1:9333")
MAX_MESSAGES = int(os.getenv("WHATSAPP_MAX_MESSAGES", "80"))

# Selektory WhatsApp Web bywają zmieniane bez zapowiedzi, więc czytamy po
# klasach kierunku wiadomości (message-in/message-out), które przetrwały już
# kilka przebudów interfejsu, a nie po wygenerowanych nazwach klas.
_EXTRACT_JS = """
(() => {
  const main = document.querySelector('#main');
  if (!main) return JSON.stringify({ error: 'brak_otwartej_rozmowy' });
  const header = (main.querySelector('header') || {}).innerText || '';
  const rows = Array.from(main.querySelectorAll('div.message-in, div.message-out'));
  const messages = rows.map((row) => {
    const bubble = row.querySelector('span.selectable-text') || row;
    return {
      kierunek: row.classList.contains('message-out') ? 'broker' : 'klient',
      tekst: (bubble.innerText || '').trim(),
    };
  }).filter((m) => m.tekst);
  return JSON.stringify({
    rozmowa: header.split('\\n')[0] || '',
    wszystkich: messages.length,
    wiadomosci: messages.slice(-%d),
  });
})()
""" % MAX_MESSAGES


@dataclass
class Conversation:
    chat: str
    messages: list[dict] = field(default_factory=list)
    total: int = 0

    def as_text(self) -> str:
        """Rozmowa w formie, którą rozumie parser wymagań klienta."""
        return "\n".join(f"{m['kierunek']}: {m['tekst']}" for m in self.messages)


class WhatsappUnavailable(RuntimeError):
    """Brak karty WhatsAppa albo przeglądarki operatora."""


async def _whatsapp_target(session) -> dict:
    async with session.get(f"{DEBUG_URL}/json/list", timeout=10) as resp:
        targets = await resp.json()
    pages = [
        t for t in targets
        if t.get("type") == "page" and "web.whatsapp.com" in (t.get("url") or "")
    ]
    if not pages:
        raise WhatsappUnavailable(
            "Nie ma otwartej karty web.whatsapp.com w przeglądarce operatora"
        )
    return pages[0]


async def read_open_conversation() -> Conversation:
    """Treść rozmowy aktualnie otwartej w WhatsApp Web.

    Świadomie czyta TO, CO BROKER OTWORZYŁ — nie przegląda listy czatów i nie
    wchodzi w rozmowy z własnej inicjatywy. Wybór, czyją korespondencję czytamy,
    należy do człowieka.
    """
    import aiohttp

    async with aiohttp.ClientSession() as session:
        target = await _whatsapp_target(session)
        ws_url = target.get("webSocketDebuggerUrl")
        if not ws_url:
            raise WhatsappUnavailable("Karta WhatsAppa nie udostępnia gniazda debugowania")

        async with session.ws_connect(ws_url, timeout=15) as ws:
            await ws.send_json({
                "id": 1,
                "method": "Runtime.evaluate",
                "params": {"expression": _EXTRACT_JS, "returnByValue": True},
            })
            while True:
                message = await ws.receive_json(timeout=20)
                if message.get("id") == 1:
                    break

    result = ((message.get("result") or {}).get("result") or {}).get("value")
    if not result:
        raise WhatsappUnavailable("Strona nie zwróciła treści rozmowy")

    data = json.loads(result)
    if data.get("error") == "brak_otwartej_rozmowy":
        raise WhatsappUnavailable(
            "Żadna rozmowa nie jest otwarta — otwórz czat z klientem w oknie operatora"
        )

    conversation = Conversation(
        chat=data.get("rozmowa") or "",
        messages=data.get("wiadomosci") or [],
        total=int(data.get("wszystkich") or 0),
    )
    logger.info(
        "[whatsapp] odczytano rozmowę '%s': %d wiadomości (z %d)",
        conversation.chat, len(conversation.messages), conversation.total,
    )
    return conversation
