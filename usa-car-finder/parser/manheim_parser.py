"""
Parser stron detali Manheima.

Źródłem prawdy jest blok JSON, który ManheimScraper wstrzykuje do zapisanego
HTML-a (rekord pojazdu przechwycony z XHR-ów SPA). Manheim renderuje detal
klientowo i zmienia klasy CSS bez zapowiedzi, więc opieranie się na selektorach
byłoby najkruchszym możliwym wyborem. DOM służy tu tylko jako uzupełnienie
(zdjęcia, VIN gdy nie było go w liście).
"""
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from bs4 import BeautifulSoup

from .manheim_records import as_float, as_int, pick as _pick, split_location
from .models import CarLot

EMBEDDED_DATA_ID = "usacar-manheim-listing"

_VIN_RE = re.compile(r"\b[A-HJ-NPR-Z0-9]{17}\b")


def _normalize_auction_date(value: Any) -> Optional[str]:
    """Manheim podaje datę sprzedaży raz jako ISO, raz jako epoch ms."""
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)) or str(value).isdigit():
        raw = float(value)
        if raw > 1e11:  # milisekundy
            raw /= 1000.0
        try:
            return datetime.fromtimestamp(raw, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        except (OverflowError, OSError, ValueError):
            return None
    return str(value)


def _embedded_record(soup: BeautifulSoup) -> dict:
    node = soup.find("script", id=EMBEDDED_DATA_ID)
    if node is None:
        return {}
    try:
        payload = json.loads(node.get_text() or "{}")
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


# Klucze, pod ktorymi Manheim trzyma adres zdjecia w obiekcie `mainImage`.
# Kolejnosc ma znaczenie: `smallUrl` to miniatura 86x64 px, bezuzyteczna w raporcie.
_KLUCZE_ZDJEC = ("largeUrl", "url", "href", "dziUrl", "smallUrl")


def _zdjecia_z_rekordu(wezel: Any, zebrane: list[str]) -> None:
    """Schodzi w glab rekordu i zbiera adresy zdjec z zagniezdzonych obiektow.

    `_pick` tu nie wystarcza: splaszcza wartosc do skalara przez `unwrap_scalar`,
    ktory szuka wylacznie kluczy pienieznych ('amount', 'value', 'price', 'number').
    Manheim podaje zdjecie jako obiekt `mainImage` z kluczem `largeUrl`, wiec
    `_pick(record, "image")` zwracalo None i lot wychodzil bez ani jednego zdjecia —
    mimo ze adres byl w danych. Broker widzial w raporcie napis zastepczy.
    """
    if isinstance(wezel, dict):
        for klucz, wartosc in wezel.items():
            nazwa = str(klucz).lower()
            if isinstance(wartosc, str) and wartosc.startswith("http"):
                pasuje_klucz = (
                    any(k.lower() == nazwa for k in _KLUCZE_ZDJEC)
                    or "image" in nazwa
                    or "photo" in nazwa
                )
                # Sama nazwa klucza nie wystarcza: pod `designatedDescription`
                # siedzi adres API opisu, nie obrazek. Wymagamy rozszerzenia pliku,
                # tak samo jak filtr DOM nizej w tej funkcji.
                sciezka = wartosc.split("?", 1)[0].lower()
                if pasuje_klucz and sciezka.endswith((".jpg", ".jpeg", ".png", ".webp")):
                    zebrane.append(wartosc)
            elif isinstance(wartosc, (dict, list)):
                _zdjecia_z_rekordu(wartosc, zebrane)
    elif isinstance(wezel, list):
        for element in wezel:
            _zdjecia_z_rekordu(element, zebrane)


def _extract_images(soup: BeautifulSoup, record: dict) -> list[str]:
    images: list[str] = []
    _zdjecia_z_rekordu(record, images)
    # Miniatury na koniec: dedup nizej kluczuje po adresie bez parametrow, wiec
    # gdy largeUrl i smallUrl wskazuja ten sam plik, zostaje ten wczesniejszy.
    images.sort(key=lambda u: 1 if "size=w" in u else 0)

    for img in soup.select("img[src], img[data-src]"):
        src = (img.get("src") or img.get("data-src") or "").strip()
        low = src.lower()
        if not low.startswith("http"):
            continue
        if not any(ext in low.split("?")[0] for ext in (".jpg", ".jpeg", ".png", ".webp")):
            continue
        if any(token in low for token in ("/logo", "/icon", "sprite", "placeholder", "favicon")):
            continue
        images.append(src)

    unique: list[str] = []
    seen: set[str] = set()
    for url in images:
        key = url.split("?", 1)[0].lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(url)
    return unique[:10]


def parse_manheim_html(html_file: Path) -> Optional[CarLot]:
    try:
        html_content = html_file.read_text(encoding="utf-8")
        soup = BeautifulSoup(html_content, "lxml")
        record = _embedded_record(soup)

        vin = _pick(record, "vin")
        if not vin:
            match = _VIN_RE.search(soup.get_text(" ", strip=True))
            vin = match.group(0) if match else None

        lot_id = str(_pick(record, "lot_id") or vin or html_file.stem).strip()
        if not lot_id:
            return None

        odometer_mi = as_int(_pick(record, "odometer"))
        odometer_km = round(odometer_mi * 1.60934) if odometer_mi else None

        # Manheim podaje lokalizację jednym polem ("FL - Manheim Orlando"),
        # osobnych city/state w odpowiedzi nie ma.
        location_state, location_name = split_location(_pick(record, "location"))
        location_city = str(_pick(record, "city") or location_name or "") or None
        location_state = str(_pick(record, "state") or location_state or "") or None

        grade = _pick(record, "condition_grade")
        damage_primary = _pick(record, "damage")
        if not damage_primary and grade:
            # Manheim opisuje stan oceną CR (0-5), nie typem szkody jak Copart/IAAI.
            damage_primary = f"Condition grade {grade}"

        return CarLot(
            source="manheim",
            lot_id=lot_id,
            url=f"https://search.manheim.com/results#/vdp/{lot_id}",
            html_file=str(html_file),
            vin=str(vin) if vin else None,
            full_vin=str(vin) if vin and len(str(vin)) == 17 else None,
            year=as_int(_pick(record, "year")),
            make=(str(_pick(record, "make")).strip() or None) if _pick(record, "make") else None,
            model=(str(_pick(record, "model")).strip() or None) if _pick(record, "model") else None,
            trim=(str(_pick(record, "trim")).strip() or None) if _pick(record, "trim") else None,
            odometer_mi=odometer_mi,
            odometer_km=odometer_km,
            damage_primary=str(damage_primary) if damage_primary else None,
            damage_secondary=(
                str(_pick(record, "damage_secondary")) if _pick(record, "damage_secondary") else None
            ),
            title_type=(str(_pick(record, "title_type")) if _pick(record, "title_type") else None),
            current_bid_usd=as_float(_pick(record, "current_bid")),
            buy_now_price_usd=as_float(_pick(record, "buy_now")),
            seller_type="dealer",  # Manheim to rynek dealerski, nie ubezpieczeniowy.
            location_city=location_city,
            location_state=location_state,
            auction_date=_normalize_auction_date(_pick(record, "auction_date")),
            images=_extract_images(soup, record),
            raw_data={"listing": record} if record else {},
        )
    except Exception as exc:
        print(f"[Parser/Manheim] Błąd {html_file.name}: {exc}")
        return None


def parse_all_manheim(cache_dir: Path) -> list[CarLot]:
    results = []
    files = list(cache_dir.glob("*.html"))
    for path in files:
        lot = parse_manheim_html(path)
        if lot:
            results.append(lot)
    print(f"[Parser/Manheim] Sparsowano {len(results)}/{len(files)} plików")
    return results
