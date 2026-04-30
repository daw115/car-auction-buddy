import re
import json
from html import unescape
from datetime import datetime, timezone
from typing import Optional
from bs4 import BeautifulSoup
from pathlib import Path
from .models import CarLot
from .copart_parser import parse_price, parse_odometer


def _parse_iaai_datetime(raw_value: str) -> Optional[str]:
    if not raw_value:
        return None
    value = unescape(raw_value).replace("\\u002B", "+").strip()
    value = value.replace("T", " ")
    patterns = [
        "%m/%d/%Y %I:%M:%S %p %z",
        "%m/%d/%Y %I:%M:%S %p",
        "%Y-%m-%d %H:%M:%S%z",
        "%Y-%m-%d %H:%M:%S",
    ]
    for pattern in patterns:
        try:
            dt = datetime.strptime(value, pattern)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            else:
                dt = dt.astimezone(timezone.utc)
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
    return None


def _decode_jsonish_value(raw_value: Optional[str]) -> str:
    if not raw_value:
        return ""
    try:
        return json.loads(f'"{raw_value}"').strip()
    except Exception:
        return unescape(raw_value).strip()


def _parse_bool(raw_value: str) -> Optional[bool]:
    value = (raw_value or "").strip().lower()
    if value == "true":
        return True
    if value == "false":
        return False
    return None


def _derive_seller_type(*values: str) -> Optional[str]:
    text = " ".join(value for value in values if value).lower()
    provider_type = (values[0] if values else "").strip().upper()

    if "non-insurance" in text or "noninsurance" in text:
        return "dealer"
    if "insurance" in text or "insurer" in text:
        return "insurance"
    if provider_type in {"DLR", "RCC"}:
        return "dealer"
    return None


