#!/usr/bin/env python3
"""
Diagnostyka źródła Manheim — jedno wyszukiwanie i zrzut tego, co realnie wraca.

Po co: ManheimScraper nie zna endpointów Manheima na sztywno, tylko wyławia
rekordy pojazdów z odpowiedzi XHR SPA i mapuje pola przez aliasy
(`scraper/manheim.py: _FIELD_ALIASES`). Ten skrypt pokazuje surowe rekordy i
wynik mapowania, więc po zmianie frontu Manheima widać od razu, który alias
przestał trafiać — bez zgadywania.

Uruchomienie (wymaga USE_EXTENSIONS=true, HEADLESS=false i zalogowanego BidWise):
    python scripts/manheim_probe.py BMW X5
    python scripts/manheim_probe.py Toyota RAV4 --year-from 2019 --year-to 2022

Zrzuty lądują w data/manheim_probe/.
"""
import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from parser.manheim_parser import parse_manheim_html  # noqa: E402
from parser.models import ClientCriteria  # noqa: E402
from scraper.browser_context import MANHEIM_PROFILE_DIR  # noqa: E402
from scraper.manheim import ManheimScraper, _pick  # noqa: E402
from scraper.manheim_session import cdp_url, config_ready  # noqa: E402

OUTPUT_DIR = Path("data/manheim_probe")
MAPPED_FIELDS = (
    "vin", "year", "make", "model", "trim", "odometer", "current_bid", "buy_now",
    "condition_grade", "damage", "title_type", "city", "state", "auction_date",
    "lot_id", "url", "image",
)


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("make")
    parser.add_argument("model", nargs="?")
    parser.add_argument("--year-from", type=int)
    parser.add_argument("--year-to", type=int)
    parser.add_argument("--max-results", type=int, default=3)
    parser.add_argument(
        "--login-wait", type=int, default=300,
        help="ile sekund czekać na ręczne zalogowanie BidWise (0 = nie czekaj)",
    )
    args = parser.parse_args()

    if not config_ready():
        print(
            "Brak rozpakowanej wtyczki w MANHEIM_EXTENSION_DIR "
            "(python scripts/sync_bidwise_extension.py).",
            file=sys.stderr,
        )
        return 1

    if cdp_url():
        print(f"Podłączam się po CDP do Chrome pod {cdp_url()} (BidWise ze Web Store).")
    else:
        print(
            "Brak MANHEIM_CHROME_CDP_URL — fallback: własny Chromium z rozpakowaną "
            f"wtyczką, profil {MANHEIM_PROFILE_DIR}. Uwaga: BidWise wczytana jako "
            "unpacked wyłącza sama siebie po kilku sekundach."
        )

    criteria = ClientCriteria(
        make=args.make,
        model=args.model,
        year_from=args.year_from,
        year_to=args.year_to,
        max_results=args.max_results,
        sources=["manheim"],
    )

    scraper = ManheimScraper()
    try:
        saved = await scraper.scrape(
            criteria, auction_window_hours=None, login_wait_s=args.login_wait
        )
    except Exception as exc:
        if "ECONNREFUSED" in str(exc) or "connect_over_cdp" in str(exc):
            print(
                f"\nNie mogę się połączyć z Chrome pod {cdp_url()}.\n"
                "Odpal najpierw w osobnym terminalu:\n"
                "    bash scripts/manheim_chrome_debug.sh\n"
                "i zostaw to okno Chrome otwarte (BidWise zainstalowana ze Web Store "
                "i zalogowana).",
                file=sys.stderr,
            )
            return 1
        raise

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    raw_path = OUTPUT_DIR / "captured_records.json"
    raw_path.write_text(
        json.dumps(scraper._captured, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    print(f"Zapytanie: {scraper.build_search_query(criteria)!r}")
    print(f"Przechwycone rekordy: {len(scraper._captured)} → {raw_path}")

    if scraper._captured:
        sample = scraper._captured[0]
        print("\nMapowanie aliasów na pierwszym rekordzie (None = alias nie trafił):")
        for field in MAPPED_FIELDS:
            print(f"  {field:<16} {_pick(sample, field)!r}")
        print("\nKlucze najwyższego poziomu:", sorted(sample)[:40])

    print(f"\nZapisane detale: {len(saved)}")
    for path, url in saved:
        lot = parse_manheim_html(Path(path))
        summary = (
            f"{lot.year} {lot.make} {lot.model} | {lot.odometer_mi} mi | "
            f"buy_now={lot.buy_now_price_usd} | {lot.location_city},{lot.location_state}"
            if lot
            else "PARSE FAILED"
        )
        print(f"  {url}\n    {path}\n    {summary}")

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
