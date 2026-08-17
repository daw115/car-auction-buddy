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

# Nazwy klas w WhatsApp Web są generowane i zmieniają się bez zapowiedzi —
# `message-in` / `message-out` już nie istnieją (zmierzone: przy pełnej rozmowie
# na ekranie ekstraktor zwracał zero wiadomości). Trzymamy się dwóch rzeczy,
# które są częścią kontraktu z czytnikami ekranu i z protokołem:
#   * `[role=row]` — jeden wiersz listy wiadomości,
#   * `data-icon` o wartości `tail-in` / `tail-out` — kierunek ogonka dymka.
#
# Kierunku NIE da się już czytać z `data-id`. Wcześniej stało tu, że identyfikator
# ma format "true_<czat>_<id>" i prefiks mówi, czy wiadomość jest od nas. Zmierzone
# na żywej sesji 18 sierpnia 2026: identyfikatory wyglądają jak "3EB00D7AC5C6596C"
# i ŻADEN nie zaczyna się od "true_". Efekt był taki, że wszystkie wiadomości,
# łącznie z naszymi, wychodziły oznaczone jako „klient" — a parser wymagań czytał
# nasze własne oferty jako to, czego klient szuka.
#
# Ogonek dymka jest rysowany tylko przy PIERWSZEJ wiadomości z serii, więc kolejne
# dziedziczą kierunek po poprzedniej. Zapasowo `aria-label`: WhatsApp podpisuje
# nasze wiadomości „Ty:", a cudze nazwą kontaktu.
_EXTRACT_JS = """
(() => {
  const main = document.querySelector('#main');
  if (!main) return JSON.stringify({ error: 'brak_otwartej_rozmowy' });
  const header = (main.querySelector('header') || {}).innerText || '';
  const rows = Array.from(main.querySelectorAll('[data-id]'));
  const seen = new Set();
  const messages = [];
  let bezTekstu = 0;
  let ostatniKierunek = null;
  for (const row of rows) {
    const id = row.getAttribute('data-id') || '';
    if (!id || seen.has(id)) continue;
    seen.add(id);
    const bubble = row.querySelector('span.selectable-text');
    const tekst = (bubble ? bubble.innerText : '').trim();
    if (!tekst) { bezTekstu += 1; continue; }
    let kierunek = null;
    if (row.querySelector('[data-icon="tail-out"]')) kierunek = 'broker';
    else if (row.querySelector('[data-icon="tail-in"]')) kierunek = 'klient';
    else {
      const podpis = (row.querySelector('[aria-label]') || {}).getAttribute
        ? row.querySelector('[aria-label]').getAttribute('aria-label') : '';
      if (/^(Ty|You)\s*:/i.test(podpis || '')) kierunek = 'broker';
      else if (podpis) kierunek = 'klient';
    }
    if (!kierunek) kierunek = ostatniKierunek || 'klient';
    ostatniKierunek = kierunek;
    messages.push({ kierunek: kierunek, tekst: tekst });
  }
  return JSON.stringify({
    rozmowa: header.split('\\n')[0] || '',
    wszystkich: messages.length,
    bezTekstu: bezTekstu,
    wiadomosci: messages.slice(-%d),
  });
})()
""" % MAX_MESSAGES


@dataclass
class Conversation:
    chat: str
    messages: list[dict] = field(default_factory=list)
    total: int = 0
    #: Wiersze bez tekstu (zdjęcia, głosówki, pliki) — nie da się z nich wyczytać
    #: wymagań, ale broker ma wiedzieć, że w rozmowie było coś jeszcze.
    attachments: int = 0

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
        attachments=int(data.get("bezTekstu") or 0),
    )
    logger.info(
        "[whatsapp] odczytano rozmowę '%s': %d wiadomości (z %d)",
        conversation.chat, len(conversation.messages), conversation.total,
    )
    return conversation
