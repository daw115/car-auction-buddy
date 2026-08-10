"""Testy źródła Manheim: gating sesji, normalizacja rekordów, limit TOP 3."""
import json

import pytest
from pydantic import ValidationError

from parser.manheim_parser import parse_manheim_html
from parser.models import CarLot, ClientCriteria
from parser import manheim_records
from scraper import manheim as manheim_scraper
from scraper import manheim_session
from scraper.automated_scraper import AutomatedScraper

LISTING = {
    "vehicleId": "WO7788991",
    "vehicle": {
        "vin": "5UXCR6C05L9C12345",
        "modelYear": 2020,
        "make": "BMW",
        "model": "X5",
        "trim": "xDrive40i",
    },
    "odometer": "42,110",
    "conditionGrade": 4.1,
    "buyNowPrice": "$28,500",
    "locationCity": "Atlanta",
    "stateAbbreviation": "GA",
    "saleDate": 1786400000000,
    "imageUrl": "https://images.manheim.com/vehicle/front.jpg",
}


def _write_detail(tmp_path, record: dict, body: str = "<h1>VDP</h1>"):
    path = tmp_path / "lot.html"
    path.write_text(
        "<html><body>"
        + body
        + f'<script id="usacar-manheim-listing" type="application/json">{json.dumps(record)}</script>'
        + "</body></html>",
        encoding="utf-8",
    )
    return path


def _criteria(**overrides) -> ClientCriteria:
    base = {"make": "BMW", "model": "X5", "sources": ["manheim"]}
    base.update(overrides)
    return ClientCriteria(**base)


def test_criteria_accepts_manheim_and_still_rejects_unknown_sources():
    assert _criteria().sources == ["manheim"]
    assert ClientCriteria(make="BMW", sources=["copart", "manheim"]).sources == [
        "copart",
        "manheim",
    ]
    with pytest.raises(ValidationError):
        ClientCriteria(make="BMW", sources=["ove"])


def _unpacked_plugin(tmp_path):
    extension = tmp_path / "bidwise"
    extension.mkdir()
    (extension / "manifest.json").write_text(
        json.dumps({"manifest_version": 3, "name": "BidWise"}), encoding="utf-8"
    )
    return extension


def _used_profile(tmp_path):
    profile = tmp_path / "chrome_profile_manheim"
    (profile / "Default").mkdir(parents=True)
    (profile / "Default" / "Preferences").write_text("{}", encoding="utf-8")
    return profile


def test_cdp_url_alone_makes_manheim_ready(monkeypatch, tmp_path):
    """Droga produkcyjna: Chrome operatora po CDP, bez rozpakowanej wtyczki."""
    monkeypatch.setenv("MANHEIM_EXTENSION_DIR", str(tmp_path / "bez-wtyczki"))
    monkeypatch.setenv("MANHEIM_CHROME_PROFILE_DIR", str(tmp_path / "bez-profilu"))
    monkeypatch.setenv("MANHEIM_CHROME_CDP_URL", "http://127.0.0.1:9223")

    assert manheim_session.config_ready() is True
    assert manheim_session.session_ready() is True

    monkeypatch.setenv("MANHEIM_CHROME_CDP_URL", "")
    assert manheim_session.config_ready() is False
    assert manheim_session.session_ready() is False


def test_readiness_ignores_global_extension_and_headless_switches(monkeypatch, tmp_path):
    """Manheim ma własny headed kontekst — USE_EXTENSIONS/HEADLESS go nie dotyczą."""
    monkeypatch.setenv("MANHEIM_CHROME_CDP_URL", "")
    monkeypatch.setenv("MANHEIM_EXTENSION_DIR", str(_unpacked_plugin(tmp_path)))
    monkeypatch.setenv("MANHEIM_CHROME_PROFILE_DIR", str(_used_profile(tmp_path)))

    for use_extensions, headless in (("false", "true"), ("true", "false")):
        monkeypatch.setenv("USE_EXTENSIONS", use_extensions)
        monkeypatch.setenv("HEADLESS", headless)
        assert manheim_session.config_ready() is True
        assert manheim_session.session_ready() is True


