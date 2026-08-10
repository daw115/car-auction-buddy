"""Oferta dla klienta: liczby z kalkulatora, słowa od modelu, nic więcej."""
import re

import pytest

from parser.models import AIAnalysis, AnalyzedLot, CarLot, ClientCriteria
from pricing.import_calculator import calculate_lot_import_costs
from report import offer_agent
from report.offer_agent import MAX_CLIENT_CARS, build_car, build_offer

_TAGS = re.compile(r"<[^>]+>")


def text_of(html: str) -> str:
    """Sam tekst maila — bez atrybutów, w których siedzą adresy zdjęć i linki."""
    return re.sub(r"\s+", " ", _TAGS.sub(" ", html))


def lot(
    model="RAV4",
    price=10_000.0,
    state="FL",
    odo=51_000,
    year=2019,
    trim=None,
    damage="Front End",
    title="Salvage",
    lot_id="L1",
) -> CarLot:
    return CarLot(
        source="copart", lot_id=lot_id, url="https://copart.example/L1", year=year,
        make="Toyota", model=model, trim=trim, odometer_mi=odo, current_bid_usd=price,
        location_state=state, location_city="MIAMI SOUTH", damage_primary=damage,
        title_type=title, images=["https://img.example/1.jpg"],
    )


def analyzed(car: CarLot, score=8.2, flags=None) -> AnalyzedLot:
    return AnalyzedLot(
        lot=car,
        analysis=AIAnalysis(
            lot_id=car.lot_id, score=score, recommendation="POLECAM",
            red_flags=flags or [], client_description_pl="Opis z analizy.",
        ),
        is_top_recommendation=True,
    )


# ────────────────────────────────────────────────────────────────────── ceny


def test_price_is_landed_cost_plus_commission_not_fx_conversion():
    """Regresja v1: model dostawał polecenie 'przelicz USD × 4,0'.

    Lot za 10 000 USD kosztował w mailu 40 000 zł, a klient płaci prawie dwa razy tyle.
    """
    car = build_car(analyzed(lot(price=10_000.0)))
    costs = calculate_lot_import_costs(car.lot, excise_rate=car.excise_rate)

    assert car.landed_pln == pytest.approx(costs["private_total_pln"])
    assert car.client_price_pln == pytest.approx(car.landed_pln + car.fee_pln)
    assert car.client_price_pln > 70_000  # nie 40 000 z kursu
    assert car.fee_pln > 0


def test_commission_is_inside_the_quoted_price():
    """Prowizja doliczona po ofercie to dopłata po drodze — tego obiecujemy nie robić."""
    car = build_car(analyzed(lot()))
    assert car.client_price_pln - car.landed_pln == pytest.approx(car.fee_pln)


def test_unknown_engine_size_uses_the_higher_excise_rate():
    """Zaniżona akcyza to zaniżona cena. W aukcjach z USA silnik poniżej 2,0 l to wyjątek."""
    nieznany = build_car(analyzed(lot(trim=None)))
    maly = build_car(analyzed(lot(trim="1.6 VVT-i")))
    duzy = build_car(analyzed(lot(trim="3.0 TDI")))

    assert nieznany.excise_rate == offer_agent.EXCISE_LARGE
    assert maly.excise_rate == offer_agent.EXCISE_SMALL
    assert duzy.excise_rate == offer_agent.EXCISE_LARGE
    assert duzy.client_price_pln > maly.client_price_pln


def test_electric_car_pays_no_excise():
    criteria = ClientCriteria(make="Tesla", fuel_type="Electric")
    car = build_car(analyzed(lot(model="Model 3")), criteria=criteria)
    assert car.excise_rate == 0.0


def test_price_is_rounded_up_never_down():
    """Kwota niższa od rzeczywistej to reklamacja przy odbiorze."""
    car = build_car(analyzed(lot()))
    quoted = int(re.sub(r"\D", "", car.price_label))
    assert quoted >= car.client_price_pln
    assert quoted % offer_agent.PRICE_ROUNDING_PLN == 0


def test_company_settlement_costs_more_than_private():
    """Firma płaci VAT od całości — ta sama aukcja kosztuje więcej pod klucz."""
    prywatnie = build_car(analyzed(lot()), settlement="private")
    firma = build_car(analyzed(lot()), settlement="company")
    assert firma.client_price_pln > prywatnie.client_price_pln


