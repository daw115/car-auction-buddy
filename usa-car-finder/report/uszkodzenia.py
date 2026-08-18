"""Kody uszkodzeń z amerykańskich aukcji po polsku.

Copart i IAAI opisują szkodę słownikiem stałych napisów: `RIGHT SIDE`,
`ALL OVER`, `WATER/FLOOD`. Bez tłumaczenia lądują w polskim zdaniu oferty
(„RIGHT SIDE — naprawa nie jest wliczona"), a klient albo tego nie rozumie,
albo rozumie tyle, że oferta jest przeklejona skądinąd.

DWA STOPNIE, BO DWA RODZAJE BŁĘDU KOSZTUJĄ INACZEJ.
Najpierw słownik dokładny: kod aukcji odwzorowany jeden do jednego, bez miejsca
na pomyłkę. Dopiero potem wzorce, które łapią warianty, jakich nikt nie
przewidział (`LEFT FRONT END`, `ENGINE BURN`). Sama regułka bywa zdradliwa —
poprzednia wersja w `offer_agent.py` miała `all over` w jednym wzorcu z
`rollover` i mówiła klientowi „dachowanie" o aucie, które nigdy nie dachowało.
Dlatego dokładne dopasowanie ma pierwszeństwo, a wzorce są ostatnią deską.

Kodu, którego nie znamy, NIE zgadujemy. `rozpoznaj` zwraca wtedy None i decyzję
podejmuje wołający: w raporcie pokazujemy oryginał (klient dopyta), a w prozie
oferty piszemy „zakres uszkodzeń do potwierdzenia" — tam angielski napis
wyglądałby na niedokończony tekst.
"""

from __future__ import annotations

import re
from typing import Optional

#: Dokładne kody, tak jak wypisują je aukcje. Rzeczowniki, bo w szablonach
#: stoją jako podmiot („Uszkodzony prawy bok — naprawa nie jest wliczona…").
_SLOWNIK: dict[str, str] = {
    # Strony i strefy nadwozia
    "FRONT END": "Uszkodzony przód",
    "FRONT": "Uszkodzony przód",
    "REAR END": "Uszkodzony tył",
    "REAR": "Uszkodzony tył",
    "SIDE": "Uszkodzony bok",
    "LEFT SIDE": "Uszkodzony lewy bok",
    "RIGHT SIDE": "Uszkodzony prawy bok",
    "LEFT FRONT": "Uszkodzony lewy przód",
    "RIGHT FRONT": "Uszkodzony prawy przód",
    "LEFT REAR": "Uszkodzony lewy tył",
    "RIGHT REAR": "Uszkodzony prawy tył",
    "TOP/ROOF": "Uszkodzony dach",
    "ROOF": "Uszkodzony dach",
    "UNDERCARRIAGE": "Uszkodzone podwozie",
    "ALL OVER": "Uszkodzenia na całym nadwoziu",
    # Zdarzenia
    "ROLLOVER": "Dachowanie",
    "HAIL": "Uszkodzenia od gradu",
    "VANDALISM": "Wandalizm",
    "BURN": "Auto po pożarze",
    "BURN - ENGINE": "Pożar w komorze silnika",
    "BURN - INTERIOR": "Pożar wnętrza",
    "WATER/FLOOD": "Auto zalane",
    "FLOOD": "Auto zalane",
    "THEFT": "Ślady kradzieży",
    "STRIPPED": "Auto rozebrane, brakuje części",
    "BIOHAZARD/CHEMICAL": "Skażenie wnętrza",
    # Usterki techniczne
    "MECHANICAL": "Usterka mechaniczna",
    "ENGINE DAMAGE": "Uszkodzony silnik",
    "TRANSMISSION": "Uszkodzona skrzynia biegów",
    "SUSPENSION": "Uszkodzone zawieszenie",
    "ELECTRICAL": "Usterka elektryki",
    # Stan bez szkody kolizyjnej
    "NORMAL WEAR": "Normalne zużycie",
    "MINOR DENT/SCRATCHES": "Drobne wgniecenia i rysy",
    "MINOR DENTS/SCRATCHES": "Drobne wgniecenia i rysy",
    "DAMAGE HISTORY": "Szkoda w historii pojazdu",
    "PARTIAL REPAIR": "Auto częściowo naprawione",
    "REPAIRED": "Auto naprawione",
    # Bez treści — aukcje wpisują to zamiast pustego pola
    "UNKNOWN": "Zakres szkody nieokreślony przez aukcję",
    "NONE": "Bez uszkodzeń podanych przez aukcję",
}

