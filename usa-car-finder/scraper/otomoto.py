"""Otomoto.pl market price scraper.

Wyszukuje średnią/min/max cenę dla danego make/model/rok na polskim rynku wtórnym.
Używany przez hybrid_reports do podania klientowi/brokerowi referencyjnej ceny PL.

Strategia:
1. Build URL https://www.otomoto.pl/osobowe/{make-slug}/{model-slug}?search[filter_float_year:from]=X&search[filter_float_year:to]=Y
2. Sync Playwright: open page, wait for listings, extract first 30 prices
3. Compute low/high/mean/median z odrzuceniem outlierów (95 percentyl cap)
4. Cache 7 dni (market_price_cache)

Fallback: Otomoto może mieć Cloudflare challenge. W takim wypadku:
- log + zapis negative cache entry (TTL 7 dni)
- return None (hybrid renderer wtedy LLM-estimate ceny PL)
"""
from __future__ import annotations

import logging
import os
import re
import statistics
from typing import Optional
from urllib.parse import quote

from dotenv import load_dotenv

from report import market_price_cache

load_dotenv(override=True)

logger = logging.getLogger("scraper.otomoto")

OTOMOTO_BASE = "https://www.otomoto.pl/osobowe"
OTOMOTO_TIMEOUT_MS = int(os.getenv("OTOMOTO_TIMEOUT_MS", "20000"))
OTOMOTO_MAX_LISTINGS = int(os.getenv("OTOMOTO_MAX_LISTINGS", "30"))
OTOMOTO_USER_AGENT = os.getenv(
    "OTOMOTO_USER_AGENT",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
)


def _slugify_make(make: str) -> str:
    """BMW -> bmw; Mercedes-Benz -> mercedes-benz."""
    return re.sub(r"[^a-z0-9-]+", "-", (make or "").strip().lower()).strip("-")


def _slugify_model(model: str) -> str:
    """M550i -> m550i; CR-V -> cr-v; M5 -> m5."""
    if not model:
        return ""
    s = model.strip().lower()
    # Otomoto używa łączników w niektórych modelach (cr-v, e-class), no spaces
    s = re.sub(r"\s+", "-", s)
    s = re.sub(r"[^a-z0-9-]+", "", s)
    return s.strip("-")


def _build_url(make: str, model: Optional[str], year_from: Optional[int],
               year_to: Optional[int], damaged_only: bool = False) -> str:
    make_slug = _slugify_make(make)
    parts = [OTOMOTO_BASE]
    if make_slug:
        parts.append(make_slug)
    model_slug = _slugify_model(model) if model else ""
    if model_slug:
        parts.append(model_slug)
    base = "/".join(parts)

    qs = []
    if year_from:
        qs.append(f"search%5Bfilter_float_year%3Afrom%5D={year_from}")
    if year_to:
        qs.append(f"search%5Bfilter_float_year%3Ato%5D={year_to}")
    if damaged_only:
        qs.append("search%5Bfilter_enum_damaged%5D=1")
    qs.append("search%5Border%5D=created_at_first%3Adesc")  # najnowsze ogłoszenia

    return base + ("?" + "&".join(qs) if qs else "")


def _parse_offers_from_html(html: str) -> list[dict]:
    """Wyciąga listę OGŁOSZEŃ z HTML Otomoto (title, price, year, mileage, url).

    Używa BeautifulSoup do parsowania <article> z search results.
    Pomija reklamy/promocje (article bez linku do oferty).

    Returns: list[{title, price_pln, year, mileage_km, url}]
    """
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        logger.warning("[Otomoto] bs4 not available — falling back to price-only")
        return []

    soup = BeautifulSoup(html, "lxml")
    offers: list[dict] = []

    articles = soup.select("article")
    for a in articles:
        title_el = a.select_one('h2 a, h3 a')
        if not title_el or "otomoto.pl/osobowe/oferta" not in (title_el.get("href") or ""):
            continue

        title = title_el.get_text(strip=True)
        url = title_el.get("href")

        # Price z <h3> zawierającym digit pattern
        price = None
        for h in a.select("h3"):
            txt = h.get_text(strip=True).replace("\xa0", " ")
            m = re.match(r"^([\d\s]{4,12})$", txt)
            if m:
                try:
                    price = int(m.group(1).replace(" ", ""))
                    if 1000 <= price <= 5_000_000:
                        break
                    price = None
                except ValueError:
                    pass

        # Parameters (rok, przebieg, fuel, gearbox)
        params_el = a.select('dl dd, [data-testid="ad-parameters"] dd')
        year = None
        mileage_km = None
        for p in params_el:
            txt = p.get_text(strip=True).replace("\xa0", " ")
            if re.match(r"^\d{4}$", txt):
                year = int(txt)
            elif "km" in txt.lower():
                m = re.match(r"^([\d\s]+)\s*km$", txt)
                if m:
                    try:
                        mileage_km = int(m.group(1).replace(" ", ""))
                    except ValueError:
                        pass

        if title and price:
            offers.append({
                "title": title,
                "price_pln": price,
                "year": year,
                "mileage_km": mileage_km,
                "url": url,
            })

    return offers


