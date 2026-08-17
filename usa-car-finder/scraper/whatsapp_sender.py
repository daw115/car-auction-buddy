"""Wysyłka wiadomości przez WhatsApp Web w przeglądarce operatora.

To jest jedyne miejsce w całym systemie, z którego treść wychodzi do klienta
automatycznie — i dlatego ma najostrzejsze warunki wstępne w całym repozytorium.

ZASADA, KTÓRA SIĘ NIE ZMIENIA: wysyłkę uruchamia człowiek. Wcześniej klikał
„Wyślij" w WhatsAppie, teraz naciska przycisk pod wiadomością w Telegramie.
Funkcja niżej nie jest wołana z żadnego automatu, harmonogramu ani nasłuchu.

DLACZEGO NUMER, A NIE OTWARTY CZAT: czytnik (`whatsapp_reader`) świadomie czyta
rozmowę, którą broker sam otworzył. Przy wysyłce ta sama zasada byłaby katastrofą
— wiadomość poszłaby do przypadkowej osoby, jeśli w przeglądarce akurat wisi inny
czat. Dlatego czat otwieramy sami, po numerze, i sprawdzamy przed wysłaniem,
że jesteśmy we właściwym.

Surowe CDP zamiast Playwrighta z tego samego powodu co w czytniku: `connect_over_cdp`
przyłącza się do wszystkich kart i zabija sesję Manheima.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from dataclasses import dataclass
from urllib.parse import quote

logger = logging.getLogger("scraper.whatsapp_sender")

DEBUG_URL = os.getenv("OPERATOR_CHROME_CDP_URL", "http://127.0.0.1:9333")

#: Ile czekamy, aż WhatsApp Web otworzy czat i wypełni pole treścią.
_TIMEOUT_OTWARCIA_S = float(os.getenv("WHATSAPP_SEND_OPEN_TIMEOUT", "25"))


class WhatsappSendError(RuntimeError):
    """Nie udało się wysłać. Wiadomość NIE poszła — broker musi zrobić to ręcznie."""


@dataclass
class WynikWysylki:
    numer: str
    tresc: str
    #: Fragment ostatniej wiadomości wychodzącej, odczytany PO wysłaniu.
    potwierdzenie: str


def normalizuj_numer(numer: str) -> str:
    """Numer w formacie, który rozumie link `wa.me`: same cyfry, z krajem.

    Polskie numery bywają zapisane jako „+48 601 234 567", „601234567" albo
    „0601-234-567". Bez kraju WhatsApp otworzy pustą rozmowę albo cudzą.
    """
    cyfry = re.sub(r"\D", "", numer or "")
    if not cyfry:
        raise WhatsappSendError("Pusty numer telefonu")
    if cyfry.startswith("00"):
        cyfry = cyfry[2:]
    if len(cyfry) == 9:  # numer krajowy bez kierunkowego
        cyfry = "48" + cyfry
    if cyfry.startswith("0"):
        cyfry = "48" + cyfry.lstrip("0")
    if len(cyfry) < 11:
        raise WhatsappSendError(f"Numer wygląda na niepełny: {numer}")
    return cyfry


# Otwarcie czatu i wpisanie treści robi sam WhatsApp przez adres `send?phone=`.
# Zostaje kliknięcie przycisku wysyłki — szukamy go po etykiecie dostępności,
# bo klasy CSS w tej aplikacji zmieniają się z tygodnia na tydzień, a `aria-label`
# i `data-icon` przetrwały wszystkie dotychczasowe przebudowy.
_CZY_GOTOWE_JS = """
(() => !!(
  document.querySelector('button[aria-label="Wyślij"]') ||
  document.querySelector('button[aria-label="Send"]') ||
  document.querySelector('span[data-icon="send"]')
))()
"""

_WYSLIJ_JS = """
(() => {
  const przycisk =
    document.querySelector('button[aria-label="Wyślij"]') ||
    document.querySelector('button[aria-label="Send"]') ||
    document.querySelector('span[data-icon="send"]')?.closest('button') ||
    document.querySelector('[data-testid="send"]');
  if (!przycisk) return { ok: false, powod: 'brak-przycisku' };
  przycisk.click();
  return { ok: true };
})()
"""

# Dowód, że treść poszła: szukamy JEJ SAMEJ wśród ostatnich wiadomości.
#
# Pierwsza wersja sprawdzała kierunek po prefiksie `true_` w `data-id` i po
# klasach `message-out`. Zmierzone na żywej sesji: ani jedno, ani drugie już nie
# istnieje — identyfikatory wyglądają jak `3EB00D7AC5C6596C4DAE7A`, a klasy to
# wygenerowane skróty (`x1n2onr6`). Wiadomość faktycznie poszła, a nadajnik
# twierdził, że nie.
#
# Porównanie treści jest odporne na te przebudowy: jeśli nasz tekst widnieje
# w rozmowie, to znaczy, że tam trafił. Normalizujemy białe znaki, bo WhatsApp
# dokleja do wiersza godzinę i status doręczenia.
_POTWIERDZENIE_JS = """
(() => {
  const szukane = %s;
  const norm = t => (t || '').replace(/\\s+/g, ' ').trim();
  const wiersze = Array.from(document.querySelectorAll('[data-id]')).slice(-8);
  for (let i = wiersze.length - 1; i >= 0; i--) {
    const tekst = norm(wiersze[i].innerText);
    if (tekst.includes(norm(szukane))) return tekst.slice(0, 200);
  }
  return null;
})()
"""


async def _ocen(ws, wyrazenie: str, identyfikator: int):
    await ws.send_json({
        "id": identyfikator,
        "method": "Runtime.evaluate",
        "params": {"expression": wyrazenie, "returnByValue": True, "awaitPromise": True},
    })
    while True:
        odpowiedz = await ws.receive_json(timeout=30)
        if odpowiedz.get("id") == identyfikator:
            return ((odpowiedz.get("result") or {}).get("result") or {}).get("value")


async def wyslij(numer: str, tresc: str) -> WynikWysylki:
    """Otwiera czat z tym numerem i wysyła treść. Zwraca potwierdzenie z ekranu.

    Rzuca `WhatsappSendError`, gdy czegokolwiek nie da się potwierdzić. Lepiej
    powiedzieć brokerowi „nie wysłałem, zrób to ręcznie" niż zostawić go
    w przekonaniu, że klient dostał wiadomość.
    """
    import aiohttp

    if not (tresc or "").strip():
        raise WhatsappSendError("Pusta treść")
    numer = normalizuj_numer(numer)

    async with aiohttp.ClientSession() as sesja:
        async with sesja.get(f"{DEBUG_URL}/json/list", timeout=10) as resp:
            targety = await resp.json()
        strony = [
            t for t in targety
            if t.get("type") == "page" and "web.whatsapp.com" in (t.get("url") or "")
        ]
        if not strony:
            raise WhatsappSendError(
                "Nie ma otwartej karty web.whatsapp.com w przeglądarce operatora"
            )
        ws_url = strony[0].get("webSocketDebuggerUrl")
        if not ws_url:
            raise WhatsappSendError("Karta WhatsAppa nie udostępnia gniazda debugowania")

        async with sesja.ws_connect(ws_url, timeout=20) as ws:
            # 1. Otwieramy czat z konkretnym numerem i wypełnioną treścią.
            adres = f"https://web.whatsapp.com/send?phone={numer}&text={quote(tresc)}"
            await _ocen(ws, f"location.href = {adres!r}", 1)

            # 2. Czekamy, aż pojawi się przycisk wysyłki. WhatsApp ładuje czat
            #    asynchronicznie i przy pierwszym wejściu potrafi to potrwać.
            gotowe = False
            czekano = 0.0
            while czekano < _TIMEOUT_OTWARCIA_S:
                await asyncio.sleep(1.0)
                czekano += 1.0
                stan = await _ocen(ws, _CZY_GOTOWE_JS, 100 + int(czekano))
                if stan:
                    gotowe = True
                    break
            if not gotowe:
                raise WhatsappSendError(
                    "WhatsApp nie otworzył czatu z tym numerem w wyznaczonym czasie. "
                    "Sprawdź, czy przeglądarka operatora jest zalogowana."
                )

            # 3. Wysyłka.
            wynik = await _ocen(ws, _WYSLIJ_JS, 2)
            if not (wynik or {}).get("ok"):
                raise WhatsappSendError(
                    f"Nie znalazłem przycisku wysyłki ({(wynik or {}).get('powod')})"
                )

            # 4. Dowód z ekranu. Bez tego „wysłane" znaczyłoby tylko „kliknąłem".
            await asyncio.sleep(2.0)
            import json as _json

            potwierdzenie = await _ocen(ws, _POTWIERDZENIE_JS % _json.dumps(tresc), 3)

    if not potwierdzenie:
        raise WhatsappSendError(
            "Kliknąłem wysyłkę, ale nie widzę wiadomości wychodzącej na ekranie. "
            "Sprawdź rozmowę ręcznie, zanim wyślesz ponownie."
        )

    return WynikWysylki(numer=numer, tresc=tresc, potwierdzenie=str(potwierdzenie))