#: Wzorce na warianty spoza słownika. KOLEJNOŚĆ MA ZNACZENIE: najpierw rzeczy
#: konkretne, potem ogólne, bo wygrywa pierwsze trafienie. „ALL OVER" stoi przed
#: „ROLLOVER" właśnie dlatego, że wcześniej te dwa dzieliły jeden wzorzec.
_WZORCE: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"normal wear", re.I), "Normalne zużycie"),
    (re.compile(r"minor dent|dent/scratch|scratch", re.I), "Drobne wgniecenia i rysy"),
    (re.compile(r"hail", re.I), "Uszkodzenia od gradu"),
    (re.compile(r"vandalism", re.I), "Wandalizm"),
    (re.compile(r"theft|stolen", re.I), "Ślady kradzieży"),
    (re.compile(r"biohazard|chemical", re.I), "Skażenie wnętrza"),
    (re.compile(r"water|flood", re.I), "Auto zalane"),
    (re.compile(r"burn|fire", re.I), "Ślady pożaru"),
    (re.compile(r"all\s*over", re.I), "Uszkodzenia na całym nadwoziu"),
    (re.compile(r"rollover", re.I), "Dachowanie"),
    (re.compile(r"undercarriage", re.I), "Uszkodzone podwozie"),
    (re.compile(r"suspension", re.I), "Uszkodzone zawieszenie"),
    (re.compile(r"mechanical|engine|transmission", re.I), "Usterka mechaniczna"),
    (re.compile(r"top/?roof|roof", re.I), "Uszkodzony dach"),
    # Strona przed strefą: „LEFT FRONT END" ma zostać lewym przodem, a nie samym
    # przodem. Klient ogląda jedno zdjęcie i pyta dokładnie o to, której strony
    # na nim nie widać.
    (re.compile(r"left\s+front", re.I), "Uszkodzony lewy przód"),
    (re.compile(r"right\s+front", re.I), "Uszkodzony prawy przód"),
    (re.compile(r"left\s+rear", re.I), "Uszkodzony lewy tył"),
    (re.compile(r"right\s+rear", re.I), "Uszkodzony prawy tył"),
    (re.compile(r"left\s+side", re.I), "Uszkodzony lewy bok"),
    (re.compile(r"right\s+side", re.I), "Uszkodzony prawy bok"),
    (re.compile(r"front", re.I), "Uszkodzony przód"),
    (re.compile(r"rear", re.I), "Uszkodzony tył"),
    (re.compile(r"side", re.I), "Uszkodzony bok"),
)


def _mala(tekst: str) -> str:
    """Pierwsza litera mała — do wstawienia w środek zdania."""
    return tekst[0].lower() + tekst[1:] if tekst[:1].isupper() else tekst


def _znormalizuj(kod: str) -> str:
    znormalizowany = re.sub(r"\s+", " ", kod).strip().upper()
    # Aukcje zapisują to samo raz ze spacjami wokół ukośnika, raz bez.
    return re.sub(r"\s*/\s*", "/", znormalizowany)


def rozpoznaj(kod: str, *, mala: bool = False) -> Optional[str]:
    """Kod uszkodzenia po polsku albo None, gdy go nie znamy.

    None jest tu treścią, nie brakiem odpowiedzi: pozwala wołającemu wybrać
    między pokazaniem oryginału a napisaniem „do potwierdzenia".
    """
    if not kod or not kod.strip():
        return None
    dokladny = _SLOWNIK.get(_znormalizuj(kod))
    if dokladny:
        return _mala(dokladny) if mala else dokladny
    for wzorzec, etykieta in _WZORCE:
        if wzorzec.search(kod):
            return _mala(etykieta) if mala else etykieta
    return None


def po_polsku(kod: str, *, mala: bool = False) -> str:
    """Jak `rozpoznaj`, ale nieznany kod wraca w oryginale.

    Do raportów: kod aukcji jest wtedy widoczny i klient o niego dopyta.
    Zmyślona polska nazwa zostałaby wzięta za ustalenie.
    """
    if not kod:
        return ""
    return rozpoznaj(kod, mala=mala) or kod.strip()


def opis(*kody: Optional[str], mala: bool = False) -> str:
    """Szkoda główna i dodatkowa w jednym zdaniu.

    Druga idzie po przecinku małą literą, bo „Uszkodzony przód + REAR END"
    czytało się jak zapis z systemu, a nie jak zdanie.
    """
    czlony: list[tuple[str, bool]] = []
    for kod in kody:
        if not kod or not kod.strip():
            continue
        przetlumaczony = rozpoznaj(kod, mala=mala)
        czlony.append((przetlumaczony or kod.strip(), przetlumaczony is not None))
    if not czlony:
        return "brak danych"

    pierwszy, *reszta = czlony
    if not reszta:
        return pierwszy[0]
    # Małą literą tylko to, co FAKTYCZNIE przetłumaczyliśmy. Kod aukcji zostaje
    # w oryginale, a „RIGHT SIDE" zmniejszone o pierwszą literę daje „rIGHT SIDE"
    # — napis, który wygląda na uszkodzone dane, a nie na uszkodzone auto.
    dodatkowe = ", ".join(_mala(t) if znany else t for t, znany in reszta)
    return f"{pierwszy[0]}, {dodatkowe}"
