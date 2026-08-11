"""
Agent sprzedażowy: ocena leada, walidator wiadomości i bramka zatwierdzania.

Trzy rzeczy, których te testy pilnują najmocniej:

  1. Ocena jest deterministyczna — te same dane dają tę samą liczbę. Bez tego nie da
     się na niej oprzeć decyzji, komu poświęcić dzień.
  2. Nic nie wychodzi do klienta bez zgody brokera. To jest wymaganie produktu,
     a nie szczegół implementacji.
  3. Walidator odrzuca wiadomości łamiące zasady z `agent-sprzedaz-usa.md` —
     zwłaszcza te, które obiecują coś, czego nie dotrzymamy.
"""
from datetime import datetime, timedelta, timezone

import pytest

from sales import db
from sales.agent import mentions_unknown_amount, validate_message
from sales.intake import _detect_budget_pln, _detect_damage_ok, _detect_years
from sales.models import Author, Channel, Draft, Lead, Segment, Stage
from sales.qualification import MIN_SENSIBLE_BID_USD, score_lead


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    """Każdy test dostaje własną bazę — inaczej kolejność testów zmienia wyniki."""
    monkeypatch.setenv("APP_DATABASE_PATH", str(tmp_path / "sales.db"))
    yield


def lead(**over) -> Lead:
    base = dict(
        name="Marek Kowalski",
        phone="48605083832",
        raw_request="szukam auta",
        make="FORD",
        model="EXPLORER",
        year_from=2019,
        budget_pln=120_000.0,
        timeline_days=30,
        damage_ok=True,
        max_odometer_mi=90_000,
        last_client_message_at=datetime.now(timezone.utc),
    )
    base.update(over)
    return Lead(**base)


# ───────────────────────────────────────────────────────────────── ocena leada


def test_ocena_jest_powtarzalna():
    """Ta sama liczba przy każdym wywołaniu — na tym stoi cała priorytetyzacja."""
    l = lead()
    assert score_lead(l).score == score_lead(l).score


def test_komplet_danych_daje_segment_a():
    wynik = score_lead(lead())
    assert wynik.segment is Segment.A
    assert not wynik.missing


def test_brak_danych_nie_karze_lecz_zwieksza_wage_reszty():
    """Lead, który napisał trzy zdania, nie jest gorszy od tego, który wypełnił dziesięć pól.

    Wagi składowych bez danych rozkładają się na resztę, więc suma wag zawsze wynosi 1.
    """
    ubogi = lead(timeline_days=None, damage_ok=None, last_client_message_at=None)
    wynik = score_lead(ubogi)
    assert sum(c.weight for c in wynik.components) == pytest.approx(1.0)
    assert wynik.component("urgency") is None
    assert wynik.component("damage_awareness") is None


def test_odmowa_auta_po_szkodzie_blokuje_wyzsze_segmenty():
    """Najczęstszy powód straconych leadów — nie wolno go rozmyć w punktach."""
    wynik = score_lead(lead(damage_ok=False))
    assert wynik.segment not in (Segment.A, Segment.B)
    assert any("nieuszkodzone" in f for f in wynik.red_flags)
    assert "model zakupu" in wynik.next_action


def test_budzet_bez_szans_blokuje_wyzsze_segmenty():
    """25 tys. zł to stawka poniżej progu aut na chodzie — 'kwalifikowany' byłby kłamstwem."""
    wynik = score_lead(lead(budget_pln=25_000.0))
    assert wynik.segment not in (Segment.A, Segment.B)
    assert any("na części" in f for f in wynik.red_flags)


def test_liczby_w_notatkach_nie_zjadaja_przecinkow_zdaniowych():
    """Formatujemy liczbę, nie zdanie — inaczej ginie przecinek po 'na części'."""
    wynik = score_lead(lead(budget_pln=25_000.0))
    flaga = next(f for f in wynik.red_flags if "na części" in f)
    assert "na części, nie do jeżdżenia" in flaga


