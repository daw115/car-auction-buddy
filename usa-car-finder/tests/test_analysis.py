"""
System analizy lotów: pokrycie danych, blokady i ranking.

Sedno tej suity to jedna rzecz: **liczba bez pewności kłamie**. Lot z Manheimu ma
pozycjowany raport stanu, lot z Copartu dwa pola opisu szkody. Grade 4,5 z jednego
i z drugiego to nie jest ta sama informacja, a ranking, który tego nie pokazuje,
zawsze wskaże Manheim — nie dlatego, że auto jest lepsze, tylko dlatego, że raport
jest bogatszy.

Druga rzecz to ogłoszenia. AutoGrade ich nie liczy i słusznie, bo opisują historię,
a nie stan blachy — ale to w nich siedzi tytuł brandowany. Test na Lemon Law jest tu
z realnego zbioru: X7 M60i z grade 5,0, zerowym cłem i ceną poniżej MMR, który
wygrywał ranking, dopóki nikt nie przeczytał ogłoszeń.
"""
import pytest

from parser.models import CarLot
from scoring.analysis import (
    analyze,
    announcement_flags,
    best_per_source,
    contradictions,
    coverage_for_lot,
    rank,
)


def manheim(**listing) -> CarLot:
    base = {
        "conditionGrade": 5.0,
        "hasFrameDamage": False,
        "hasPriorPaint": False,
        "greenLight": True,
        "redLight": False,
        "salvageVehicle": False,
        "titleStatus": "Title Present",
        "mmrPrice": 50_000,
        "tireTreadLF": 9, "tireTreadRF": 9, "tireTreadLR": 8, "tireTreadRR": 8,
    }
    base.update(listing)
    return CarLot(
        source="manheim", lot_id="M1", url="u", vin="5UX33EM09R9S33233",
        year=2024, make="BMW", model="X7", trim="M60i", odometer_mi=10_000,
        current_bid_usd=45_000, location_state="PA", keys=True,
        raw_data={"listing": base},
    )


def copart(**over) -> CarLot:
    base = dict(
        source="copart", lot_id="C1", url="u", vin="1FMSK8DH1NG123456",
        year=2022, make="FORD", model="EXPLORER", odometer_mi=40_000,
        current_bid_usd=20_000, location_state="FL", keys=True,
        damage_primary="Front End", title_type="Clean",
    )
    base.update(over)
    return CarLot(**base)


# ──────────────────────────────────────────── pewność danych, nie tylko ocena


def test_manheim_ma_wyzsze_pokrycie_niz_copart():
    """To jest powód istnienia pola `coverage`: raporty nie są równe."""
    m = coverage_for_lot(manheim())
    c = coverage_for_lot(copart())
    assert m.ratio > c.ratio
    assert m.confidence == "wysoka"


def test_copart_mowi_wprost_czego_nie_wie():
    """Broker ma zobaczyć listę braków, a nie samą liczbę."""
    c = coverage_for_lot(copart())
    assert "bieżnik opon" in c.missing
    assert "wcześniejszy lakier" in c.missing


def test_brak_danych_to_nie_brak_uszkodzen():
    """Lot bez wpisów o szkodach nie może udawać auta w idealnym stanie."""
    pusty = coverage_for_lot(
        CarLot(source="copart", lot_id="C2", url="u", year=2020, make="FORD", model="F-150")
    )
    assert pusty.ratio < 0.45
    assert pusty.confidence == "niska"


def test_analiza_copartu_zaznacza_brak_notowania_rynkowego():
    """Copart i IAAI nie podają MMR — bez tego 'tanio' jest opinią, nie faktem."""
    a = analyze(copart())
    assert a.mmr_usd is None
    assert a.value_gap_pct is None
    assert any("notowania rynkowego" in n for n in a.notes)


# ──────────────────────────────────────────────────── ogłoszenia i blokady


