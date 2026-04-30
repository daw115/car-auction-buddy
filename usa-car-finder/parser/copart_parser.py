import re
import json
from typing import Optional, Tuple
from bs4 import BeautifulSoup
from pathlib import Path
from .models import CarLot


def parse_price(text: str) -> Optional[float]:
    if not text:
        return None
    cleaned = re.sub(r"[^\d.]", "", text.replace(",", ""))
    try:
        return float(cleaned) if cleaned else None
    except ValueError:
        return None


def parse_odometer(text: str) -> Tuple[Optional[int], Optional[int]]:
    if not text:
        return None, None
    nums = re.findall(r"\d+", text.replace(",", ""))
    if not nums:
        return None, None
    mi = int(nums[0])
    return mi, round(mi * 1.60934)


def _extract_image_urls(soup: BeautifulSoup, html_content: str) -> list[str]:
    candidates: list[str] = []

    # 1) Standardowe tagi img.
    for img in soup.select("img[src], img[data-src], img[data-lazy], img[data-original]"):
        src = (
            img.get("src")
            or img.get("data-src")
            or img.get("data-lazy")
            or img.get("data-original")
            or ""
        ).strip()
        if src.startswith("http"):
            candidates.append(src)

    # 2) URL-e obrazów ukryte w JS/JSON.
    regex_urls = re.findall(
        r"https?://[^\"'\\\s]+?\.(?:jpg|jpeg|png|webp)(?:\?[^\"'\\\s]*)?",
        html_content,
        flags=re.IGNORECASE,
    )
    candidates.extend(regex_urls)

    # 3) JSON-LD z polem image.
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
                candidates.append(image_field)
            elif isinstance(image_field, list):
                for img_url in image_field:
                    if isinstance(img_url, str) and img_url.startswith("http"):
                        candidates.append(img_url)

    # Uporządkuj i ogranicz do najbardziej prawdopodobnych zdjęć lotu.
    unique: list[str] = []
    seen = set()
    for url in candidates:
        normalized = url.split("?", 1)[0].lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        unique.append(url)

    priority = [
        u for u in unique
        if any(token in u.lower() for token in ("copart", "vehicle", "lot", "image", "photo"))
    ]
    fallback = [u for u in unique if u not in priority]
    return (priority + fallback)[:10]


def parse_copart_html(html_file: Path) -> Optional[CarLot]:
    try:
        html_content = html_file.read_text(encoding="utf-8")
        soup = BeautifulSoup(html_content, "lxml")

        def txt(selector: str) -> str:
            el = soup.select_one(selector)
            return el.get_text(strip=True) if el else ""

        lot_id = html_file.stem
        lot_url = None
        lot_match = re.search(r"https?://(?:www\.)?copart\.com/lot/(\d+)", html_content)
        if lot_match:
            lot_id = lot_match.group(1)
            lot_url = lot_match.group(0)
        elif not lot_id.isdigit():
            lot_match = re.search(r"/lot/(\d{5,})", html_content)
            if lot_match:
                lot_id = lot_match.group(1)
                lot_url = f"https://www.copart.com/lot/{lot_id}"

        if not str(lot_id).isdigit():
            return None

        # Wyciągnij JSON z cachedSolrLotDetailsStr
        make = None
        model = None
        year = None
        vin_raw = None
        location_state = None
        location_city = None
        current_bid = None
        damage_primary = None
        title_type = None
        mi = None
        km = None
        auction_date_text = None
        seller_type = None

        match = re.search(r'cachedSolrLotDetailsStr:\s*"(.+?)"(?=,\s*[\w]+:)', html_content, re.DOTALL)
        if match:
            json_str = match.group(1)
            # Decode escaped string properly
            import codecs
            json_str = codecs.decode(json_str, 'unicode_escape')
            try:
                data = json.loads(json_str)
                make = data.get("mkn")
                model = data.get("lm")
                year = data.get("lcy")
                vin_raw = data.get("fv")
                location_state = data.get("ts")
                location_city = data.get("locCity")

                # Current bid is in dynamicLotDetails
                dynamic = data.get("dynamicLotDetails", {})
                current_bid = dynamic.get("currentBid") or data.get("hb")

                damage_primary = data.get("dd")
                title_type = data.get("tgd")
                if data.get("ifs") is True:
                    seller_type = "insurance"
                elif data.get("ifs") is False:
                    seller_type = "dealer"

                # Odometer
                orr = data.get("orr")
                if orr:
                    mi = int(orr)
                    km = round(mi * 1.60934)

                # Data aukcji
                ad_timestamp = data.get("ad")
                if ad_timestamp:
                    from datetime import datetime, timezone
                    auction_dt = datetime.fromtimestamp(ad_timestamp / 1000, tz=timezone.utc)
                    auction_date_text = auction_dt.strftime("%Y-%m-%d %H:%M:%S")
            except:
                pass

        images = _extract_image_urls(soup, html_content)

        page_text = soup.get_text().lower()
        airbags_deployed = "deployed" in page_text and "airbag" in page_text
        keys = "yes" in txt(".lot-keys").lower() if txt(".lot-keys") else None

        return CarLot(
            source="copart",
            lot_id=lot_id,
            url=lot_url or f"https://www.copart.com/lot/{lot_id}",
            html_file=str(html_file),
            vin=vin_raw or None,
            year=year,
            make=make or None,
            model=model or None,
            odometer_mi=mi,
            odometer_km=km,
            damage_primary=damage_primary or None,
            title_type=title_type or None,
            current_bid_usd=current_bid,
            seller_type=seller_type,
            location_city=location_city or None,
            location_state=location_state,
            images=images,
            airbags_deployed=airbags_deployed,
            keys=keys,
            auction_date=auction_date_text or None,
        )

    except Exception as e:
        print(f"[Parser/Copart] Błąd {html_file.name}: {e}")
        return None


def parse_all_copart(cache_dir: Path) -> list[CarLot]:
    results = []
    files = list(cache_dir.glob("*.html"))
    for f in files:
        lot = parse_copart_html(f)
        if lot:
            results.append(lot)
    print(f"[Parser/Copart] Sparsowano {len(results)}/{len(files)} plików")
    return results
