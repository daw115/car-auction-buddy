"""Kody uszkodzeń z amerykańskich aukcji po polsku.

Copart i IAAI opisują szkodę słownikiem stałych napisów: `RIGHT SIDE`,
`ALL OVER`, `WATER/FLOOD`. Do tej pory szły do klienta w tej postaci, więc
w polskim zdaniu lądowało „RIGHT SIDE — naprawa nie jest wliczona". Klient
albo tego nie rozumie, albo rozumie tyle, że oferta jest przeklejona skądinąd.

Tłumaczymy na rzeczowniki, bo w szablonach stoją jako podmiot („Uszkodzony
prawy bok — naprawa nie jest wliczona…"), a nie w środku zdania.

Kodu, którego nie znamy, NIE zgadujemy: wraca w oryginale. Zła nazwa szkody
w ofercie jest gorsza niż angielska — angielską klient dopyta, a polską weźmie
za ustalenie. Nowe kody dopisuje się tutaj, gdy pojawią się w danych.
"""

from __future__ import annotations

import re

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
    "THEFT": "Auto po kradzieży",
    "STRIPPED": "Auto rozebrane, brakuje części",
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


def po_polsku(kod: str) -> str:
    """Jeden kod uszkodzenia po polsku. Nieznany wraca bez zmian."""
    if not kod:
        return ""
    znormalizowany = re.sub(r"\s+", " ", kod).strip().upper()
    # Aukcje zapisują to samo raz ze spacjami wokół ukośnika, raz bez.
    znormalizowany = re.sub(r"\s*/\s*", "/", znormalizowany)
    return _SLOWNIK.get(znormalizowany, kod.strip())


def opis(*kody: str) -> str:
    """Szkoda główna i dodatkowa w jednym zdaniu.

    Druga szkoda idzie po przecinku małą literą, bo „Uszkodzony przód + REAR END"
    czytało się jak zapis z systemu, a nie jak zdanie.
    """
    przetlumaczone = [po_polsku(k) for k in kody if k and k.strip()]
    if not przetlumaczone:
        return "brak danych"
    pierwszy, *reszta = przetlumaczone
    if not reszta:
        return pierwszy
    dodatkowe = ", ".join(t[0].lower() + t[1:] if t[:1].isupper() else t for t in reszta)
    return f"{pierwszy}, {dodatkowe}"
