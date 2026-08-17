"""HTML na PDF, żeby broker miał co wysłać przez WhatsAppa.

Dotąd raport istniał wyłącznie jako strona HTML. Broker, który chciał wysłać go
klientowi, musiał otworzyć go w przeglądarce i wydrukować do pliku — co da się
zrobić na komputerze, ale nie w rozmowie na telefonie. A rozmowa z klientem
toczy się na WhatsAppie.

Szablony są już pisane pod druk (`@page A4`, `break-inside: avoid`), więc PDF
powstaje z tego samego HTML-a i wygląda tak samo jak wydruk z przeglądarki.

WeasyPrint jest na serwerze (62.3) i nie ma go na macOS-ie bez bibliotek
systemowych, dlatego import jest leniwy: brak silnika nie może wywrócić
generowania raportów HTML, które działa wszędzie.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

logger = logging.getLogger("report.pdf_export")


class PdfNiedostepny(RuntimeError):
    """Silnik PDF nie jest zainstalowany na tej maszynie."""


def dostepny() -> bool:
    """Czy da się w ogóle wygenerować PDF. Panel pyta o to przed pokazaniem przycisku."""
    try:
        import weasyprint  # noqa: F401
    except Exception:
        return False
    return True


def html_na_pdf(html: str, *, base_url: Optional[str] = None) -> bytes:
    """Zamienia gotowy HTML raportu na PDF.

    `base_url` jest potrzebny tylko wtedy, gdy dokument odwołuje się do plików
    z dysku. Nasze raporty mają zdjęcia wklejone jako `data:`, więc PDF powstaje
    bez ani jednego zapytania do sieci — czyli tak samo szybko i tak samo
    wyglądająco niezależnie od tego, czy aukcja jeszcze trzyma zdjęcia.
    """
    try:
        from weasyprint import HTML
    except Exception as blad:  # noqa: BLE001
        raise PdfNiedostepny(
            "WeasyPrint nie jest zainstalowany. Na Ubuntu: apt install libpango-1.0-0 "
            "libpangoft2-1.0-0 libharfbuzz0b, potem pip install weasyprint."
        ) from blad

    return HTML(string=html, base_url=base_url).write_pdf()


def nazwa_pliku(lot, przyrostek: str = "oferta") -> str:
    """Nazwa pliku, którą klient zobaczy w WhatsAppie.

    Ma być czytelna na liście załączników, więc marka i model zamiast identyfikatora
    lota. Znaki spoza ASCII wypadają, bo część klientów pocztowych i telefonów
    potrafi je zamienić w krzaki albo uciąć rozszerzenie.
    """
    czesci = [str(x) for x in (lot.year, lot.make, lot.model) if x]
    rdzen = "-".join(czesci) if czesci else "auto"
    rdzen = re.sub(r"[^A-Za-z0-9-]+", "-", rdzen).strip("-").lower()
    return f"{rdzen}-{przyrostek}.pdf"
