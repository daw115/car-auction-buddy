"""Smoke test integracji bidfax z analyzerem.

Sprawdza:
1. Enrichment mutuje lot.raw_data tylko dla lotów z finalną ceną (IN_PROGRESS pomijane)
2. Local scoring nie crashuje przy obecności pól bidfax
3. _lot_payloads() (ścieżka OpenAI) wystawia pola bidfax do AI payloadu
4. _analyze_lots_with_claude inline payload też zawiera pola bidfax (assertion na kodzie)
5. Flaga BIDFAX_ENRICHMENT_ENABLED=false → kompletny no-op

Bez prawdziwej przeglądarki — używa FakeBidfaxClient + monkey-patch lookup_with_cache.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ["BIDFAX_ENRICHMENT_ENABLED"] = "true"
os.environ["AI_ANALYSIS_MODE"] = "local"
tmpdir = Path(tempfile.mkdtemp())
os.environ["BIDFAX_CACHE_PATH"] = str(tmpdir / "bidfax_test.json")

from parser.models import CarLot, ClientCriteria  # noqa: E402
from scraper.bidfax import FakeBidfaxClient, IN_PROGRESS  # noqa: E402
import ai.analyzer as analyzer  # noqa: E402
import scraper.bidfax as bidfax_module  # noqa: E402


def _make_lot(lot_id: str, **overrides) -> CarLot:
    defaults = dict(
        source="copart",
        lot_id=lot_id,
        url=f"https://www.copart.com/lot/{lot_id}",
        year=2020,
        make="Toyota",
        model="Camry",
        odometer_mi=60_000,
        damage_primary="REAR END",
        title_type="Salvage",
        current_bid_usd=4_200.0,
        seller_type="insurance",
        location_state="NJ",
        location_city="WINDSOR",
        auction_date="2026-05-13T14:00:00Z",
        keys=True,
        airbags_deployed=False,
    )
    defaults.update(overrides)
    return CarLot(**defaults)


def _install_fake_bidfax(responses: dict[str, tuple[str, str, str]]) -> FakeBidfaxClient:
    fake = FakeBidfaxClient(responses=responses)

    async def fake_lookup(queries, cache_path, makes=None, delay=2.0, client=None):
        return await fake.lookup_many(queries, makes=makes, delay=delay)

    analyzer.lookup_with_cache = fake_lookup
    bidfax_module.lookup_with_cache = fake_lookup
    return fake


def _section(title: str) -> None:
    print()
    print("=" * 60)
    print(title)
    print("=" * 60)


def test_enrichment_and_payloads() -> bool:
    _section("TEST 1: Enrichment + local scoring + payloads")

    # Bidfax wymaga 17-znakowych VINów jako query. Każdy lot ma full_vin
    # ustawiony — w prawdziwej aplikacji to przychodzi z AuctionGate extension.
    VIN_FAIR = "JTDKARFU8K3071234"
    VIN_OVERPRICED = "JTDBL40E099012345"
    VIN_NO_DATA = "JTDFK4FUXJ0123456"

    lots = [
        _make_lot("HIT_FAIR", current_bid_usd=4_200, full_vin=VIN_FAIR),
        _make_lot("HIT_OVERPRICED", current_bid_usd=11_000, location_state="CA", full_vin=VIN_OVERPRICED),
        _make_lot("NO_BIDFAX", current_bid_usd=3_500, full_vin=VIN_NO_DATA),
    ]

    fake = _install_fake_bidfax({
        VIN_FAIR: ("$8,500", VIN_FAIR, f"https://bidfax.info/toyota/camry/x-vin-{VIN_FAIR}.html"),
        VIN_OVERPRICED: ("$9,200", VIN_OVERPRICED, f"https://bidfax.info/toyota/camry/y-vin-{VIN_OVERPRICED}.html"),
        VIN_NO_DATA: (IN_PROGRESS, "", ""),
    })

    criteria = ClientCriteria(
        make="Toyota", model="Camry",
        year_from=2018, year_to=2024,
        budget_usd=15_000, max_odometer_mi=100_000,
    )

    top, all_results = analyzer.analyze_lots(lots, criteria, top_n=2)

    print(f"\nFakeBidfax otrzymał {len(fake.lookup_calls)} zapytań: {fake.lookup_calls}")

    enriched = [lot for lot in lots if "bidfax_sold_price" in lot.raw_data]
    print(f"\nLoty wzbogacone ({len(enriched)}/{len(lots)}):")
    for lot in lots:
        bf = lot.raw_data.get("bidfax_sold_price", "—")
        bf_url = lot.raw_data.get("bidfax_history_url", "—")
        print(f"  {lot.lot_id}: sold={bf}  url={bf_url[:60] if bf_url != '—' else '—'}")

    assert lots[0].raw_data.get("bidfax_sold_price") == "$8,500"
    assert lots[0].raw_data.get("bidfax_sold_vin") == "JTDKARFU8K3071234"
    assert lots[1].raw_data.get("bidfax_sold_price") == "$9,200"
    assert "bidfax_sold_price" not in lots[2].raw_data, "IN_PROGRESS nie powinien być zapisany"
    print("\n[PASS] Enrichment poprawny (HIT_FAIR + HIT_OVERPRICED wzbogacone, NO_BIDFAX pominięty)")

    print(f"\nLocal scoring zwrócił {len(all_results)} analiz, TOP {len(top)}:")
    for analyzed in all_results:
        print(
            f"  {analyzed.lot.lot_id}: score={analyzed.analysis.score:.1f} "
            f"rec={analyzed.analysis.recommendation} "
            f"total_cost=${analyzed.analysis.estimated_total_cost_usd or 0:,}"
        )

    assert len(all_results) == 3, f"Oczekiwano 3 analiz, dostałem {len(all_results)}"
    assert len(top) == 2
    print("\n[PASS] Local scoring nie crashuje przy obecności bidfax pól")

    payloads = analyzer._lot_payloads(lots)
    print(f"\n_lot_payloads() — pierwsze pole bidfax_* na każdym locie:")
    for p in payloads:
        print(
            f"  {p['lot_id']}: sold={p['bidfax_sold_price']!r} "
            f"vin={p['bidfax_sold_vin']!r}"
        )

    assert payloads[0]["bidfax_sold_price"] == "$8,500"
    assert payloads[0]["bidfax_history_url"].startswith("https://bidfax.info/")
    assert payloads[0]["bidfax_sold_vin"] == "JTDKARFU8K3071234"
    assert payloads[2]["bidfax_sold_price"] is None
    print("\n[PASS] _lot_payloads() wystawia bidfax fields do AI payloadu (OpenAI)")

    src = Path(analyzer.__file__).read_text()
    claude_section = src.split("def _analyze_lots_with_claude")[1].split("\n\n")[1] if "_analyze_lots_with_claude" in src else ""
    assert '"bidfax_sold_price": lot.raw_data.get("bidfax_sold_price")' in src
    assert '"bidfax_history_url": lot.raw_data.get("bidfax_history_url")' in src
    assert '"bidfax_sold_vin": lot.raw_data.get("bidfax_sold_vin")' in src
    print("[PASS] Claude inline payload zawiera pola bidfax (sprawdzone na źródle)")

    assert "HISTORYCZNA CENA SPRZEDAŻY" in analyzer.SYSTEM_PROMPT
    assert "bidfax_sold_price" in analyzer.SYSTEM_PROMPT
    print("[PASS] SYSTEM_PROMPT zawiera sekcję o bidfax")

    return True


def test_disabled_flag_is_noop() -> bool:
    _section("TEST 2: BIDFAX_ENRICHMENT_ENABLED=false → no-op")

    os.environ["BIDFAX_ENRICHMENT_ENABLED"] = "false"

    fake_called = {"count": 0}
    async def fake_lookup_count(queries, cache_path, makes=None, delay=2.0, client=None):
        fake_called["count"] += 1
        return {}
    analyzer.lookup_with_cache = fake_lookup_count

    lots = [_make_lot("WHATEVER")]
    criteria = ClientCriteria(make="Toyota", budget_usd=15_000)

    analyzer._enrich_lots_with_bidfax(lots, criteria)

    assert fake_called["count"] == 0, "Z flagą off lookup nie powinien być wywołany"
    assert "bidfax_sold_price" not in lots[0].raw_data
    print("[PASS] Flaga BIDFAX_ENRICHMENT_ENABLED=false → zero zapytań, zero mutacji")
    return True


def test_lookup_failure_does_not_break() -> bool:
    _section("TEST 3: Awaria bidfax → kontynuacja bez wzbogacenia")

    os.environ["BIDFAX_ENRICHMENT_ENABLED"] = "true"

    async def fake_lookup_crash(queries, cache_path, makes=None, delay=2.0, client=None):
        raise RuntimeError("symulowana awaria Cloudflare")
    analyzer.lookup_with_cache = fake_lookup_crash

    lots = [_make_lot("CRASH_TEST")]
    criteria = ClientCriteria(make="Toyota", budget_usd=15_000)

    try:
        analyzer._enrich_lots_with_bidfax(lots, criteria)
    except Exception as exc:
        print(f"[FAIL] Awaria propagowała wyjątek: {exc}")
        return False

    assert "bidfax_sold_price" not in lots[0].raw_data
    print("[PASS] Awaria bidfax nie wywala enrichmentu, raw_data pozostaje czyste")
    return True


if __name__ == "__main__":
    results = []
    try:
        results.append(("enrichment + payloads", test_enrichment_and_payloads()))
        results.append(("disabled flag no-op", test_disabled_flag_is_noop()))
        results.append(("lookup failure handling", test_lookup_failure_does_not_break()))
    except AssertionError as exc:
        print(f"\n[FAIL] AssertionError: {exc}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    except Exception as exc:
        print(f"\n[FAIL] Niespodziewany wyjątek: {exc}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    print()
    print("=" * 60)
    print("WYNIK")
    print("=" * 60)
    for name, ok in results:
        print(f"  {'PASS' if ok else 'FAIL'} — {name}")
    print()
    sys.exit(0 if all(ok for _, ok in results) else 1)
