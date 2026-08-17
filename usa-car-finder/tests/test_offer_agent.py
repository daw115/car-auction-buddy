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
    """Firma płaci VAT od całości — ta sama aukcja kosztuje więcej pod drzwi."""
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


def test_price_note_lists_what_the_price_covers():
    offer = build_offer([analyzed(lot())], use_llm=False)
    body = text_of(offer.client_html)
    assert "odprawa celna" in body and "prowizja" in body


def test_registration_is_not_mentioned_in_the_price():
    """Kalkulator jej nie liczy — ani nie obiecujemy, ani nie zagadujemy tematu w cenie."""
    offer = build_offer([analyzed(lot())], use_llm=False)
    assert "rejestracj" not in text_of(offer.client_html).lower()


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
    assert offer_agent._clean_prose("Cena to 40 000 zł pod drzwi.", 130) is None


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


def test_proxy_model_alias_without_a_proxy_url_fails_loudly(monkeypatch):
    """Klucz i alias modelu z .env należą do proxy — na oficjalnym API dają 404.

    Ścieżka Anthropic jest ratunkowa, więc bez tej kontroli błąd wychodził dopiero
    wtedy, gdy pierwszy provider już padł.
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "")
    monkeypatch.setattr(offer_agent, "OFFER_MODEL", "claude-sonnet-4-6-thinking")

    with pytest.raises(RuntimeError, match="alias proxy"):
        offer_agent._check_anthropic_config()

    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://api.oneprovider.dev")
    offer_agent._check_anthropic_config()  # z proxy alias jest poprawny


@pytest.mark.parametrize(
    "intro, oczekiwane",
    [
        ("Panie Marku, znalazłem auto w Pana budżecie.", "Znalazłem auto w Pana budżecie."),
        ("Dzień dobry, mam dla Pana dwa auta.", "Mam dla Pana dwa auta."),
        ("Witam! Wybrałem auta pod Pana kryteria.", "Wybrałem auta pod Pana kryteria."),
        ("Wybrałem auta pod Pana kryteria.", "Wybrałem auta pod Pana kryteria."),
    ],
)
def test_second_greeting_is_cut_out(intro, oczekiwane):
    """Szablon wita się sam — "Dzień dobry, Marek, Panie Marku, ..." wyszło z realnego wywołania."""
    prose, _ = offer_agent._validated_prose({"intro": intro}, [])
    assert prose["intro"] == oczekiwane


def test_greeting_only_intro_falls_back_to_the_deterministic_one():
    prose, _ = offer_agent._validated_prose({"intro": "Dzień dobry!"}, [])
    assert prose["intro"] is None


def test_stripping_a_greeting_does_not_eat_the_first_real_word():
    """Regresja: wycinanie wołacza po 'Dzień dobry' zjadało pierwsze słowo treści."""
    assert offer_agent._strip_greeting("Dzień dobry, Mam dla Pana dwa auta.") == "Mam dla Pana dwa auta."
    assert offer_agent._strip_greeting("Witam! Wybrałem auta.") == "Wybrałem auta."
    assert offer_agent._strip_greeting("Dzień dobry, Panie Marku, mam dwa auta.") == "Mam dwa auta."


def test_our_own_intro_obeys_the_no_digits_rule():
    """Zakaz cyfr obowiązuje też wersję deterministyczną — "Mam 1 auto" brzmi jak log."""
    offer = build_offer([analyzed(lot(lot_id=f"L{i}", model=f"M{i}")) for i in range(3)], use_llm=False)
    intro = text_of(offer.client_html).split("2019")[0]
    assert "trzy auta" in intro
    assert not re.search(r"Mam \d", intro)


# ────────────────────────────────────────────── budżet: auta ponad kwotę klienta


def over_budget(car: CarLot) -> AnalyzedLot:
    """Lot z werdyktem scoringu: dobra ocena, cena ponad budżet klienta."""
    item = analyzed(car, score=8.9)
    item.analysis.recommendation = "PONAD BUDŻET"
    item.is_top_recommendation = False
    car.raw_data = dict(car.raw_data or {})
    car.raw_data["unified_score"] = {
        "score": 8.9,
        "recommendation": "PONAD BUDŻET",
        "over_budget": True,
        "disqualifiers": [],
        "budget": {"over": True, "gap_pln": 92_588, "note": "ponad budżet o 92 588 zł"},
    }
    return item


def test_over_budget_car_never_fills_a_slot_in_the_client_email():
    """Regresja: od kiedy scoring nie zeruje takich lotów, stoją wysoko w rankingu.

    Bez filtra wypełniałyby wolne miejsca w czwórce dla klienta — z ceną pod drzwi
    i bez słowa o tym, że przekraczają kwotę, którą klient podał.
    """
    tanie = analyzed(lot(lot_id="TANI", price=6_000.0))
    drogie = over_budget(lot(lot_id="DROGI", price=30_000.0, model="Highlander"))

    offer = build_offer([tanie, drogie], use_llm=False)
    tresc = text_of(offer.client_html)

    assert "RAV4" in tresc
    assert "Highlander" not in tresc
    assert any("ponad budżet" in w for w in offer.warnings)


def test_broker_still_sees_the_over_budget_car():
    """Broker ma je zobaczyć — to on decyduje, czy zaproponować dołożenie."""
    offer = build_offer(
        [analyzed(lot(lot_id="TANI", price=6_000.0)),
         over_budget(lot(lot_id="DROGI", price=30_000.0, model="Highlander"))],
        use_llm=False,
    )
    assert "Highlander" in text_of(offer.broker_html)


def test_broker_can_let_an_over_budget_car_through_and_it_is_named_as_such():
    offer = build_offer(
        [over_budget(lot(lot_id="DROGI", price=30_000.0, model="Highlander"))],
        use_llm=False,
        allow_over_budget=True,
    )
    tresc = text_of(offer.client_html)

    assert "Highlander" in tresc
    assert "powyżej podanego budżetu" in tresc
    assert any("UWAGA" in w for w in offer.warnings)


def test_intro_does_not_promise_the_budget_when_a_car_exceeds_it():
    """Deterministyczna proza też nie może twierdzić, że wszystko się mieści."""
    criteria = ClientCriteria(make="Toyota", budget_pln_to=60_000)
    offer = build_offer(
        [analyzed(lot(lot_id="TANI", price=6_000.0)),
         over_budget(lot(lot_id="DROGI", price=30_000.0, model="Highlander"))],
        criteria=criteria,
        use_llm=False,
        allow_over_budget=True,
    )
    assert "budżet" not in text_of(offer.client_html).lower().split("cena pod drzwi")[0]


def test_model_sentence_claiming_budget_fit_is_rejected_for_an_over_budget_car():
    """Zdanie bez cyfr i bez żargonu przechodziło wszystkie dotychczasowe bramki."""
    car = build_car(over_budget(lot(lot_id="DROGI", price=30_000.0)))
    assert car.over_budget

    validated, warnings = offer_agent._validated_prose(
        {"cars": [{"id": "DROGI", "why": "To auto mieści się w Pana budżecie."}]}, [car]
    )
    assert "DROGI" not in validated["why"]
    assert any("DROGI" in w for w in warnings)


def test_over_budget_label_comes_from_scoring_not_a_copy():
    """Przepisana etykieta rozjechałaby się po cichu — oferta przestałaby rozpoznawać
    auta ponad budżet i twierdziłaby, że mieszczą się w kwocie klienta."""
    from scoring import OVER_BUDGET

    assert offer_agent.OVER_BUDGET_LABEL is OVER_BUDGET


def test_agent_prompt_is_looked_up_in_several_places(tmp_path, monkeypatch):
    """Release na serwerze dostaje tylko usa-car-finder/, a prompt leży w korzeniu repo.

    Regresja z produkcji: pliku nie było, oferta cicho szła bez prozy modelu przez
    kilkanaście wdrożeń — fallback działał, więc nikt tego nie zauważył.
    """
    w_aplikacji = tmp_path / "agent-oferta-auto-usa.md"
    w_aplikacji.write_text("PROMPT Z RELEASE", encoding="utf-8")
    monkeypatch.setattr(
        offer_agent, "AGENT_PROMPT_CANDIDATES",
        (tmp_path / "nie-ma.md", w_aplikacji),
    )
    assert offer_agent._load_agent_prompt() == "PROMPT Z RELEASE"


def test_missing_prompt_names_every_place_it_looked(tmp_path, monkeypatch):
    monkeypatch.setattr(
        offer_agent, "AGENT_PROMPT_CANDIDATES", (tmp_path / "a.md", tmp_path / "b.md")
    )
    with pytest.raises(FileNotFoundError, match="a.md.*b.md"):
        offer_agent._load_agent_prompt()