def test_lot_without_a_price_is_skipped():
    """Auto bez ceny w ofercie to zaproszenie do rozmowy o tym, czego nie wiemy."""
    bez_ceny = CarLot(source="iaai", lot_id="X", url="u", make="Toyota")
    offer = build_offer([analyzed(lot()), bez_ceny], use_llm=False)
    assert len(offer.cars) == 1


# ──────────────────────────────────────────────────────── co widzi klient


def test_client_email_never_leaks_internal_score_or_jargon():
    offer = build_offer([analyzed(lot(), score=9.4)], use_llm=False)
    body = text_of(offer.client_html).lower()

    for zakazane in ("score", "9.4", "/10", "salvage", "copart", "$", "usd", "lot "):
        assert zakazane not in body
    assert offer_agent._leaks(offer.client_html) == []


def test_auction_jargon_is_translated_to_polish():
    offer = build_offer(
        [analyzed(lot(damage="Front End", title="Salvage"))], use_llm=False
    )
    body = text_of(offer.client_html)
    assert "uszkodzony przód" in body
    assert "dokumenty auta powypadkowego" in body


def test_unknown_damage_is_admitted_not_smoothed_over():
    """Brak danych mówimy wprost — v1 nazywał to 'minor cosmetic issues'."""
    offer = build_offer([analyzed(lot(damage="Unknown Code 77"))], use_llm=False)
    assert "do potwierdzenia" in text_of(offer.client_html)


def test_mileage_is_shown_in_kilometres():
    offer = build_offer([analyzed(lot(odo=51_000))], use_llm=False)
    assert "82 tys. km" in text_of(offer.client_html)


def test_client_sees_at_most_four_cars_broker_sees_all():
    """Więcej pozycji paraliżuje wybór; broker musi widzieć całość."""
    lots = [analyzed(lot(lot_id=f"L{i}", model=f"M{i}")) for i in range(7)]
    offer = build_offer(lots, use_llm=False)

    assert len(offer.cars) == 7
    assert text_of(offer.client_html).count("tys. km") == MAX_CLIENT_CARS
    assert "M6" in text_of(offer.broker_html)


def test_price_note_says_what_is_and_is_not_included():
    offer = build_offer([analyzed(lot())], use_llm=False)
    body = text_of(offer.client_html)
    assert "odprawa celna" in body and "prowizja" in body
    # Rejestracji kalkulator nie liczy, więc nie wolno jej wliczać w cenę.
    assert "Poza nią zostaje rejestracja" in body


def test_price_is_framed_as_todays_bid_not_a_fixed_price():
    """Cena aukcyjna to stawka — aukcja może pójść wyżej."""
    offer = build_offer([analyzed(lot())], use_llm=False)
    assert "licytacja może pójść wyżej" in text_of(offer.client_html)


def test_empty_offer_says_so_instead_of_pretending():
    offer = build_offer([], use_llm=False)
    assert "nie mam auta" in text_of(offer.client_html)
    assert offer.warnings and not offer.has_offers


# ─────────────────────────────────────────────────────── walidacja prozy


def test_prose_with_digits_is_rejected():
    """Cyfra od modelu to liczba, której nikt nie policzył."""
    assert offer_agent._clean_prose("Auto po stłuczce przodu.", 130)
    assert offer_agent._clean_prose("Cena to 40 000 zł pod klucz.", 130) is None


@pytest.mark.parametrize(
    "zdanie",
    [
        "To okazja życia, drugiej takiej nie będzie.",
        "Auto jak nowe, stan idealny.",
        "Daję gwarancję na cały układ napędowy.",
        "Pewny zysk przy odsprzedaży.",
        "Świetne auto!",
        "Polecam 🔥",
        "Ten lot ma salvage title i wysoki score.",
    ],
)
def test_prose_breaking_the_rules_is_dropped(zdanie):
    assert offer_agent._clean_prose(zdanie, 200) is None


def test_broker_note_may_contain_numbers():
    """Notatkę czyta broker, nie klient — tam liczby są potrzebne."""
    prose, _ = offer_agent._validated_prose(
        {"broker_note": "Przy locie L1 uważać na próg 12 000 USD."}, []
    )
    assert prose["broker_note"]