def _parse_prices_from_html(html: str) -> list[int]:
    """Wyciąga ceny PLN z HTML strony listingu Otomoto.

    Aktualny format Otomoto (2026): "price":"64000" jako string (PLN).
    Ceny w innych walutach (EUR) mają osobny "currency" key.
    """
    prices: list[int] = []

    # 1. Główny format: "price":"NNNNN" jako string (Otomoto 2026)
    for m in re.finditer(r'"price"\s*:\s*"(\d{4,8})"', html):
        try:
            v = int(m.group(1))
            if 1000 <= v <= 5_000_000:  # sane bounds
                prices.append(v)
        except ValueError:
            continue

    if prices:
        return prices

    # 2. Legacy format (jeśli wróci): {"value": int, "currency": "PLN"}
    next_data_match = re.search(
        r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL,
    )
    if next_data_match:
        import json as _json
        try:
            data = _json.loads(next_data_match.group(1))
        except Exception:
            data = None
        if data:
            def walk(obj):
                if isinstance(obj, dict):
                    if obj.get("currency") == "PLN" and isinstance(obj.get("value"), (int, float)):
                        v = int(obj["value"])
                        if 1000 <= v <= 5_000_000:
                            prices.append(v)
                    for vv in obj.values():
                        walk(vv)
                elif isinstance(obj, list):
                    for it in obj:
                        walk(it)
            walk(data)
            if prices:
                return prices

    # 3. Fallback: visible prices regex
    for m in re.finditer(r'>\s*([\d\s]{4,12})\s*</[^>]+>\s*<[^>]*PLN', html):
        raw = m.group(1).replace(" ", "").replace("\xa0", "")
        try:
            v = int(raw)
            if 1000 <= v <= 5_000_000:
                prices.append(v)
        except ValueError:
            continue

    return prices


def _aggregate_offers(offers: list[dict]) -> dict:
    """Liczy statystyki ze szczegółowych ofert (cena, rok, przebieg)."""
    if not offers:
        return {
            "low_pln": None, "high_pln": None, "mean_pln": None, "median_pln": None,
            "sample_size": 0, "avg_mileage_km": None, "avg_year": None,
            "top_offers": [],
        }

    prices = [o["price_pln"] for o in offers if o.get("price_pln")]
    mileages = [o["mileage_km"] for o in offers if o.get("mileage_km")]
    years = [o["year"] for o in offers if o.get("year")]

    if not prices:
        return {
            "low_pln": None, "high_pln": None, "mean_pln": None, "median_pln": None,
            "sample_size": 0, "avg_mileage_km": None, "avg_year": None,
            "top_offers": [],
        }

    # Trim 5% outlierów cen
    sorted_p = sorted(prices)
    n = len(sorted_p)
    if n >= 10:
        trim = int(n * 0.05)
        sorted_p = sorted_p[trim:n - trim] if trim else sorted_p

    # Top 5 najtańszych ofert (broker analizuje konkurencję)
    top_offers = sorted(offers, key=lambda o: o.get("price_pln") or float("inf"))[:5]

    return {
        "low_pln": sorted_p[0],
        "high_pln": sorted_p[-1],
        "mean_pln": int(statistics.mean(sorted_p)),
        "median_pln": int(statistics.median(sorted_p)),
        "sample_size": len(sorted_p),
        "avg_mileage_km": int(statistics.mean(mileages)) if mileages else None,
        "avg_year": round(statistics.mean(years), 1) if years else None,
        "top_offers": top_offers,
    }


def _aggregate(prices: list[int]) -> dict:
    """[Legacy] Liczy low/high/mean/median z odrzuceniem skrajnych outlierów."""
    if not prices:
        return {"low_pln": None, "high_pln": None, "mean_pln": None,
                "median_pln": None, "sample_size": 0}

    sorted_p = sorted(prices)
    n = len(sorted_p)
    # Trim 5% z każdej strony (jeśli >=10 punktów)
    if n >= 10:
        trim = int(n * 0.05)
        sorted_p = sorted_p[trim:n - trim] if trim else sorted_p

    return {
        "low_pln": sorted_p[0],
        "high_pln": sorted_p[-1],
        "mean_pln": int(statistics.mean(sorted_p)),
        "median_pln": int(statistics.median(sorted_p)),
        "sample_size": len(sorted_p),
    }


