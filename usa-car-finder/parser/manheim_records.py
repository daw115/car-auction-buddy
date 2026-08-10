"""
Normalizacja rekordów pojazdów z API Manheima — bez zależności od przeglądarki.

Wspólne dla trzech miejsc: scrapera (przechwyt XHR), parsera zapisanych
dokumentów i endpointu /api/manheim/ingest (kolektor w rozszerzeniu). Kształt
danych jest jeden, więc mapa aliasów też musi być jedna — wcześniej żyła
w dwóch kopiach i rozjeżdżały się przy każdej poprawce.

Zaobserwowane na żywo (onesearch-api.manheim.com/graphql):
  * SPA rozbija pojazd na kilka zapytań — osobno opis, osobno status licytacji
    (`highBid`, `endTime`, `bidCount`), stąd scalanie po VIN-ie,
  * kwoty przychodzą jako obiekt `{"amount": 14250, "currency": "USD"}`.
"""
import base64
import gzip
import json
import re
from typing import Any, Optional

# Klucze, pod którymi Manheim trzyma poszczególne pola. Kolejność = priorytet.
# Szukane rekurencyjnie i bez rozróżniania wielkości liter, więc zmiana
# zagnieżdżenia po stronie Manheima niczego nie psuje.
FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    # Nazwy potwierdzone listą `fields` z zapytania getExecuteSearchId
    # (onesearch-api.manheim.com). Starsze warianty zostają jako zapas.
    "vin": ("vin", "vehiclevin", "fullvin"),
    "year": ("sourceyear", "year", "modelyear", "vehicleyear"),
    "make": ("sourcemake", "make", "makename", "vehiclemake"),
    "model": ("sourcemodel", "model", "modelname", "vehiclemodel"),
    "trim": ("sourcetrim", "trim", "trimname", "series", "subseries"),
    "odometer": ("odometer", "mileage", "miles", "odometerreading"),
    "current_bid": (
        "bidprice", "startingbidprice", "currentbid", "highbid", "currentprice",
        "bidamount", "hb",
    ),
    "buy_now": ("buynowprice", "buynow", "askingprice", "price", "listprice", "bnp"),
    "mmr": ("mmrprice", "averagemmrvaluation", "valuationsmmr"),
    "condition_grade": (
        "conditiongrade", "arbitrationrating", "grade", "cr", "conditionreportgrade",
    ),
    # announcementsEnrichment/disclosuresEnrichment to identyfikatory liczbowe,
    # nie opisy — zmierzone na żywym rekordzie (wartość 1150). Nie wpuszczamy ich
    # do damage, bo parser zrobiłby z tego "uszkodzenie 1150".
    "damage": ("damagedescription", "damage", "announcements", "announcement"),
    "damage_secondary": ("secondarydamage", "conditiondescription", "comments"),
    "title_type": ("titlestatus", "titlestate", "titletype", "title", "brandedtitle"),
    "city": ("city", "locationcity"),
    "state": ("state", "locationstate", "stateabbreviation"),
    "location": (
        "pickuplocation", "facilitationlocation", "vehiclelocationdescription",
        "locationname", "location", "auctionname", "salelocation",
    ),
    "auction_date": (
        "saledate", "auctionendtime", "auctionstarttime", "auctiondate",
        "saledatetime", "enddate", "endtime", "auctionenddate", "salestartdate",
    ),
    "lot_id": (
        "unifiedid", "ovelistingid", "vehicleid", "workordernumber", "lotnumber",
        "lotid", "id", "uuid",
    ),
    "url": ("detailpageurl", "wsurl", "vdpurl", "detailurl", "vehicleurl", "url", "link"),
    "image": ("mainimage", "imageurl", "thumbnailurl", "primaryimage", "image", "thumbnail"),
    "seller": ("sellername", "seller", "consignor", "sellertype"),
}

# Kwoty bywają owinięte w obiekt — bez rozpakowania highBid/buyNow wracałyby
# jako None, mimo że wartość jest w rekordzie.
_MONEY_KEYS = ("amount", "value", "price", "number")

_VIN_RE = re.compile(r"[A-HJ-NPR-Z0-9]{11,17}")


def walk(node: Any):
    """Wszystkie słowniki w dowolnie zagnieżdżonej strukturze JSON."""
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from walk(value)
    elif isinstance(node, list):
        for item in node:
            yield from walk(item)


def lower_keys(record: dict) -> dict:
    return {str(key).lower().replace("_", ""): value for key, value in record.items()}


def unwrap_scalar(value: Any) -> Any:
    if isinstance(value, dict):
        for key in _MONEY_KEYS:
            inner = value.get(key)
            if isinstance(inner, (int, float, str)) and inner not in (None, ""):
                return inner
        return None
    if isinstance(value, list):
        # Manheim część pól oddaje jako listę jednoelementową
        # (zmierzone: "sourceModel": ["RAV4"]). Bierzemy pierwszą wartość prostą.
        for item in value:
            if isinstance(item, (int, float, str)) and item not in (None, ""):
                return item
        return None
    return value