def test_rejected_prose_is_reported_to_the_broker():
    """Broker ma zobaczyć, że model próbował czegoś, czego nie wolno."""
    car = build_car(analyzed(lot()))
    prose, warnings = offer_agent._validated_prose(
        {"intro": "Mam dla Pana 3 auta!", "cars": [{"id": "L1", "why": "Okazja życia."}]},
        [car],
    )
    assert prose["intro"] is None and prose["why"] == {}
    assert len(warnings) == 2


def test_model_prose_reaches_the_email_when_it_is_clean(monkeypatch):
    monkeypatch.setattr(
        offer_agent, "_call_llm",
        lambda system, user: '{"intro": "Wybrałem auta pod Pana kryteria.",'
                             ' "cars": [{"id": "L1", "why": "Uszkodzenie jest kosmetyczne."}],'
                             ' "closing": "Podesłać kalkulację?", "broker_note": "OK"}',
    )
    offer = build_offer([analyzed(lot())], use_llm=True)

    assert offer.prose_source == "llm"
    body = text_of(offer.client_html)
    assert "Uszkodzenie jest kosmetyczne." in body
    assert "Wybrałem auta pod Pana kryteria." in body


# ─────────────────────────────────────────────────────────────── odporność


def test_offer_survives_a_dead_model(monkeypatch):
    """Po scrapie i analizie oferta bez zdań 'dlaczego' jest lepsza niż wyjątek."""
    def padnij(system, user):
        raise RuntimeError("Gemini 503")

    monkeypatch.setattr(offer_agent, "_call_llm", padnij)
    offer = build_offer([analyzed(lot())], use_llm=True)

    assert offer.prose_source == "deterministic"
    assert offer.client_html and "tys. km" in text_of(offer.client_html)
    assert any("model nieosiągalny" in w for w in offer.warnings)


def test_offer_survives_garbage_from_the_model(monkeypatch):
    monkeypatch.setattr(offer_agent, "_call_llm", lambda system, user: "przepraszam, nie mogę")
    offer = build_offer([analyzed(lot())], use_llm=True)
    assert offer.prose_source == "deterministic"


def test_pipeline_entry_point_returns_broker_brief_and_client_mail(monkeypatch):
    monkeypatch.setattr(offer_agent, "_call_llm", lambda system, user: "{}")
    broker, klient = offer_agent.generate_offers_with_agent(
        top_lots=[analyzed(lot())], remaining_lots=[], client_name="Kliencie",
        search_query="Toyota RAV4",
    )
    assert "Brief ofertowy" in broker and "Dzień dobry" in klient
    # "Kliencie" to placeholder parsera, nie imię — nie witamy się nim.
    assert "Kliencie" not in klient


# ──────────────────────────────────────────────────────── brief dla brokera


def test_broker_brief_shows_the_full_calculation_and_the_auction_link():
    offer = build_offer([analyzed(lot())], use_llm=False)
    brief = offer.broker_html

    assert "https://copart.example/L1" in brief
    assert "Prowizja" in brief and "Sprowadzenie" in brief
    assert "Akcyza (stawka)" in brief


def test_broker_brief_lists_what_is_missing_before_bidding():
    """Checklista liczona z danych, nie zgadywana — brak VIN-u to brak historii."""
    goly = lot()
    goly.images = []
    offer = build_offer([analyzed(goly, flags=["poduszki zadziałały"])], use_llm=False)
    brief = text_of(offer.broker_html)

    assert "brak pełnego VIN" in brief
    assert "za mało na ocenę stanu" in brief
    assert "poduszki zadziałały" in brief


def test_broker_brief_shows_the_alternative_settlement():
    """Broker widzi obie ścieżki rozliczenia, bo to pytanie do klienta."""
    offer = build_offer([analyzed(lot())], use_llm=False)
    assert "Drugi wariant rozliczenia" in offer.broker_html


def test_budget_is_mentioned_only_when_something_fits_in_it():
    """'Mam auta pod budżet 60 tys.' przy cenach od 62 tys. czyta się jak niedosłuchanie."""
    tanie = ClientCriteria(make="Toyota", budget_pln_to=200_000)
    drogie = ClientCriteria(make="Toyota", budget_pln_to=40_000)

    assert "pod budżet" in text_of(build_offer([analyzed(lot())], criteria=tanie, use_llm=False).client_html)
    assert "pod budżet" not in text_of(build_offer([analyzed(lot())], criteria=drogie, use_llm=False).client_html)
