"""Stawki cła i akcyzy po zmianach z 2026 roku.

Ta suita pilnuje trzech rzeczy, z których każda kosztuje realne pieniądze przy każdej
wycenie: kraju montażu z VIN-u, rozpoznania hybrydy i kierunku, w którym mylimy się
przy braku danych.

Kierunek pomyłki jest tu najważniejszy i ma osobne testy. Zawyżona wycena wraca do nas
jako przegrana oferta — przykro, ale odwracalne. Zaniżona wraca do klienta jako dopłata
po fakcie, czyli jako złamana obietnica "bez dopłat po drodze", na której stoi cała
sprzedaż. Dlatego każda niepewność ma iść w stronę droższą.
"""
from datetime import date

import pytest

from parser.models import CarLot
from pricing import vin as vin_mod
from pricing.drivetrain import Drivetrain, detect
from pricing.tariff import (
    DUTY_PREFERENTIAL,
    DUTY_STANDARD,
    EXCISE_EV,
    EXCISE_HYBRID_MEDIUM,
    EXCISE_HYBRID_SMALL,
    EXCISE_ICE_LARGE,
    EXCISE_ICE_SMALL,
    duty_free_window_open,
    rates_for_lot,
)

PRZED_ZMIANA = date(2026, 6, 30)
PO_ZMIANIE = date(2026, 8, 11)
PO_WYGASNIECIU = date(2030, 1, 1)


def lot(**over) -> CarLot:
    base = dict(
        source="copart", lot_id="L1", url="u", year=2021,
        make="FORD", model="EXPLORER", current_bid_usd=15_000, location_state="FL",
    )
    base.update(over)
    return CarLot(**base)


# ─────────────────────────────────────────────────────────── kraj montażu z VIN-u


@pytest.mark.parametrize(
    "prefix, kraj, w_usa",
    [
        ("1FTFW1E85", "US", True),    # Ford z Michigan
        ("5YJ3E1EA7", "US", True),    # Tesla z Fremont — montaż w USA, ale patrz test o EV
        ("4T1BF1FK0", "US", True),    # Toyota z Kentucky
        ("2T3BFREV1", "CA", False),   # Toyota z Ontario
        ("3VW217AU9", "MX", False),   # Volkswagen z Puebli
        ("JTMBFREV0", "JP", False),   # Toyota z Japonii
        ("WBAJA9C50", "DE", False),   # BMW z Monachium
        ("KMHD84LF6", "KR", False),   # Hyundai z Ulsan
    ],
)
def test_kraj_montazu_bierze_sie_z_pierwszego_znaku(prefix, kraj, w_usa):
    """Marka nie mówi nic o kraju montażu — BMW bywa z USA, Ford z Meksyku."""
    wynik = vin_mod.origin(prefix + "12345678")
    assert wynik.country_code == kraj
    assert wynik.assembled_in_usa is w_usa
    assert wynik.confident


def test_zamaskowany_vin_z_copartu_wystarcza_do_ustalenia_cla():
    """Copart ukrywa sześć ostatnich znaków, ale kraj siedzi w pierwszym.

    To jest praktycznie ważne: kwalifikację do zerowego cła znamy z listy wyników,
    zanim otworzymy szczegóły aukcji i zanim cokolwiek zalicytujemy.
    """
    wynik = vin_mod.origin("1FTFW1E85MF******")
    assert wynik.assembled_in_usa
    assert wynik.confident


def test_smiec_w_polu_vin_nie_udaje_kraju():
    for bezwartosciowy in (None, "", "—", "brak", "1234"):
        assert not vin_mod.origin(bezwartosciowy).confident


# ────────────────────────────────────────────────────────────── rozpoznanie napędu


@pytest.mark.parametrize(
    "opis, oczekiwany",
    [
        ("2.5L I4 HYBRID", Drivetrain.HEV),
        ("SPORT PLUG-IN HYBRID", Drivetrain.PHEV),
        ("LIMITED 48V MILD HYBRID", Drivetrain.MHEV),
        ("3.6L V6 ETORQUE", Drivetrain.MHEV),
        ("LONG RANGE ELECTRIC", Drivetrain.BEV),
        ("PRIUS TWO", Drivetrain.HEV),
        ("WRANGLER 4XE", Drivetrain.PHEV),
        ("5.0L V8 XLT", Drivetrain.ICE),
    ],
)
def test_naped_z_opisu_wersji(opis, oczekiwany):
    assert detect(opis).kind is oczekiwany


def test_chevrolet_nie_jest_elektrykiem():
    """Wzorzec na 'EV' bez granic słowa łapał 'CHEVROLET' i zwalniał Silverado z akcyzy."""
    wynik = detect("CHEVROLET", "SILVERADO 1500", "5.3L V8")
    assert wynik.kind is Drivetrain.ICE
    assert not wynik.confident  # brak słowa-klucza to założenie, nie wiedza


# ───────────────────────────────────────────────────────────────────────── cło


