"""Oferta jako obrazek — pierwsza rzecz, którą klient dostaje na WhatsAppie.

PDF w rozmowie jest barierą: trzeba go pobrać, otworzyć w osobnej aplikacji
i wrócić do czatu. Obrazek widać od razu w wątku, więc klient przegląda trzy
auta w tej samej sekundzie, w której dostaje wiadomość, i odpowiada numerem.
PDF zostaje na później: idzie razem ze szczegółowym raportem, gdy klient już
wskaże, co go interesuje.

Renderujemy WŁASNĄ przeglądarką Playwrighta, nie tą z profilu operatora.
Tamta trzyma zalogowaną sesję Manheima i WhatsAppa; podłączanie się do niej
przez `connect_over_cdp` zrywa slot debugowania i kosztuje ponowną autoryzację
BidWise (opisane w scraper/whatsapp_reader.py).
"""

from __future__ import annotations

import logging
import os
import re
from typing import Optional

logger = logging.getLogger("report.screenshot")

#: Szerokość odpowiadająca kartce A4 przy 96 dpi. Wyższa daje obrazek, który
#: WhatsApp skaluje w dół i tekst przestaje być czytelny na telefonie.
SZEROKOSC_PX = int(os.getenv("REPORT_SCREENSHOT_WIDTH", "820"))


class ScreenshotNiedostepny(RuntimeError):
    """Brak Playwrighta albo przeglądarki. Zostaje PDF."""


def dostepny() -> bool:
    try:
        import playwright  # noqa: F401
    except Exception:
        return False
    return True


def html_na_png(html: str, *, szerokosc: Optional[int] = None) -> bytes:
    """Zamienia gotowy HTML raportu na PNG całej strony.

    Zdjęcia w naszych szablonach są wklejone jako `data:`, więc render nie czeka
    na sieć — to samo, co daje PDF-om powtarzalność, tutaj daje szybkość.
    """
    try:
        from playwright.sync_api import sync_playwright
    except Exception as blad:  # noqa: BLE001
        raise ScreenshotNiedostepny(
            "Playwright nie jest zainstalowany. pip install playwright && playwright install chromium"
        ) from blad

    szer = szerokosc or SZEROKOSC_PX
    try:
        with sync_playwright() as pw:
            przegladarka = pw.chromium.launch(args=["--no-sandbox"])
            try:
                # Niskie okno celowo: `full_page` nigdy nie schodzi poniżej wysokości
                # widoku, więc przy standardowych 1080 krótka oferta dostawałaby
                # kilkaset pikseli pustego tła pod spodem. W czacie widać głównie
                # miniaturę, a miniatura w połowie pusta to zmarnowana pierwsza chwila.
                strona = przegladarka.new_page(viewport={"width": szer, "height": 200})
                # `domcontentloaded`, nie `load`: zdjęcia mamy wklejone jako `data:`,
                # więc nie ma na co czekać. Czekanie na `load` sięgałoby do sieci
                # zawsze, gdy któregoś zdjęcia nie udało się wkleić — i przy
                # niedostępnym CDN aukcji cała oferta padałaby zamiast wyjść bez
                # jednej fotografii.
                strona.set_content(html, wait_until="domcontentloaded")
                kartka = strona.query_selector(".page")
                if kartka is not None:
                    return kartka.screenshot(type="png")
                return strona.screenshot(full_page=True, type="png")
            finally:
                przegladarka.close()
    except Exception as blad:  # noqa: BLE001
        raise ScreenshotNiedostepny(f"Nie udało się wyrenderować obrazka: {blad}") from blad


async def html_na_png_async(html: str, *, szerokosc: Optional[int] = None) -> bytes:
    """To samo, ale wołalne z endpointu FastAPI.

    Synchroniczne API Playwrighta odmawia pracy, gdy w bieżącym wątku kręci się
    pętla asyncio — a każdy endpoint tej aplikacji jest `async`. Objawia się to
    dopiero na żywym serwerze („Please use the Async API instead"), bo wywołane
    wprost z Pythona to samo wywołanie przechodzi bez zarzutu.

    Wątek zamiast asynchronicznego API Playwrighta, bo render jest jednorazowy
    i tak trwa sekundy: druga implementacja tej samej rzeczy kosztowałaby więcej
    niż jedno przełączenie wątku.
    """
    import asyncio

    return await asyncio.to_thread(html_na_png, html, szerokosc=szerokosc)


def nazwa_pliku(client_name: Optional[str] = None) -> str:
    """Nazwa widoczna w WhatsAppie. Bez znaków spoza ASCII, bo telefony potrafią
    je zamienić w krzaki albo uciąć rozszerzenie."""
    rdzen = re.sub(r"[^A-Za-z0-9-]+", "-", (client_name or "propozycje")).strip("-").lower()
    return f"{rdzen or 'propozycje'}-oferta.png"