def test_lemon_law_blokuje_auto_mimo_grade_5():
    """Realny przypadek ze zbioru: grade 5,0, cło 0%, cena poniżej MMR — i odkup fabryczny.

    AutoGrade nie liczy ogłoszeń, więc grade zostaje piątką. Decyzja zakupowa musi je
    przeczytać, bo to jest tytuł brandowany.
    """
    lot = manheim(
        announcementsEnrichment={"announcements": ["Lemon Law Manuf Buyback"], "remarks": ""}
    )
    a = analyze(lot)
    assert a.grade.grade == 5.0
    assert a.blocked
    assert any("Lemon Law" in b for b in a.blockers)


@pytest.mark.parametrize(
    "ogloszenie",
    [
        "Salvage Title",
        "Flood Damage",
        "Frame Damage",
        "True Mileage Unknown",
        "Bill of Sale Only",
        "Manufacturer Buyback",
    ],
)
def test_ogloszenia_dyskwalifikujace(ogloszenie):
    lot = manheim(announcementsEnrichment={"announcements": [ogloszenie]})
    assert analyze(lot).blocked


def test_prior_paint_ostrzega_ale_nie_blokuje():
    """Lakierowanie obniża wartość, ale nie jest powodem do odrzucenia auta."""
    lot = manheim(announcementsEnrichment={"announcements": ["Green Light / Ride & Drive", "Prior Paint"]})
    a = analyze(lot)
    assert not a.blocked
    assert any("lakierowane" in n for n in a.notes)


def test_ogloszenia_czytamy_takze_z_wolnego_komentarza():
    """Sprzedawcy wpisują to samo raz w ogłoszeniu, raz w komentarzu, a bywa że tylko tam."""
    blokady, _ = announcement_flags(manheim(comments="PPW- PRIOR PAINTWORK. Lemon Law Manuf Buyback"))
    assert any("Lemon Law" in b for b in blokady)


def test_sprzecznosc_flagi_z_opisem_jest_zgloszona():
    """`hasPriorPaint: false` przy komentarzu 'PRIOR PAINTWORK' — jedno z dwóch kłamie."""
    lot = manheim(hasPriorPaint=False, comments="PPW- PRIOR PAINTWORK.")
    assert contradictions(lot)
    assert any("SPRZECZNOŚĆ" in n for n in analyze(lot).notes)


def test_brak_tytulu_blokuje():
    assert analyze(manheim(titleStatus="Title Absent")).blocked


def test_konstrukcja_i_czerwone_swiatlo_blokuja():
    assert analyze(manheim(hasFrameDamage=True)).blocked
    assert analyze(manheim(redLight=True, greenLight=False)).blocked


# ─────────────────────────────────────────────────────────────── ranking


def test_ranking_odrzuca_zablokowane():
    dobry = analyze(manheim())
    zly = analyze(manheim(hasFrameDamage=True))
    assert rank([dobry, zly]) == [dobry]


def test_ranking_premiuje_zerowe_clo_przy_reszcie_rownej():
    z_usa = analyze(manheim())                       # VIN 5... = USA
    lot_de = manheim()
    lot_de.vin = lot_de.full_vin = "WBA43AT01RCR78056"  # Niemcy
    z_niemiec = analyze(lot_de)
    assert z_usa.duty_free and not z_niemiec.duty_free
    assert rank([z_niemiec, z_usa])[0] is z_usa


def test_ranking_premiuje_wieksza_luke_do_rynku():
    tanie = analyze(manheim(mmrPrice=60_000))   # stawka 45k wobec MMR 60k
    drogie = analyze(manheim(mmrPrice=46_000))
    assert rank([drogie, tanie])[0] is tanie


def test_ranking_odcina_ponizej_progu_grade():
    slaby = analyze(manheim(conditionGrade=2.5))
    assert rank([slaby], min_grade=3.5) == []


def test_najlepszy_z_kazdego_zrodla_osobno():
    """Osobno, bo zwycięzca globalny byłby zawsze z Manheimu — z powodu raportu, nie auta."""
    wynik = best_per_source([analyze(manheim()), analyze(copart())])
    assert wynik["manheim"] is not None
    assert wynik["copart"] is not None
    assert wynik["iaai"] is None  # brak lotów z tego źródła


def test_budzet_ucina_za_drogie():
    a = analyze(manheim())
    assert rank([a], budget_pln=100_000) == []
    assert rank([a], budget_pln=10_000_000) == [a]