def pick(record: dict, field: str) -> Any:
    """Pierwsza niepusta wartość dla aliasu pola — także z zagnieżdżeń."""
    aliases = FIELD_ALIASES.get(field, ())
    for node in walk(record):
        if not isinstance(node, dict):
            continue
        flat = lower_keys(node)
        for alias in aliases:
            value = unwrap_scalar(flat.get(alias))
            if value in (None, "", [], {}):
                continue
            return value
    return None


def as_int(value: Any) -> Optional[int]:
    if value in (None, ""):
        return None
    digits = re.sub(r"[^\d]", "", str(value))
    return int(digits) if digits else None


def as_float(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    cleaned = re.sub(r"[^\d.]", "", str(value).replace(",", ""))
    try:
        return float(cleaned) if cleaned else None
    except ValueError:
        return None


def looks_like_vehicle(record: dict) -> bool:
    """Heurystyka: rekord pojazdu ma VIN albo komplet year+make+model."""
    if not isinstance(record, dict):
        return False
    flat = lower_keys(record)
    vin = flat.get("vin")
    if isinstance(vin, str) and _VIN_RE.fullmatch(vin.strip().upper()):
        return True
    present = sum(
        1
        for field in ("year", "make", "model")
        if any(flat.get(alias) not in (None, "", [], {}) for alias in FIELD_ALIASES[field])
    )
    return present == 3


_LOCATION_RE = re.compile(r"^\s*([A-Z]{2})\s*-\s*(.+?)\s*$")


def split_location(value: Any) -> tuple[Optional[str], Optional[str]]:
    """Manheim podaje lokalizację jednym polem: "FL - Manheim Orlando".

    Zwraca (stan, nazwa). Gdy formatu nie da się rozpoznać — (None, oryginał),
    bo lepiej stracić stan niż wpisać śmieć do kolumny stanu.
    """
    if not isinstance(value, str) or not value.strip():
        return None, None
    match = _LOCATION_RE.match(value.strip())
    if match:
        return match.group(1), match.group(2)
    return None, value.strip()


def record_key(record: dict) -> str:
    return str(pick(record, "vin") or pick(record, "lot_id") or "")


def merge_records(records: list[dict]) -> list[dict]:
    """Scala rekordy tego samego pojazdu zamiast zostawiać pierwszy.

    SPA rozbija dane na kilka zapytań; bez scalenia tracilibyśmy jedną z połówek
    zależnie od tego, która odpowiedź przyszła pierwsza.
    """
    merged: dict[str, dict] = {}
    order: list[str] = []
    for record in records:
        key = record_key(record)
        if not key:
            continue
        if key not in merged:
            merged[key] = dict(record)
            order.append(key)
            continue
        for field, value in record.items():
            current = merged[key].get(field)
            if current in (None, "", [], {}) and value not in (None, "", [], {}):
                merged[key][field] = value
    return [merged[key] for key in order]


def _decode_embedded(value: str) -> Optional[Any]:
    """Rozpakowuje JSON zaszyty w stringu — także spakowany.

    Manheim oddaje wyniki jako `stringifiedJSON`, a przy większych odpowiedziach
    ustawia `compressed: true` i wtedy jest to **gzip w base64** (payload zaczyna
    się od `H4sIA`). Bez tego kroku widać tylko napis: zmierzone na odpowiedzi
    1,13 MB, z której wychodzi 100 lotów z pełnym kompletem pól.
    """
    text = value.strip()
    if not text:
        return None
    if text[0] in "[{":
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return None
    if not text.startswith("H4sI"):
        return None
    try:
        return json.loads(gzip.decompress(base64.b64decode(text)))
    except Exception:
        return None


def extract_vehicles(payload: Any, depth: int = 0) -> list[dict]:
    """Wyławia rekordy pojazdów, schodząc też w JSON-y zaszyte w stringach.

    Jedno przejście, bez zbierania pośrednich kopii payloadu — inaczej ten sam
    lot trafiał na listę dwa razy (zmierzone: 200 zamiast 100).
    """
    found: list[dict] = []
    if depth > 6:
        return found
    if isinstance(payload, dict):
        if looks_like_vehicle(payload):
            found.append(payload)
        for key, value in payload.items():
            if isinstance(value, str):
                if "stringified" in key.lower() or value.startswith("H4sI"):
                    inner = _decode_embedded(value)
                    if inner is not None:
                        found.extend(extract_vehicles(inner, depth + 1))
                continue
            found.extend(extract_vehicles(value, depth + 1))
    elif isinstance(payload, list):
        for item in payload:
            found.extend(extract_vehicles(item, depth + 1))
    return found
