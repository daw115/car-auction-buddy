"""Odczytanie wyboru klienta z jego odpowiedzi na ofertę.

Oferta wstępna idzie jako obrazek z autami ponumerowanymi 1, 2, 3 i z prośbą
„proszę odpisać samym numerem". Klient odpisuje „2", „to drugie" albo „1 i 3",
i wtedy trzeba zamienić to na konkretne loty z kroku 1 sprawy.

To jest PODPOWIEDŹ, nie automat. Wynik trafia do panelu jako propozycja
zaznaczenia, którą broker potwierdza — bo „mam 2 dzieci, wolę większe" też
zawiera dwójkę, a pomyłka na tym etapie wysyła klientowi raport o cudzym aucie.
Parser świadomie łapie za dużo i zostawia odsiew człowiekowi; odwrotna pomyłka
(przeoczony wybór) kosztuje więcej, bo klient czeka.
"""

from __future__ import annotations

import re

#: Liczebniki porządkowe w formach, w jakich ludzie piszą je na WhatsAppie.
#: Pierwsze trzy wystarczą — oferta wstępna ma trzy auta.
_SLOWNIE = {
    "pierwsz": 1,
    "drug": 2,
    "trzec": 3,
    "czwart": 4,
    "piat": 5,
    "piąt": 5,
    "szost": 6,
    "szóst": 6,
}

#: Słowa, po których liczba prawie na pewno nie jest numerem pozycji.
#: „2 tysiące", „3 lata", „za 2 dni" — to opowieść o czymś innym.
_JEDNOSTKI = re.compile(
    r"^(tys|tysi|zl|zł|pln|usd|dol|lat|rok|lata|dni|dzien|dzień|tyg|mies|km|mil|godz|proc|%)",
    re.IGNORECASE,
)


def numery_z_odpowiedzi(tekst: str, ile: int) -> list[int]:
    """Numery pozycji (1-based), na które wskazuje odpowiedź klienta.

    `ile` to liczba aut w ofercie — wszystko poza tym zakresem odpada, więc rok
    „2021" czy cena „56097" nie mają jak się przebić.

    Zwraca listę bez powtórzeń, w kolejności pojawienia się w tekście: klient
    piszący „3 i 1" wskazał najpierw trójkę i tak to zapisujemy.
    """
    if not tekst or ile < 1:
        return []

    # Zbieramy razem z pozycją w tekście, bo cyfry i słowa mieszają się w jednym
    # zdaniu („to drugie, nie 1") i liczy się kolejność klienta, nie nasza.
    trafienia: list[tuple[int, int]] = []

    for dopasowanie in re.finditer(r"\d+", tekst):
        surowy = dopasowanie.group()
        # Wiodące zero znaczy, że to nie jest numer pozycji tylko fragment czegoś
        # innego (kod, godzina). „01" nikt nie pisze, wybierając auto z listy.
        if len(surowy) > 1 and surowy.startswith("0"):
            continue
        if _JEDNOSTKI.match(tekst[dopasowanie.end() :].lstrip()):
            continue
        trafienia.append((dopasowanie.start(), int(surowy)))

    maly = tekst.lower()
    for rdzen, numer in _SLOWNIE.items():
        pozycja = maly.find(rdzen)
        if pozycja >= 0:
            trafienia.append((pozycja, numer))

    znalezione: list[int] = []
    for _, numer in sorted(trafienia):
        if 1 <= numer <= ile and numer not in znalezione:
            znalezione.append(numer)
    return znalezione