def test_budzet_liczony_przez_sufit_a_nie_przez_kurs():
    """Koszty stałe nie skalują się z ceną auta, więc dzielenie budżetu przez kurs kłamie."""
    wynik = score_lead(lead(budget_pln=60_000.0))
    nota = wynik.component("budget").note
    assert "stawkę ok." in nota
    # 60 tys. zł to nie 15 tys. USD — po odjęciu transportu, odprawy i prowizji zostaje mniej.
    stawka = int("".join(ch for ch in nota.split("USD")[0] if ch.isdigit()))
    assert MIN_SENSIBLE_BID_USD < stawka < 12_000


def test_mlody_rocznik_przy_malym_budzecie_dostaje_flage():
    wynik = score_lead(lead(year_from=datetime.now(timezone.utc).year, budget_pln=55_000.0))
    assert any("rocznik" in f for f in wynik.red_flags)


def test_cisza_obniza_zaangazowanie():
    swiezy = score_lead(lead()).component("engagement").value
    stary = score_lead(
        lead(last_client_message_at=datetime.now(timezone.utc) - timedelta(days=30))
    ).component("engagement").value
    assert stary < swiezy


def test_brak_kontaktu_jest_pierwsza_rzecza_do_zrobienia():
    wynik = score_lead(lead(phone=None, email=None))
    assert "kontakt" in wynik.next_action.lower()


# ────────────────────────────────────────────────────── wyciąganie danych z treści


@pytest.mark.parametrize(
    "tekst, oczekiwany",
    [
        ("budżet 120 tys. pod klucz", 120_000),
        ("mam 30 tysięcy złotych", 30_000),
        ("do 85k", 85_000),
        ("80-120 tysięcy", 120_000),          # górna granica jest budżetem
        ("BMW X5 rocznik 2024", None),        # rocznik to nie kwota
        ("przebieg do 150000 mil", None),     # liczba bez waluty to nie budżet
    ],
)
def test_budzet_z_tresci_zgloszenia(tekst, oczekiwany):
    """Reguła musi działać, gdy parser modelowy padnie — inaczej gubimy podany budżet."""
    assert _detect_budget_pln(tekst) == (float(oczekiwany) if oczekiwany else None)


@pytest.mark.parametrize(
    "tekst, oczekiwany",
    [
        ("wiem że to auta powypadkowe, to mi nie przeszkadza", True),
        ("auto musi być bezwypadkowe", False),
        ("szukam forda", None),  # nie pytaliśmy — nie zgadujemy
    ],
)
def test_zgoda_na_auto_po_szkodzie_z_tresci(tekst, oczekiwany):
    assert _detect_damage_ok(tekst) is oczekiwany


def test_rocznik_z_tresci():
    assert _detect_years("Ford Explorer 2020+") == (2020, None)
    assert _detect_years("rocznik 2018-2021") == (2018, 2021)


# ──────────────────────────────────────────────────────────── walidator wiadomości


@pytest.mark.parametrize(
    "tresc",
    [
        "Daję gwarancję na to auto.",                 # obietnica nie do dotrzymania
        "To auto jest bezwypadkowe.",                 # z aukcji nie ma bezwypadkowych
        "Proszę o zaliczkę na konto.",                # ustalenia finansowe to broker
        "Mogę dać rabat na prowizję.",                # nie agent o tym decyduje
        "Ocena tego auta to 8/10.",                   # metryka wewnętrzna
        "Auto ma clean title.",                       # żargon aukcyjny
        "Świetna okazja!",                            # ton sprzedażowy i wykrzyknik
        "Na pewno wygramy tę aukcję.",                # obietnica wyniku licytacji
    ],
)
def test_walidator_odrzuca_zakazane_wiadomosci(tresc):
    assert validate_message(tresc) is None


def test_walidator_przepuszcza_poprawna_wiadomosc():
    tresc = (
        "Sprawdziłem dostępne auta z tego rocznika. "
        "Wszystkie są po szkodzie, głównie uszkodzenia przodu. "
        "Czy taki zakres wchodzi w grę?"
    )
    assert validate_message(tresc) == tresc


def test_walidator_tnie_zbyt_dlugie_wiadomosci():
    assert validate_message("Zdanie. " * 40) is None


def test_walidator_odrzuca_wiecej_niz_cztery_zdania():
    assert validate_message("Raz. Dwa. Trzy. Cztery. Pięć.") is None


