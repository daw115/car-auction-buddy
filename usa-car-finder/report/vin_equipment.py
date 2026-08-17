"""Wyposażenie z VIN-u, prosto z bazy NHTSA.

Dlaczego to w ogóle jest potrzebne: wyposażenie do oferty braliśmy z surowego
rekordu aukcji, a komplet danych podaje wyłącznie Manheim. Loty z Copart i IAAI
wychodziły więc bez sekcji wyposażenia, mimo że klient pyta o silnik i napęd
niezależnie od tego, na której giełdzie auto stoi.

NHTSA (vPIC) dekoduje każdy VIN za darmo i bez klucza. Dla przykładowego RAV4
oddaje 59 wypełnionych pól: model silnika, moc, liczbę miejsc, rodzaj napędu,
rozmieszczenie poduszek, ABS/ESC.

Czego NHTSA NIE poda: fabrycznych opcji i pakietów (szyberdach, skóra, nawigacja)
ani koloru. To są dane producenta, dostępne odpłatnie albo z naklejki okiennej.
Nie obiecujemy ich klientowi i nie zmyślamy - lepiej pokazać pięć pewnych rzeczy
niż dziesięć, z których połowa jest zgadnięta.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional

logger = logging.getLogger("report.vin_equipment")

_URL = "https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVin/{vin}?format=json"

# Odpowiedź dla danego VIN-u się nie zmienia (to dane fabryczne), więc trzymamy ją
# na dysku. Bez tego każdy render raportu to osobne wyjście do sieci, a broker
# generuje kilka raportów pod rząd z tego samego wyszukiwania.
_CACHE = Path(os.getenv("VIN_CACHE_DIR", "./data")) / "vin_equipment_cache.json"

_PALIWA = {
    "gasoline": "benzyna",
    "diesel": "diesel",
    "electric": "elektryczny",
    "flexible fuel vehicle (ffv)": "benzyna/E85",
}
_NAPEDY = {
    "4wd/4-wheel drive/4x4": "na cztery koła (4x4)",
    "awd/all-wheel drive": "na cztery koła (AWD)",
    "fwd/front-wheel drive": "na przednie koła",
    "rwd/rear-wheel drive": "na tylne koła",
}


def _wczytaj_cache() -> dict:
    try:
        return json.loads(_CACHE.read_text(encoding="utf8"))
    except Exception:
        return {}


def _zapisz_cache(dane: dict) -> None:
    try:
        _CACHE.parent.mkdir(parents=True, exist_ok=True)
        _CACHE.write_text(json.dumps(dane, ensure_ascii=False), encoding="utf8")
    except Exception:
        logger.debug("[vin] nie udało się zapisać cache", exc_info=True)


def dekoduj(vin: str) -> dict:
    """Surowe pola NHTSA dla VIN-u. Pusty słownik, gdy się nie udało."""
    if not vin or len(vin) < 11 or os.getenv("VIN_EQUIPMENT_ENABLED", "true").lower() != "true":
        return {}

    vin = vin.strip().upper()
    # Copart maskuje ostatnie sześć znaków gwiazdkami; NHTSA i tak dekoduje
    # pierwsze jedenaście, ale gwiazdka w adresie psuje zapytanie.
    if "*" in vin:
        vin = vin.split("*")[0]
        if len(vin) < 11:
            return {}

    cache = _wczytaj_cache()
    if vin in cache:
        return cache[vin]

    try:
        adres = _URL.format(vin=urllib.parse.quote(vin))
        zadanie = urllib.request.Request(adres, headers={"User-Agent": "usa-car-finder"})
        czas = float(os.getenv("VIN_DECODE_TIMEOUT_SECONDS", "8"))
        with urllib.request.urlopen(zadanie, timeout=czas) as odpowiedz:
            tresc = json.loads(odpowiedz.read().decode("utf8"))
    except Exception:
        logger.debug("[vin] NHTSA nie odpowiedziała dla %s", vin, exc_info=True)
        return {}

    pola = {
        wiersz.get("Variable"): wiersz.get("Value")
        for wiersz in tresc.get("Results", [])
        if wiersz.get("Value") not in (None, "", "Not Applicable")
    }
    cache[vin] = pola
    _zapisz_cache(cache)
    return pola


def wyposazenie_z_vin(vin: Optional[str]) -> list[str]:
    """Punkty o wyposażeniu, po polsku, gotowe do wklejenia klientowi."""
    pola = dekoduj(vin or "")
    if not pola:
        return []

    punkty: list[str] = []

    poj = pola.get("Displacement (L)")
    cyl = pola.get("Engine Number of Cylinders")
    moc = pola.get("Engine Brake (hp) From")
    paliwo = pola.get("Fuel Type - Primary")
    czesci = []
    if poj:
        # NHTSA potrafi oddać 2.998832712 — dla klienta to jest trzylitrowy silnik.
        try:
            czesci.append(f"{round(float(poj), 1):.1f}".replace(".", ",") + " l")
        except (TypeError, ValueError):
            czesci.append(f"{poj} l")
    if cyl:
        czesci.append(f"{cyl} cylindry")
    if moc:
        czesci.append(f"{str(moc).split('.')[0]} KM")
    if paliwo:
        czesci.append(_PALIWA.get(str(paliwo).lower(), str(paliwo).lower()))
    if czesci:
        punkty.append("Silnik: " + ", ".join(czesci) + ".")

    naped = pola.get("Drive Type")
    if naped:
        punkty.append(f"Napęd: {_NAPEDY.get(str(naped).lower(), str(naped))}.")

    nadwozie = pola.get("Body Class")
    drzwi = pola.get("Doors")
    miejsca = pola.get("Number of Seats")
    if nadwozie:
        opis = str(nadwozie).split("[")[0].strip()
        dodatki = []
        if drzwi:
            dodatki.append(f"{drzwi} drzwi")
        if miejsca:
            # 2 miejsca, ale 5 miejsc — polska odmiana, nie da się jednym wzorem.
            liczba = str(miejsca)
            dodatki.append(f"{liczba} miejsca" if liczba in ("2", "3", "4") else f"{liczba} miejsc")
        punkty.append(f"Nadwozie: {opis}{', ' + ', '.join(dodatki) if dodatki else ''}.")

    # Systemy bezpieczeństwa: klient o nie pyta, a NHTSA podaje je dla każdego auta.
    bezpieczenstwo = []
    if pola.get("Antilock Braking System (ABS)") == "Standard":
        bezpieczenstwo.append("ABS")
    if pola.get("Electronic Stability Control (ESC)") == "Standard":
        bezpieczenstwo.append("kontrola stabilności")
    if pola.get("Traction Control") == "Standard":
        bezpieczenstwo.append("kontrola trakcji")
    if bezpieczenstwo:
        punkty.append("W standardzie: " + ", ".join(bezpieczenstwo) + ".")

    poduszki = []
    if pola.get("Front Air Bag Locations"):
        poduszki.append("przednie")
    if pola.get("Side Air Bag Locations"):
        poduszki.append("boczne")
    if pola.get("Curtain Air Bag Locations"):
        poduszki.append("kurtynowe")
    if poduszki:
        punkty.append("Poduszki powietrzne: " + ", ".join(poduszki) + ".")

    if pola.get("Keyless Ignition") == "Standard":
        punkty.append("Uruchamianie bezkluczykowe.")

    kraj = pola.get("Plant Country")
    miasto = pola.get("Plant City")
    if kraj:
        # .title() robi z "UNITED STATES (USA)" napis "United States (Usa)".
        KRAJE = {"united states (usa)": "USA", "canada": "Kanadzie", "mexico": "Meksyku",
                 "japan": "Japonii", "germany": "Niemczech", "korea (south)": "Korei"}
        kraj_pl = KRAJE.get(str(kraj).lower(), str(kraj).title())
        gdzie = f"{str(miasto).title()}, {kraj_pl}" if miasto else kraj_pl
        punkty.append(f"Wyprodukowane w: {gdzie}.")

    return punkty