def test_config_ready_does_not_require_an_existing_profile(monkeypatch, tmp_path):
    """Pierwsze uruchomienie (probe) musi móc dopiero założyć profil."""
    monkeypatch.setenv("MANHEIM_CHROME_CDP_URL", "")
    monkeypatch.setenv("MANHEIM_EXTENSION_DIR", str(_unpacked_plugin(tmp_path)))
    monkeypatch.setenv("MANHEIM_CHROME_PROFILE_DIR", str(tmp_path / "jeszcze-nie-ma"))

    assert manheim_session.config_ready() is True
    assert manheim_session.session_ready() is False


def test_readiness_false_when_plugin_directory_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("MANHEIM_CHROME_CDP_URL", "")
    monkeypatch.setenv("MANHEIM_EXTENSION_DIR", str(tmp_path / "nie-ma"))
    monkeypatch.setenv("MANHEIM_CHROME_PROFILE_DIR", str(_used_profile(tmp_path)))

    assert manheim_session.config_ready() is False
    assert manheim_session.session_ready() is False


def test_result_limit_defaults_to_three_and_never_exceeds_request(monkeypatch):
    monkeypatch.delenv("MANHEIM_MAX_RESULTS", raising=False)
    assert manheim_session.result_limit() == 3
    assert manheim_session.result_limit(15) == 3
    assert manheim_session.result_limit(1) == 1

    monkeypatch.setenv("MANHEIM_MAX_RESULTS", "5")
    assert manheim_session.result_limit(15) == 5


def test_vehicle_records_are_recognized_regardless_of_nesting():
    assert manheim_records.looks_like_vehicle(LISTING["vehicle"]) is True
    assert manheim_records.looks_like_vehicle({"make": "BMW"}) is False
    assert manheim_records.pick(LISTING, "year") == 2020
    assert manheim_records.pick(LISTING, "odometer") == "42,110"
    assert manheim_records.pick(LISTING, "lot_id") == "WO7788991"


def test_prefilter_rejects_lots_outside_client_criteria():
    scraper = manheim_scraper.ManheimScraper()
    assert scraper._matches_criteria(LISTING, _criteria()) is True
    assert scraper._matches_criteria(LISTING, _criteria(year_from=2022)) is False
    assert scraper._matches_criteria(LISTING, _criteria(max_odometer_mi=30_000)) is False
    assert scraper._matches_criteria(LISTING, _criteria(budget_usd=20_000)) is False
    assert scraper._matches_criteria(LISTING, _criteria(model="X3")) is False


def test_search_query_uses_year_only_when_single_model_year():
    scraper = manheim_scraper.ManheimScraper()
    assert scraper.build_search_query(_criteria(year_from=2019, year_to=2019)) == "2019 BMW X5"
    assert scraper.build_search_query(_criteria(year_from=2018, year_to=2021)) == "BMW X5"


def test_parser_reads_injected_listing_and_normalizes_units(tmp_path):
    lot = parse_manheim_html(_write_detail(tmp_path, LISTING))

    assert lot is not None
    assert (lot.source, lot.lot_id, lot.make, lot.model) == ("manheim", "WO7788991", "BMW", "X5")
    assert lot.vin == "5UXCR6C05L9C12345"
    assert lot.full_vin == lot.vin
    assert (lot.odometer_mi, lot.odometer_km) == (42110, 67769)
    assert lot.buy_now_price_usd == 28500.0
    assert lot.seller_type == "dealer"
    assert lot.damage_primary == "Condition grade 4.1"
    assert lot.auction_date.startswith("2026-")
    assert lot.images == ["https://images.manheim.com/vehicle/front.jpg"]