def parse_iaai_html(html_file: Path) -> Optional[CarLot]:
    try:
        html_content = html_file.read_text(encoding="utf-8")
        soup = BeautifulSoup(html_content, "lxml")

        def txt(selector: str) -> str:
            el = soup.select_one(selector)
            return el.get_text(strip=True) if el else ""

        def attr(key: str) -> str:
            m = re.search(rf'"{re.escape(key)}":"(.*?)"', html_content)
            return _decode_jsonish_value(m.group(1)) if m else ""

        lot_id = html_file.stem
        lot_url = None
        detail_match = re.search(r"https?://(?:www\.)?iaai\.com/VehicleDetail/(\d+)", html_content)
        if detail_match:
            lot_id = detail_match.group(1)
            lot_url = detail_match.group(0)
        else:
            vehicle_match = re.search(r"https?://(?:www\.)?iaai\.com/vehicle/(\d+)", html_content)
            if vehicle_match:
                lot_id = vehicle_match.group(1)
                lot_url = vehicle_match.group(0)

        # Parse title for year/make/model (format: "2008 HYUNDAI SONATA GLS V6 for Auction - IAA")
        title_text = txt("title") or txt("h1") or ""
        year = None
        make = None
        model = None

        title_match = re.match(r'(\d{4})\s+([A-Z]+)\s+(.+?)\s+(?:for\s+Auction|$)', title_text)
        if title_match:
            year = int(title_match.group(1))
            make = title_match.group(2)
            model = title_match.group(3).strip()

        if not year and attr("Year").isdigit():
            year = int(attr("Year"))
        make = make or attr("Make") or None
        model = model or attr("Model") or None

        # VIN - search in HTML for 17-character alphanumeric
        vin_raw = None
        vin_matches = re.findall(r'\b[A-HJ-NPR-Z0-9]{17}\b', html_content)
        if vin_matches:
            vin_raw = vin_matches[0]

        odo_text = txt("[class*='odometer']") or txt("[class*='mileage']")
        mi, km = parse_odometer(odo_text)
        if mi is None:
            odo_value = attr("ODOValue")
            odo_unit = attr("ODOUoM").lower()
            if odo_value and odo_value.replace(",", "").isdigit():
                raw_miles = int(odo_value.replace(",", ""))
                if odo_unit in {"", "mi", "mile", "miles"}:
                    mi = raw_miles
                    km = int(raw_miles * 1.60934)

        damage_primary = (
            txt("[class*='damage-type']")
            or txt("[class*='primary-damage']")
            or attr("PrimaryDamageDesc")
        )
        damage_secondary = attr("SecondaryDamageDesc")

        title_type = (
            txt("[class*='title-type']")
            or txt("[class*='document-type']")
            or attr("TitleSaleDoc")
            or attr("Title")
        )

        bid_text = (
            txt("[class*='current-bid']")
            or txt("[class*='buy-now']")
            or attr("HighBidAmount")
            or attr("MinimumBidAmount")
        )
        current_bid = parse_price(bid_text)

        location = txt("[class*='location']") or txt("[class*='yard']")
        city = attr("City") or (location.split(",")[0].strip() if "," in location else location)
        state = attr("State") or (location.split(",")[-1].strip() if "," in location else None)

        seller_type = _derive_seller_type(
            attr("ProviderType"),
            attr("ProviderDesc"),
            attr("ProviderName"),
            attr("Origin"),
            attr("RDProvider"),
            attr("Synonyms"),
        )

        images = []
        for img in soup.select("img[src], img[data-src], img[data-lazy], img[data-original]"):
            src = (
                img.get("src")
                or img.get("data-src")
                or img.get("data-lazy")
                or img.get("data-original")
                or ""
            ).strip()
            if src.startswith("http"):
                images.append(src)

        regex_urls = re.findall(
            r"https?://[^\"'\\\s]+?\.(?:jpg|jpeg|png|webp)(?:\?[^\"'\\\s]*)?",
            html_content,
            flags=re.IGNORECASE,
        )
        images.extend(regex_urls)

        vis_urls = re.findall(
            r"https?://vis\.iaai\.com/dimensions\?imageKeys=[^\"'\\\s]+",
            html_content,
            flags=re.IGNORECASE,
        )
        images.extend(vis_urls)

        image_keys = re.findall(r'"k":"([^"]+~I\d+[^"]*)"', html_content)
        for key in image_keys[:12]:
            images.append(f"https://vis.iaai.com/dimensions?imageKeys={key}")

        for script in soup.select("script[type='application/ld+json']"):
            raw = script.get_text(strip=True)
            if not raw:
                continue
            try:
                payload = json.loads(raw)
            except Exception:
                continue
            nodes = payload if isinstance(payload, list) else [payload]
            for node in nodes:
                image_field = node.get("image") if isinstance(node, dict) else None
                if isinstance(image_field, str) and image_field.startswith("http"):
                    images.append(image_field)
                elif isinstance(image_field, list):
                    for img_url in image_field:
                        if isinstance(img_url, str) and img_url.startswith("http"):
                            images.append(img_url)

        deduped = []
        seen = set()
        for url in images:
            normalized = url.split("?", 1)[0].lower()
            if normalized in seen:
                continue
            seen.add(normalized)
            deduped.append(url)

        priority = [
            u for u in deduped
            if any(token in u.lower() for token in ("iaai", "vehicle", "lot", "image", "photo"))
        ]
        images = (priority + [u for u in deduped if u not in priority])[:10]

        page_text = soup.get_text().lower()
        airbag_state = attr("AirbagState").lower()
        airbags_deployed = (
            "deployed" in airbag_state
            or ("deployed" in page_text and "airbag" in page_text)
        )

        # Data aukcji z JSON embedded w HTML
        auction_date_text = None
        try:
            # IAAI ma kilka wariantów pól daty aukcji.
            match = re.search(r'"saleDate["\s:]+(\d+)', html_content)
            if match:
                timestamp_ms = int(match.group(1))
                auction_dt = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)
                auction_date_text = auction_dt.strftime("%Y-%m-%d %H:%M:%S")

            if not auction_date_text:
                for pattern in [
                    r'"AuctionDateTime":"([^"]+)"',
                    r'"DisplayLaneRunDateTime":"([^"]+)"',
                    r'"liveDate":"([^"]+)"',
                ]:
                    m = re.search(pattern, html_content)
                    if not m:
                        continue
                    parsed = _parse_iaai_datetime(m.group(1))
                    if parsed:
                        auction_date_text = parsed
                        break
        except:
            pass

        return CarLot(
            source="iaai",
            lot_id=lot_id,
            url=lot_url or f"https://www.iaai.com/VehicleDetail/{lot_id}",
            html_file=str(html_file),
            vin=vin_raw or None,
            year=year,
            make=make or None,
            model=model or None,
            odometer_mi=mi,
            odometer_km=km,
            damage_primary=damage_primary or None,
            damage_secondary=damage_secondary or None,
            title_type=title_type or None,
            current_bid_usd=current_bid,
            seller_type=seller_type,
            location_city=city or None,
            location_state=state,
            images=images,
            keys=_parse_bool(attr("Keys")),
            airbags_deployed=airbags_deployed,
            auction_date=auction_date_text or None,
        )

    except Exception as e:
        print(f"[Parser/IAAI] Błąd {html_file.name}: {e}")
        return None


def parse_all_iaai(cache_dir: Path) -> list[CarLot]:
    results = []
    files = list(cache_dir.glob("*.html"))
    for f in files:
        lot = parse_iaai_html(f)
        if lot:
            results.append(lot)
    print(f"[Parser/IAAI] Sparsowano {len(results)}/{len(files)} plików")
    return results