def lookup_market_price(
    make: str,
    model: Optional[str] = None,
    year_from: Optional[int] = None,
    year_to: Optional[int] = None,
    damaged_only: bool = False,
    *,
    use_cache: bool = True,
) -> Optional[dict]:
    """Sync wrapper — sprawdza cache, jeśli miss to scrapeuje przez Playwright.

    Returns dict {low_pln, high_pln, mean_pln, median_pln, sample_size, query_url}
    lub None gdy Otomoto niedostępne / brak wyników.
    """
    if not make:
        return None

    # 1) Cache
    if use_cache:
        cached = market_price_cache.get_cached(make, model, year_from, year_to, damaged_only)
        if cached is not None:
            return cached

    url = _build_url(make, model, year_from, year_to, damaged_only)
    logger.info("[Otomoto] Lookup: %s", url)

    # 2) Scrape via sync Playwright (hybrid_reports jest sync)
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.warning("[Otomoto] playwright.sync_api niedostępne — pomijam lookup")
        market_price_cache.store(
            make, model, year_from, year_to, damaged_only,
            query_url=url, error="playwright_unavailable",
        )
        return None

    html = ""
    error_msg: Optional[str] = None
    try:
        with sync_playwright() as p:
            # Użyj systemowego Chrome (channel=chrome) jeśli BROWSER_CHANNEL=chrome,
            # inaczej bundled Chromium (default Playwright).
            _channel = (os.getenv("BROWSER_CHANNEL", "").strip().lower() or None)
            _launch_kwargs = {"headless": True, "args": ["--no-sandbox"]}
            if _channel and _channel != "chromium":
                _launch_kwargs["channel"] = _channel
            browser = p.chromium.launch(**_launch_kwargs)
            context = browser.new_context(
                user_agent=OTOMOTO_USER_AGENT,
                locale="pl-PL",
                viewport={"width": 1280, "height": 900},
            )
            page = context.new_page()
            try:
                page.goto(url, timeout=OTOMOTO_TIMEOUT_MS, wait_until="domcontentloaded")
                # Otomoto ładuje listingi przez Next.js — daj czas na hydrację
                try:
                    page.wait_for_selector('[data-testid="search-results"], main, article', timeout=8000)
                except Exception:
                    pass
                html = page.content()
            except Exception as exc:
                error_msg = f"playwright_navigation: {type(exc).__name__}: {str(exc)[:120]}"
                logger.warning("[Otomoto] %s", error_msg)
            finally:
                page.close()
                context.close()
                browser.close()
    except Exception as exc:
        error_msg = f"playwright_launch: {type(exc).__name__}: {str(exc)[:120]}"
        logger.warning("[Otomoto] %s", error_msg)

    if error_msg or not html:
        market_price_cache.store(
            make, model, year_from, year_to, damaged_only,
            query_url=url, error=error_msg or "empty_html",
        )
        return None

    # Cloudflare challenge detection
    if "Just a moment" in html or "challenge-platform" in html or "cf-mitigated" in html.lower():
        logger.info("[Otomoto] Cloudflare challenge wykryty — negative cache")
        market_price_cache.store(
            make, model, year_from, year_to, damaged_only,
            query_url=url, error="cloudflare_challenge",
        )
        return None

    # Próbuj najpierw structured (z title/year/mileage) — daje detail dla broker
    offers = _parse_offers_from_html(html)

    if not offers:
        # Fallback: tylko ceny
        prices = _parse_prices_from_html(html)
        if not prices:
            logger.info("[Otomoto] Brak cen w HTML (%d KB) — negative cache", len(html) // 1024)
            market_price_cache.store(
                make, model, year_from, year_to, damaged_only,
                query_url=url, error="no_prices_parsed",
            )
            return None
        prices = prices[:OTOMOTO_MAX_LISTINGS]
        agg = _aggregate(prices)
        agg["query_url"] = url
        agg["cached"] = False
        agg["top_offers"] = []
        agg["avg_mileage_km"] = None
        agg["avg_year"] = None
    else:
        offers = offers[:OTOMOTO_MAX_LISTINGS]
        agg = _aggregate_offers(offers)
        agg["query_url"] = url
        agg["cached"] = False

    market_price_cache.store(
        make, model, year_from, year_to, damaged_only,
        low_pln=agg["low_pln"], high_pln=agg["high_pln"],
        mean_pln=agg["mean_pln"], median_pln=agg["median_pln"],
        sample_size=agg["sample_size"], query_url=url,
    )
    logger.info(
        "[Otomoto] %s %s %s-%s: %d ofert, średnia %s PLN",
        make, model, year_from, year_to, agg["sample_size"], agg["mean_pln"],
    )
    return agg


# ============================================================================
# CLI/test entry
# ============================================================================
if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s | %(message)s")
    if len(sys.argv) >= 2:
        make = sys.argv[1]
        model = sys.argv[2] if len(sys.argv) >= 3 else None
        year_from = int(sys.argv[3]) if len(sys.argv) >= 4 else None
        year_to = int(sys.argv[4]) if len(sys.argv) >= 5 else None
        result = lookup_market_price(make, model, year_from, year_to, use_cache=False)
        import json as _json
        print(_json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print("Usage: python -m scraper.otomoto BMW M550i 2018 2022")