def test_parser_falls_back_to_vin_from_page_when_listing_block_missing(tmp_path):
    path = tmp_path / "bare.html"
    path.write_text(
        "<html><body><p>VIN 5UXCR6C05L9C12345</p></body></html>", encoding="utf-8"
    )

    lot = parse_manheim_html(path)

    assert lot is not None
    assert lot.vin == "5UXCR6C05L9C12345"
    assert lot.lot_id == "5UXCR6C05L9C12345"


def test_manheim_lot_ids_survive_url_extraction():
    extract = AutomatedScraper._extract_lot_id_from_url
    assert extract("https://search.manheim.com/results#/vdp/WO7788991") == "WO7788991"
    assert extract("https://search.manheim.com/vehicle/9f2c-uuid-77") == "9f2c-uuid-77"
    # Copart/IAAI zachowują dotychczasowe wyciąganie samych cyfr.
    assert extract("https://www.copart.com/lot/45661246") == "45661246"
    assert extract("https://www.iaai.com/VehicleDetail/12345678") == "12345678"


def test_truncation_reserves_slots_for_manheim(monkeypatch):
    monkeypatch.delenv("MANHEIM_MAX_RESULTS", raising=False)
    lots = [CarLot(source="copart", lot_id=str(i), url=f"c{i}") for i in range(15)]
    lots += [CarLot(source="manheim", lot_id=f"m{i}", url=f"m{i}") for i in range(3)]

    kept = AutomatedScraper._truncate_with_manheim_quota(lots, 15)

    assert len(kept) == 15
    assert sum(1 for lot in kept if lot.source == "manheim") == 3
    assert [lot.lot_id for lot in kept if lot.source == "copart"] == [str(i) for i in range(12)]


def test_truncation_is_noop_when_list_fits():
    lots = [CarLot(source="copart", lot_id="1", url="c1")]
    assert AutomatedScraper._truncate_with_manheim_quota(lots, 15) is lots


def test_dateless_manheim_lots_survive_auction_window_filter(monkeypatch):
    monkeypatch.setenv("MANHEIM_IGNORE_AUCTION_WINDOW", "true")
    scraper = AutomatedScraper()
    lots = [
        CarLot(source="manheim", lot_id="m1", url="m1"),
        CarLot(source="copart", lot_id="c1", url="c1"),
    ]

    kept = scraper._filter_by_auction_date(lots, min_hours=12, max_hours=120)

    assert [lot.lot_id for lot in kept] == ["m1"]

    monkeypatch.setenv("MANHEIM_IGNORE_AUCTION_WINDOW", "false")
    assert scraper._filter_by_auction_date(lots, min_hours=12, max_hours=120) == []


def test_money_objects_and_split_graphql_records_are_merged():
    """SPA Manheima rozbija pojazd na kilka zapytań i owija kwoty w obiekt.

    Kształt wzięty z realnego przechwytu onesearch-api.manheim.com/graphql.
    """
    bid_status = {
        "__typename": "Listing",
        "vin": "2C4RC1EG4JR177880",
        "id": "454022371",
        "highBid": {"amount": 14250, "currency": "USD"},
        "endTime": "2026-08-12T18:00:00Z",
        "bidCount": 7,
    }
    vehicle = {
        "vin": "2C4RC1EG4JR177880",
        "year": 2018,
        "make": "Chrysler",
        "model": "Pacifica",
        "odometer": 61234,
    }

    assert manheim_records.pick(bid_status, "current_bid") == 14250
    assert manheim_records.pick(bid_status, "auction_date") == "2026-08-12T18:00:00Z"

    scraper = manheim_scraper.ManheimScraper()
    scraper._captured = [bid_status, vehicle]
    merged = scraper._dedup_captured()

    assert len(merged) == 1
    assert merged[0]["year"] == 2018
    assert merged[0]["bidCount"] == 7
    assert manheim_records.pick(merged[0], "make") == "Chrysler"