def test_auto_z_usa_ma_zerowe_clo_po_pierwszym_lipca():
    stawki = rates_for_lot(lot(vin="1FMSK8DH1NG123456"), on=PO_ZMIANIE)
    assert stawki.duty_rate == DUTY_PREFERENTIAL
    assert stawki.duty_free


def test_to_samo_auto_przed_zmiana_placi_pelne_clo():
    stawki = rates_for_lot(lot(vin="1FMSK8DH1NG123456"), on=PRZED_ZMIANA)
    assert stawki.duty_rate == DUTY_STANDARD


def test_preferencja_wygasa_z_koncem_2029():
    """Kalkulator ma wrócić do 10% sam, bez czekania aż ktoś zauważy."""
    assert duty_free_window_open(PO_ZMIANIE)
    assert not duty_free_window_open(PO_WYGASNIECIU)
    assert rates_for_lot(lot(vin="1FMSK8DH1NG123456"), on=PO_WYGASNIECIU).duty_rate == DUTY_STANDARD


def test_auto_z_meksyku_kupione_w_usa_placi_clo():
    """Najczęstsza pułapka: 'amerykańskie' auto zmontowane w Puebli."""
    stawki = rates_for_lot(lot(vin="3VW217AU9JM123456"), on=PO_ZMIANIE)
    assert stawki.duty_rate == DUTY_STANDARD
    assert "Meksyk" in stawki.country_name


def test_elektryk_z_usa_nie_lapie_sie_na_zerowe_clo():
    """Pojazdy elektryczne wyłączono z listy — montaż we Fremont nic tu nie zmienia."""
    stawki = rates_for_lot(
        lot(vin="5YJ3E1EA7LF123456", make="TESLA", model="MODEL 3"), on=PO_ZMIANIE
    )
    assert stawki.drivetrain is Drivetrain.BEV
    assert stawki.duty_rate == DUTY_STANDARD
    assert stawki.excise_rate == EXCISE_EV  # akcyzy nie płaci mimo cła


def test_brak_vinu_liczy_clo_drozej_i_mowi_o_tym_wprost():
    """Bez VIN-u nie zgadujemy po marce — liczymy 10% i zapisujemy założenie."""
    stawki = rates_for_lot(lot(vin=None), on=PO_ZMIANIE)
    assert stawki.duty_rate == DUTY_STANDARD
    assert not stawki.certain
    assert any("Kraj montażu" in a for a in stawki.assumptions)


# ─────────────────────────────────────────────────────────────────────── akcyza


@pytest.mark.parametrize(
    "trim, oczekiwana",
    [
        ("1.6 TDI", EXCISE_ICE_SMALL),        # spalinowy do 2,0 l
        ("2.0 TFSI", EXCISE_ICE_SMALL),       # 1984 cm³ mieści się w progu
        ("3.5 V6", EXCISE_ICE_LARGE),         # spalinowy powyżej 2,0 l
        ("2.5L HYBRID", EXCISE_HYBRID_MEDIUM),  # hybryda 2000-3500 cm³
        ("1.8L HYBRID", EXCISE_HYBRID_SMALL),   # hybryda do 2000 cm³
        ("3.0L I6 48V", EXCISE_HYBRID_MEDIUM),  # mild hybrid — interpretacja MF z 2026
    ],
)
def test_stawki_akcyzy(trim, oczekiwana):
    assert rates_for_lot(lot(trim=trim), on=PO_ZMIANIE).excise_rate == oczekiwana


def test_mild_hybrid_polowi_akcyze_na_duzym_silniku():
    """Najbardziej dochodowa różnica: 18,6% wobec 9,3% na tym samym silniku."""
    spalinowy = rates_for_lot(lot(trim="3.0L I6"), on=PO_ZMIANIE)
    lagodna = rates_for_lot(lot(trim="3.0L I6 48V"), on=PO_ZMIANIE)
    assert spalinowy.excise_rate == EXCISE_ICE_LARGE
    assert lagodna.excise_rate == pytest.approx(spalinowy.excise_rate / 2)


def test_preferencja_hybrydowa_konczy_sie_na_3500_cm3():
    """Granica, o którą najłatwiej się potknąć przy amerykańskich autach.

    Duże V6 i V8 z instalacją 48 V — Ram 1500 eTorque 3.6, Hemi 5.7 — hybrydami
    w rozumieniu stawki są, ale pojemnością wychodzą ponad próg i płacą pełne 18,6%.
    Policzenie im 9,3% zaniżyłoby cenę o kilka tysięcy złotych, a takich aut jest
    na Copart bardzo dużo.
    """
    ponizej = rates_for_lot(lot(trim="3.5L V6 HYBRID"), on=PO_ZMIANIE)
    powyzej = rates_for_lot(lot(trim="3.6L V6 ETORQUE"), on=PO_ZMIANIE)
    assert ponizej.excise_rate == EXCISE_HYBRID_MEDIUM
    assert powyzej.excise_rate == EXCISE_ICE_LARGE


def test_hybryda_powyzej_3500_traci_preferencje():
    assert rates_for_lot(lot(trim="5.0L V8 HYBRID"), on=PO_ZMIANIE).excise_rate == EXCISE_ICE_LARGE


