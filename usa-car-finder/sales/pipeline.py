"""Cztery kroki obsługi klienta: oferta wstępna, wybór, raport, decyzja.

Broker prowadzi jedną sprawę przez cztery etapy i po każdym z nich musi wiedzieć,
CO dokładnie zostało zrobione:

    1. Oferta wstępna     — które trzy auta wysłaliśmy i kiedy
    2. Wybrane samochody  — na które klient wskazał
    3. Raport szczegółowy — o którym aucie, wysłany kiedy
    4. Decyzja            — czy klient kupuje

`Lead.stage` odpowiada na pytanie „gdzie jesteśmy", ale nie na „co pokazaliśmy".
Bez tej drugiej odpowiedzi po tygodniu nie da się ustalić, czy klient milczy na
temat trzech aut, czy jednego, ani który raport dostał. Rozmowa na WhatsAppie
tego nie zastąpi: broker wysyła stamtąd PDF-y, których treści nie widać w wątku.

Krok 4 to decyzja KLIENTA o zakupie, nie nasza o licytacji. Ta druga zaczyna się
po niej i ma własny etap w `Stage` — sprawa kończy się na „kupuje" albo
„rezygnuje", i dopiero wtedy zaczyna się licytacja.

Stan trzymamy w SQLite razem z leadami, a nie w Postgresie razem z kartoteką:
kroki są napędzane rozmową i kandydatami, a te są tutaj. Trzecie źródło prawdy
o tej samej sprawie kosztowałoby więcej niż daje.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from sales.db import _connect, init_db

logger = logging.getLogger("sales.pipeline")

KROKI = {
    1: "oferta wstępna",
    2: "wybrane samochody",
    3: "raport szczegółowy",
    4: "decyzja",
}


@dataclass
class StanSprawy:
    lead_id: int
    krok: int = 1
    #: Loty wysłane w ofercie wstępnej — tyle, ile trzeba, żeby je rozpoznać w rozmowie.
    wyslane: list[dict] = field(default_factory=list)
    #: Na które klient wskazał. Podzbiór wysłanych, w kolejności jego wyboru.
    wybrane: list[dict] = field(default_factory=list)
    #: Nazwy plików raportów, które poszły do klienta.
    raporty: list[str] = field(default_factory=list)
    decyzja: Optional[str] = None  # "kupuje" | "rezygnuje" | None
    notatka: str = ""
    zmieniono: Optional[str] = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "lead_id": self.lead_id,
            "krok": self.krok,
            "krok_nazwa": KROKI.get(self.krok, "?"),
            "wyslane": self.wyslane,
            "wybrane": self.wybrane,
            "raporty": self.raporty,
            "decyzja": self.decyzja,
            "notatka": self.notatka,
            "zmieniono": self.zmieniono,
        }


def _teraz() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def init() -> None:
    """Tabela kroków. Jeden wiersz na leada — sprawa nie rozgałęzia się."""
    init_db()
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS lead_pipeline (
                lead_id INTEGER PRIMARY KEY REFERENCES leads(id) ON DELETE CASCADE,
                krok INTEGER NOT NULL DEFAULT 1,
                wyslane_json TEXT NOT NULL DEFAULT '[]',
                wybrane_json TEXT NOT NULL DEFAULT '[]',
                raporty_json TEXT NOT NULL DEFAULT '[]',
                decyzja TEXT,
                notatka TEXT NOT NULL DEFAULT '',
                zmieniono TEXT NOT NULL
            );
            """
        )


def stan(lead_id: int) -> StanSprawy:
    """Aktualny krok sprawy. Dla leada bez wiersza zwraca krok 1, nie None —
    każda sprawa jest na jakimś etapie, nawet zanim ktokolwiek ją tknął."""
    init()
    with _connect() as conn:
        row = conn.execute("SELECT * FROM lead_pipeline WHERE lead_id = ?", (lead_id,)).fetchone()
    if row is None:
        return StanSprawy(lead_id=lead_id)
    return StanSprawy(
        lead_id=lead_id,
        krok=int(row["krok"]),
        wyslane=json.loads(row["wyslane_json"] or "[]"),
        wybrane=json.loads(row["wybrane_json"] or "[]"),
        raporty=json.loads(row["raporty_json"] or "[]"),
        decyzja=row["decyzja"],
        notatka=row["notatka"] or "",
        zmieniono=row["zmieniono"],
    )