def test_scraper_reuses_an_authenticated_tab_and_ignores_logged_out_ones():
    """BidWise autoryzuje sesję per karta — obcej karty nie wolno brać."""

    class FakePage:
        def __init__(self, url):
            self.url = url

    class FakeContext:
        def __init__(self, urls):
            self.pages = [FakePage(u) for u in urls]

    find = manheim_scraper.ManheimScraper._find_manheim_page
    assert find(FakeContext(["https://www.iaai.com/", "about:blank"])) is None
    assert find(FakeContext(["https://site.manheim.com/en/locations.html"])) is None
    good = find(FakeContext(
        ["about:blank", "https://search.manheim.com/results#/results/abc-123"]
    ))
    assert good is not None and "search.manheim.com" in good.url


def test_logged_in_check_trusts_the_url_not_page_text():
    """Wylogowana sesja jest odsyłana na site.manheim.com — to jedyny pewny sygnał."""
    import asyncio

    class FakePage:
        def __init__(self, url):
            self.url = url

        async def inner_text(self, _selector):
            raise AssertionError("nie powinniśmy sięgać po treść strony")

    check = manheim_scraper.ManheimScraper()._is_logged_in
    assert asyncio.run(check(FakePage("https://search.manheim.com/results#/results/abc"))) is True
    assert asyncio.run(check(FakePage("https://site.manheim.com/en/locations.html"))) is False


def test_collector_mode_returns_top_three_without_touching_a_browser(monkeypatch, tmp_path):
    """Ścieżka produkcyjna: rekordy z kolektora, zero Playwrighta.

    Kształt pól jak w realnej odpowiedzi getExecuteSearchId.
    """
    import asyncio

    def record(vin, year, model, odo, grade):
        return {
            "vin": vin,
            "unifiedId": f"OVE.FAAO.{vin[-6:]}",
            "sourceYear": str(year),
            "sourceMake": "Toyota",
            "sourceModel": model,
            "odometer": odo,
            "conditionGrade": grade,
            "pickupLocation": "GA - Manheim Atlanta",
            "saleDate": "2026-08-12T20:00:00Z",
        }

    records = [
        record("JTMRWRFV9PD20481%d" % i, 2023, "RAV4", 20_000 + i, 5 - i * 0.1)
        for i in range(6)
    ]
    monkeypatch.setattr(
        manheim_scraper.ManheimScraper, "_collector_records", staticmethod(lambda: records)
    )
    monkeypatch.setenv("MANHEIM_SOURCE_MODE", "collector")
    monkeypatch.setenv("HTML_CACHE_DIR", str(tmp_path))
    monkeypatch.delenv("MANHEIM_MAX_RESULTS", raising=False)
    # 0 = nie zlecaj rozszerzeniu, korzystaj z tego co już zebrane.
    monkeypatch.setenv("MANHEIM_JOB_TIMEOUT_SECONDS", "0")

    criteria = ClientCriteria(make="Toyota", model="RAV4", sources=["manheim"], max_results=15)
    saved = asyncio.run(manheim_scraper.ManheimScraper().scrape(criteria))

    assert len(saved) == 3
    lots = [parse_manheim_html(__import__("pathlib").Path(path)) for path, _ in saved]
    assert all(lot is not None and lot.source == "manheim" for lot in lots)
    assert all(lot.make == "Toyota" and lot.model == "RAV4" for lot in lots)
    assert all(lot.location_state == "GA" for lot in lots)


def test_collector_mode_is_explicit_about_an_empty_store(monkeypatch, tmp_path):
    import asyncio

    monkeypatch.setattr(
        manheim_scraper.ManheimScraper, "_collector_records", staticmethod(list)
    )
    monkeypatch.setenv("MANHEIM_SOURCE_MODE", "collector")
    monkeypatch.setenv("HTML_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("MANHEIM_JOB_TIMEOUT_SECONDS", "0")

    criteria = ClientCriteria(make="Toyota", sources=["manheim"])
    assert asyncio.run(manheim_scraper.ManheimScraper().scrape(criteria)) == []