def test_nieznana_pojemnosc_liczy_akcyze_drozej():
    """Pomyłka w drugą stronę zaniża cenę o kilka tysięcy złotych."""
    stawki = rates_for_lot(lot(trim=None, model="EXPLORER"), on=PO_ZMIANIE)
    assert stawki.excise_rate == EXCISE_ICE_LARGE
    assert any("Pojemność" in a for a in stawki.assumptions)


# ─────────────────────────────────────────── wpływ na cenę, czyli po co to wszystko


def test_zerowe_clo_realnie_obniza_cene_pod_klucz():
    """Sens całej zmiany: to samo auto, dwa kraje montażu, inna cena dla klienta."""
    from scoring.budget import landed_cost_for_lot

    z_usa = landed_cost_for_lot(lot(vin="1FMSK8DH1NG123456", trim="2.0 ECOBOOST"))
    z_meksyku = landed_cost_for_lot(lot(vin="3FMSK8DH1NG123456", trim="2.0 ECOBOOST"))

    assert z_usa < z_meksyku
    # Cło wchodzi do podstawy VAT-u, więc oszczędność jest wyraźnie większa niż samo cło.
    assert (z_meksyku - z_usa) > 3_000


def test_sufit_budzetu_rosnie_gdy_clo_znika():
    """Przy tym samym budżecie klienta stać na wyższą stawkę na aukcji."""
    from scoring.budget import max_bid_for_budget

    zachowawczo = max_bid_for_budget(60_000, state="FL", duty_rate=DUTY_STANDARD)
    z_preferencja = max_bid_for_budget(60_000, state="FL", duty_rate=DUTY_PREFERENTIAL)
    assert z_preferencja.max_bid_usd > zachowawczo.max_bid_usd


def test_kalkulator_niesie_powody_do_briefu_brokera():
    """Broker ma zobaczyć, skąd wzięła się stawka, zanim zatwierdzi wysyłkę."""
    from pricing.import_calculator import calculate_lot_import_costs

    costs = calculate_lot_import_costs(lot(vin="1FMSK8DH1NG123456", trim="3.6 V6 ETORQUE"))
    assert costs["duty_rate"] == DUTY_PREFERENTIAL
    assert "montaż w USA" in costs["duty_reason"]
    assert costs["drivetrain"] == "mhev"


# ───────────────────────── elektryki, które udawały spalinowe (pomyłka zaniżająca)


@pytest.mark.parametrize(
    "marka, model",
    [
        ("BMW", "iX"), ("BMW", "i4"), ("BMW", "i7"),
        ("MERCEDES-BENZ", "EQE"), ("MERCEDES-BENZ", "EQS"),
        ("FORD", "MUSTANG MACH-E"), ("FORD", "F-150 LIGHTNING"),
        ("CADILLAC", "LYRIQ"), ("CHEVROLET", "BLAZER EV"),
        ("RIVIAN", "R1S"), ("TOYOTA", "BZ4X"), ("PORSCHE", "TAYCAN"),
        ("KIA", "EV6"), ("NISSAN", "ARIYA"), ("POLESTAR", "2"),
    ],
)
def test_elektryki_bez_slowa_electric_w_nazwie(marka, model):
    """Nazwa "iX" nie zawiera ani "EV", ani "ELECTRIC", a to jest elektryk.

    Pomyłka w tę stronę jest jedyną w całym module, która ZANIŻA cenę: elektryk wzięty
    za spalinowy dostaje cło 0% zamiast 10%, czyli kilkanaście tysięcy złotych mniej,
    niż klient faktycznie zapłaci.
    """
    assert detect(marka, model).kind is Drivetrain.BEV


@pytest.mark.parametrize(
    "marka, model, wersja",
    [
        ("BMW", "X7", "M60i"),
        ("BMW", "X5", "sDrive40i"),
        ("FORD", "F-150", "XLT 5.0 V8"),
        ("CHEVROLET", "SILVERADO 1500", "5.3 V8"),
        ("TOYOTA", "RAV4", "XLE"),
    ],
)
def test_spalinowe_nie_lapia_sie_na_wzorce_elektrykow(marka, model, wersja):
    """Rozszerzenie listy elektryków nie może zamienić X5 w elektryka."""
    assert detect(marka, model, wersja).kind is not Drivetrain.BEV


def test_ostrzezenie_o_elektryku_tylko_gdy_nie_wiemy_co_to_za_auto():
    """Przy komplecie pól ostrzeżenie odpalałoby się na każdym spalinowym aucie.

    Ostrzeżenie, które widać zawsze, przestaje być ostrzeżeniem — uczy ludzi je pomijać.
    """
    z_kompletem = rates_for_lot(lot(vin="1FMSK8DH1NG123456", make="FORD", model="EXPLORER"))
    bez_marki = rates_for_lot(lot(vin="1FMSK8DH1NG123456", make=None, model=None, trim="Long Range"))

    assert not any("elektryk" in a.lower() for a in z_kompletem.assumptions)
    assert any("elektryk" in a.lower() for a in bez_marki.assumptions)