def test_cyfry_sa_dozwolone_bo_agent_powtarza_policzona_cene():
    """Inaczej niż w prozie oferty — bez cyfr nie da się rozmawiać o cenie."""
    assert validate_message("Cena pod klucz to 95 000 zł.") is not None


def test_kwota_spoza_danych_jest_wykrywana():
    """Model nie ma prawa przeliczać. Kwota, której nie policzyliśmy, jest zmyślona."""
    oferty = [{"cena_pln": 95_000, "nazwa": "Ford Explorer"}]
    assert not mentions_unknown_amount("Cena pod klucz to 95 000 zł.", oferty)
    assert mentions_unknown_amount("Wyjdzie jakieś 88 000 zł.", oferty)
    assert not mentions_unknown_amount("Sprawdzę i wrócę z konkretem.", oferty)


# ───────────────────────────────────────────────────────── bramka zatwierdzania


def test_draft_nie_jest_wiadomoscia_dopoki_broker_nie_zatwierdzi():
    """Rdzeń wymagania: nic nie idzie do klienta bez zgody."""
    zapisany = db.create_lead(lead())
    draft = db.save_draft(
        Draft(lead_id=zapisany.id, text="Dzień dobry, mam pytanie.", channel=Channel.WHATSAPP,
              rationale="test")
    )

    assert db.messages(zapisany.id) == []
    assert len(db.pending_drafts()) == 1

    wiadomosc = db.approve_and_send(draft.id)
    assert wiadomosc.author is Author.BROKER
    assert db.pending_drafts() == []
    assert len(db.messages(zapisany.id)) == 1


def test_dwa_klikniecia_nie_wysylaja_dwa_razy():
    """Panel bywa klikany dwa razy. Klient nie może dostać tej samej wiadomości podwójnie."""
    zapisany = db.create_lead(lead())
    draft = db.save_draft(
        Draft(lead_id=zapisany.id, text="Treść.", channel=Channel.WHATSAPP, rationale="")
    )
    assert db.approve_and_send(draft.id) is not None
    assert db.approve_and_send(draft.id) is None
    assert len(db.messages(zapisany.id)) == 1


def test_poprawka_brokera_wygrywa_z_propozycja_agenta():
    zapisany = db.create_lead(lead())
    draft = db.save_draft(
        Draft(lead_id=zapisany.id, text="Wersja agenta.", channel=Channel.WHATSAPP, rationale="")
    )
    db.approve_and_send(draft.id, edited_text="Wersja brokera.")
    assert db.messages(zapisany.id)[0].text == "Wersja brokera."


def test_odrzucony_draft_zostaje_do_wgladu():
    """Odrzucone propozycje są jedynym materiałem, z którego widać, w czym agent się myli."""
    zapisany = db.create_lead(lead())
    draft = db.save_draft(
        Draft(lead_id=zapisany.id, text="Zła propozycja.", channel=Channel.WHATSAPP, rationale="")
    )
    assert db.reject_draft(draft.id, reason="za nachalne")
    assert db.pending_drafts() == []
    assert db.get_draft(draft.id).rejected_at is not None
    assert "za nachalne" in db.get_draft(draft.id).rationale


def test_zatwierdzenie_przesuwa_etap_gdy_draft_tak_mowi():
    zapisany = db.create_lead(lead(stage=Stage.NOWY))
    draft = db.save_draft(
        Draft(lead_id=zapisany.id, text="Pytanie.", channel=Channel.WHATSAPP,
              rationale="", stage_after=Stage.KWALIFIKACJA)
    )
    db.approve_and_send(draft.id)
    assert db.get_lead(zapisany.id).stage is Stage.KWALIFIKACJA


def test_ten_sam_klient_nie_dostaje_drugiej_kartoteki():
    db.create_lead(lead(phone="48605083832"))
    znaleziony = db.find_lead_by_contact(phone="48605083832")
    assert znaleziony is not None
    assert znaleziony.name == "Marek Kowalski"


def test_wiadomosc_klienta_odswieza_zegar_zaangazowania():
    zapisany = db.create_lead(lead(last_client_message_at=None))
    db.add_message(zapisany.id, author=Author.KLIENT, text="Dzień dobry", channel=Channel.WHATSAPP)
    assert db.get_lead(zapisany.id).last_client_message_at is not None