def _zapisz(s: StanSprawy) -> StanSprawy:
    init()
    s.zmieniono = _teraz()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO lead_pipeline
                (lead_id, krok, wyslane_json, wybrane_json, raporty_json, decyzja, notatka, zmieniono)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(lead_id) DO UPDATE SET
                krok = excluded.krok,
                wyslane_json = excluded.wyslane_json,
                wybrane_json = excluded.wybrane_json,
                raporty_json = excluded.raporty_json,
                decyzja = excluded.decyzja,
                notatka = excluded.notatka,
                zmieniono = excluded.zmieniono
            """,
            (
                s.lead_id,
                s.krok,
                json.dumps(s.wyslane, ensure_ascii=False),
                json.dumps(s.wybrane, ensure_ascii=False),
                json.dumps(s.raporty, ensure_ascii=False),
                s.decyzja,
                s.notatka,
                s.zmieniono,
            ),
        )
    return s


def klucz_lota(lot: Any, pozycja: int = 0) -> str:
    """Stabilny identyfikator auta w obrębie jednej sprawy.

    `lot_id` WYGLĄDA NA GOTOWY KLUCZ I NIM NIE JEST. U Manheima jest to nazwa
    kanału aukcji, nie numer egzemplarza: w danych z produkcji wszystkie loty
    z tego źródła mają `lot_id = "OVE"`. Klucz zbudowany na tym polu sklejałby
    całą ofertę w jedno auto — klient odpisuje „1", „2" albo „3" i za każdym
    razem dostaje ten sam samochód, bez żadnego błędu po drodze.

    Kolejność jest od najpewniejszego. VIN identyfikuje EGZEMPLARZ i jest jeden
    na świecie. Adres aukcji identyfikuje OGŁOSZENIE i też jest niepowtarzalny,
    więc ratuje loty bez VIN-u. `lot_id` dopiero potem, bo jego unikalność
    zależy od źródła. Pozycja na końcu, gdy nie ma nic innego — klucz żyje
    w obrębie jednej oferty, więc numer pozycji ją domyka.
    """
    # Auto krąży po aplikacji w dwóch kształtach: samo (`CarLot`) i opakowane
    # w kandydata z wyszukiwania (`{lot, score, ...}`). Klucz musi wyjść ten sam,
    # inaczej krok 1 zapisze „lot-1", a krok 3 poszuka po VIN-ie i nie znajdzie.
    if isinstance(lot, dict) and isinstance(lot.get("lot"), dict):
        lot = lot["lot"]
    get = (lambda k: lot.get(k)) if isinstance(lot, dict) else (lambda k: getattr(lot, k, None))
    for pole in ("vin", "full_vin", "url", "lot_id"):
        wartosc = get(pole)
        if wartosc:
            return str(wartosc)
    return f"{get('source') or 'lot'}-{pozycja + 1}"


def _opis_lota(lot: Any, pozycja: int = 0) -> dict[str, Any]:
    """Tyle, ile trzeba, żeby broker rozpoznał auto w rozmowie sprzed tygodnia."""
    klucz = klucz_lota(lot, pozycja)
    if isinstance(lot, dict) and isinstance(lot.get("lot"), dict):
        lot = lot["lot"]  # kandydat z wyszukiwania, nie sam lot
    get = (lambda k: lot.get(k)) if isinstance(lot, dict) else (lambda k: getattr(lot, k, None))
    return {
        "klucz": klucz,
        "lot_id": get("lot_id"),
        "source": get("source"),
        "nazwa": " ".join(str(x) for x in [get("year"), get("make"), get("model")] if x),
        "vin": get("vin"),
        "url": get("url"),
    }


def klucz_wpisu(wpis: dict[str, Any], pozycja: int = 0) -> str:
    """Klucz zapisanej pozycji. Sprawy sprzed tej zmiany nie mają pola `klucz`,
    ale mają VIN i adres — czyli to, z czego `klucz_lota` i tak by go policzył."""
    return str(
        wpis.get("klucz")
        or wpis.get("vin")
        or wpis.get("url")
        or wpis.get("lot_id")
        or f"lot-{pozycja + 1}"
    )


def zapisz_oferte(lead_id: int, loty) -> StanSprawy:
    """Krok 1: poszła oferta wstępna. Zapisujemy, CO poszło."""
    s = stan(lead_id)
    s.wyslane = [_opis_lota(l, i) for i, l in enumerate(loty)][:6]
    s.krok = max(s.krok, 2)  # od teraz czekamy na wybór klienta
    return _zapisz(s)


def zapisz_wybor(lead_id: int, klucze: list[str]) -> StanSprawy:
    """Krok 2: klient wskazał auta. Bierzemy je z wysłanych, nie z powietrza.

    Gdy wskaże coś, czego nie wysyłaliśmy (bo znalazł sam albo pomylił numer),
    zapisujemy to jako pozycję bez opisu — lepiej mieć ślad niż go zgubić.
    """
    s = stan(lead_id)
    po_kluczu = {klucz_wpisu(w, i): w for i, w in enumerate(s.wyslane)}
    s.wybrane = [
        po_kluczu.get(str(k), {"klucz": str(k), "lot_id": str(k), "nazwa": "spoza oferty"})
        for k in klucze
    ]
    s.krok = max(s.krok, 3) if s.wybrane else s.krok
    return _zapisz(s)


def zapisz_raport(lead_id: int, nazwa_pliku: str) -> StanSprawy:
    """Krok 3: raport szczegółowy poszedł do klienta."""
    s = stan(lead_id)
    if nazwa_pliku not in s.raporty:
        s.raporty.append(nazwa_pliku)
    s.krok = max(s.krok, 4)
    return _zapisz(s)


def zapisz_decyzje(lead_id: int, decyzja: str, notatka: str = "") -> StanSprawy:
    """Krok 4: decyzja klienta o zakupie.

    Dozwolone są dwie wartości. „Zastanawia się" celowo NIE jest decyzją —
    to nadal krok 4 bez rozstrzygnięcia, a wpisanie go jako trzeciej opcji
    zamieniłoby lejek w miejsce, w którym sprawy leżą bezterminowo.
    """
    if decyzja not in ("kupuje", "rezygnuje"):
        raise ValueError("decyzja musi być 'kupuje' albo 'rezygnuje'")
    s = stan(lead_id)
    s.decyzja = decyzja
    s.notatka = notatka
    s.krok = 4
    return _zapisz(s)
