"""
Ocena stanu w skali AutoGrade — zgodność z opublikowaną metodyką NAAA/Manheim.

Te testy pilnują trzech rzeczy:

  1. Że grade liczy WYŁĄCZNIE stan. Dokument AutoGrade wymienia wprost, czego w nim
     nie ma: przebiegu, rocznika, marki, wersji, koloru, opcji, MSRP, announcements
     i kosztu naprawy. To nie jest przeoczenie — to sedno pomysłu. Wpuszczenie
     czegokolwiek z tej listy zrobiłoby z grade'u drugą ocenę zakupową i zabiło
     porównywalność z liczbą, którą drukuje aukcja.
  2. Że reguła opon nie liczy jednej szkody dwa razy.
  3. Że lot z Copartu i lot z Manheimu wychodzą na tej samej skali — bo po to
     ten moduł powstał.
"""
import pytest

from parser.models import CarLot
from scoring.autograde import (
    DamageItem,
    Severity,
    Tier,
    grade_for_lot,
    grade_from_items,
    grade_label,
    items_from_damage_text,
    tire_items,
)


def lot(**over) -> CarLot:
    base = dict(source="copart", lot_id="L1", url="u", year=2022, make="BMW", model="X5", keys=True)
    base.update(over)
    return CarLot(**base)


# ────────────────────────────────────────────────────── skala i etykiety


def test_auto_bez_uszkodzen_ma_piatke():
    """„No exterior condition items were reported" to dokładnie ten przypadek."""
    assert grade_from_items([]).grade == 5.0
    assert grade_from_items([]).label == "Extra Clean"


@pytest.mark.parametrize(
    "grade, etykieta",
    [
        (5.0, "Extra Clean"),
        (4.6, "Extra Clean"),
        (4.2, "Clean"),
        (3.4, "Average"),
        (2.4, "Rough"),
        (1.5, "Extra Rough"),
        (0.5, "Salvage"),
    ],
)
def test_etykiety_klas(grade, etykieta):
    assert grade_label(grade) == etykieta


def test_grade_nie_wychodzi_poza_skale():
    ciezkie = [DamageItem(f"szkoda {i}", Tier.MAJOR, Severity.SEVERE) for i in range(20)]
    assert grade_from_items(ciezkie).grade == 0.0


# ─────────────────────────────────── to, czego w grade NIE MA (lista z dokumentu)


@pytest.mark.parametrize(
    "pole, wartosc",
    [
        ("odometer_mi", 250_000),   # przebieg
        ("year", 2005),             # rocznik
        ("make", "KIA"),            # marka
        ("trim", "BASE"),           # wersja
    ],
)
def test_grade_ignoruje_to_co_dokument_wyklucza(pole, wartosc):
    """Auto w tym samym stanie ma ten sam grade, choćby było stare i przejechane.

    Wartość powstaje dopiero z połączenia grade'u z rocznikiem, przebiegiem i MMR —
    tak mówi dokument i tak samo działa u nas `scoring/unified.py`.
    """
    czyste = grade_for_lot(lot(damage_primary="Minor Dent/Scratches")).grade
    zmienione = grade_for_lot(lot(damage_primary="Minor Dent/Scratches", **{pole: wartosc})).grade
    assert czyste == zmienione


# ─────────────────────────────────────────────────────── poziomy redukcji


def test_major_boli_bardziej_niz_moderate_i_minor():
    """Trzy poziomy z dokumentu muszą się układać w kolejności."""
    major = grade_from_items([DamageItem("x", Tier.MAJOR)]).grade
    moderate = grade_from_items([DamageItem("x", Tier.MODERATE)]).grade
    minor = grade_from_items([DamageItem("x", Tier.MINOR)]).grade
    assert major < moderate < minor < 5.0


def test_nasilenie_ma_wplyw_stopniowany():
    """„Damage Size / Severity / Number of Occurrences may have a graduated impact"."""
    lekka = grade_from_items([DamageItem("x", Tier.MODERATE, Severity.LIGHT)]).grade
    ciezka = grade_from_items([DamageItem("x", Tier.MODERATE, Severity.SEVERE)]).grade
    assert ciezka < lekka


def test_kolejne_wystapienia_licza_sie_slabiej():
    """NAAA wpisuje 'parking lot dings' w definicję grade'u 3, nie wraku.

    Bez wygaszania dziesięć rys parkingowych dawało zero i auto średnie wyglądało
    w raporcie gorzej niż auto po czołowym zderzeniu.
    """
    jedna = 5.0 - grade_from_items([DamageItem("rysa", Tier.MINOR, count=1)]).grade
    dziesiec = 5.0 - grade_from_items([DamageItem("rysa", Tier.MINOR, count=10)]).grade
    assert dziesiec < jedna * 10
    assert grade_from_items([DamageItem("rysa", Tier.MINOR, Severity.LIGHT, count=10)]).grade >= 3.0


# ──────────────────────────────────────────────────────────── twarde sufity


def test_uszkodzenie_konstrukcji_zabiera_klase_clean():
    """Nie ma auta 'clean' z uszkodzoną konstrukcją, choćby reszta była bez zarzutu."""
    ocena = grade_from_items([DamageItem("rama", Tier.MAJOR, Severity.LIGHT, structural=True)])
    assert ocena.grade <= 2.0
    assert "konstrukcji" in " ".join(ocena.caps_applied)


def test_zalanie_i_pozar_schodza_najnizej():
    for flaga in ("Water/Flood", "Burn"):
        ocena = grade_for_lot(lot(damage_primary=flaga))
        assert ocena.grade <= 1.0


def test_brak_kluczy_i_niejezdzace_maja_swoje_sufity():
    assert grade_for_lot(lot(damage_primary="Minor Dent/Scratches", keys=False)).grade <= 3.5
    assert grade_for_lot(lot(damage_primary="Mechanical")).grade <= 2.5


# ────────────────────────────────────────── opony: reguła bez podwójnego liczenia


def test_biieznik_powyzej_pasma_nie_wplywa_na_grade():
    """Opony 8/32 i 9/32 są poza pasmem redukcji — tak wygląda auto z grade 5,0.

    UWAGA NA DWIE RÓŻNE SKALE. Manheim koloruje opony zielono od 6/32 w górę, ale
    dokument AutoGrade liczy redukcję Minor już od 7/32 w dół. Zielona opona na
    ekranie może więc mieć wpływ na grade — kolor jest informacją dla oglądającego,
    a pasmo 4–7/32 wchodzi do wyliczenia.
    """
    assert tire_items([9, 9, 8, 8]) == []
    assert tire_items([8, 8, 8, 8]) == []
    # 6/32 jest u Manheima zielone, a mimo to mieści się w paśmie 4-7/32.
    assert len(tire_items([6, 6, 6, 6])) == 1


def test_zuzycie_4_7_32_to_redukcja_minor():
    pozycje = tire_items([5, 5, 4, 4])
    assert len(pozycje) == 1
    assert pozycje[0].tier is Tier.MINOR


def test_ponizej_3_32_to_redukcja_moderate():
    pozycje = tire_items([2, 2, 9, 9])
    assert len(pozycje) == 1
    assert pozycje[0].tier is Tier.MODERATE
    assert pozycje[0].count == 2


def test_wpis_o_wymianie_wylacza_liczenie_biezinika():
    """„Ensuring there is no double dipping for tire replacement" — wprost z dokumentu."""
    assert tire_items([2, 2, 1, 1], replacement_flagged=True) == []


# ──────────────────────────────────── wspólna skala dla Copartu i Manheimu


def test_grade_aukcji_wygrywa_z_nasza_rekonstrukcja():
    """Kupujący widzi liczbę aukcji — nie wolno jej nadpisywać własnym wyliczeniem."""
    ocena = grade_for_lot(
        lot(source="manheim", raw_data={"listing": {"conditionGrade": 4.2}})
    )
    assert ocena.grade == 4.2
    assert ocena.source == "grade aukcji"


def test_rozjazd_wobec_grade_aukcji_jest_odnotowany():
    """Aukcja mówi 5.0, a raport stanu pokazuje czołowe zderzenie — broker ma to zobaczyć."""
    ocena = grade_for_lot(
        lot(
            source="manheim",
            damage_primary="Front End",
            damage_secondary="Undercarriage",
            raw_data={"listing": {"conditionGrade": 5.0}},
        )
    )
    assert ocena.grade == 5.0
    assert any("ROZJAZD" in n for n in ocena.notes)


def test_lot_z_copartu_dostaje_grade_w_tej_samej_skali():
    """Sedno modułu: bez tego nie da się porównać lota z Copartu z lotem z Manheimu."""
    z_copartu = grade_for_lot(lot(source="copart", damage_primary="Minor Dent/Scratches"))
    z_manheimu = grade_for_lot(
        lot(source="manheim", raw_data={"listing": {"conditionGrade": 4.9}})
    )
    assert 0.0 <= z_copartu.grade <= 5.0
    assert abs(z_copartu.grade - z_manheimu.grade) < 0.5


def test_ten_sam_opis_w_obu_polach_liczy_sie_raz():
    """Copart podaje primary i secondary; to samo hasło w obu to jedna szkoda."""
    jedno = items_from_damage_text("Front End")
    dwa = items_from_damage_text("Front End", "Front End")
    assert len(jedno) == len(dwa) == 1


def test_dwie_rozne_szkody_licza_sie_osobno():
    assert len(items_from_damage_text("Front End", "Rear End")) == 2


# ──────────────────────────────────────────── wpięcie w ocenę zakupową


def test_scoring_uzywa_autograde_i_pokazuje_go_w_uzasadnieniu():
    from parser.models import ClientCriteria
    from scoring.unified import ClientProfile, score_lot

    wynik = score_lot(
        lot(damage_primary="Minor Dent/Scratches", current_bid_usd=20_000, location_state="FL"),
        ClientCriteria(make="BMW"),
        ClientProfile(),
    )
    stan = next(c for c in wynik.components if c.key == "condition")
    assert "AutoGrade" in stan.detail


def test_brak_danych_o_stanie_nie_kara_lota():
    """Brak raportu to nie to samo co raport bez uwag — waga idzie na resztę składowych."""
    from parser.models import ClientCriteria
    from scoring.unified import ClientProfile, score_lot

    wynik = score_lot(
        lot(damage_primary=None, current_bid_usd=20_000, location_state="FL"),
        ClientCriteria(make="BMW"),
        ClientProfile(),
    )
    assert all(c.key != "condition" for c in wynik.components)


# ─────────────────────────────────── kalibracja na realnych danych aukcyjnych


def test_brak_raportu_stanu_nie_daje_piatki():
    """Zmierzone na 280 lotach z Manheimu: brak sygnału uszkodzenia to NIE auto idealne.

    Ich prawdziwy grade wyniósł średnio 4,58, a 37% nie było „Extra Clean". Startowanie
    od 5,0 zawyżało ocenę systematycznie o 0,42 punktu — czyli obiecywało klientowi
    stan, którego auto nie miało. Szczegóły w `scoring/calibration.py`.
    """
    from scoring import calibration as cal

    z_raportem = grade_from_items([], condition_report=True)
    bez_raportu = grade_from_items([], condition_report=False)

    assert z_raportem.grade == 5.0
    assert bez_raportu.grade == cal.NO_REPORT_PRIOR
    assert bez_raportu.grade < z_raportem.grade


def test_ocena_bez_raportu_niesie_pasmo_niepewnosci():
    """Broker ma zobaczyć, że to szacunek, a nie odczyt."""
    ocena = grade_from_items([], condition_report=False)
    assert ocena.band is not None
    assert not ocena.certain
    dol, gora = ocena.band
    assert dol < gora <= ocena.grade
    assert "szacunek" in ocena.summary()


def test_pasmo_przesuwa_sie_razem_z_odjetymi_punktami():
    """Auto z opisaną szkodą ma pasmo niżej, a nie to samo co auto bez opisu."""
    czyste = grade_from_items([], condition_report=False)
    ze_szkoda = grade_from_items(
        [DamageItem("przód", Tier.MODERATE)], condition_report=False
    )
    assert ze_szkoda.band[0] < czyste.band[0]
    assert ze_szkoda.band[1] < czyste.band[1]


def test_pasmo_nie_jest_odwrocone():
    """Zmienna pętli `sufit` przesłaniała punkt startowy i pasmo wychodziło 5,1-4,6."""
    for pozycje in ([], [DamageItem("x", Tier.MINOR)], [DamageItem("y", Tier.MAJOR, structural=True)]):
        ocena = grade_from_items(pozycje, condition_report=False)
        assert ocena.band[0] <= ocena.band[1], f"odwrócone pasmo: {ocena.band}"


def test_copart_nigdy_nie_ma_raportu_stanu_a_manheim_ma():
    """Copart i IAAI nie robią pozycjowanych raportów — dają dwa pola opisu szkody."""
    from scoring.autograde import has_condition_report

    assert not has_condition_report(lot(source="copart", damage_primary="Front End"))
    assert has_condition_report(
        lot(source="manheim", raw_data={"listing": {"conditionReportUrl": "http://x"}})
    )


def test_ten_sam_opis_szkody_daje_nizsza_ocene_bez_raportu():
    """Sedno kalibracji: identyczna szkoda, inna wiedza o reszcie auta."""
    z_raportem = grade_from_items(
        items_from_damage_text("Front End"), condition_report=True
    ).grade
    bez_raportu = grade_from_items(
        items_from_damage_text("Front End"), condition_report=False
    ).grade
    assert bez_raportu < z_raportem


def test_kalibracja_niesie_metryczke_probki():
    """Stała bez metryczki starzeje się po cichu."""
    from scoring import calibration as cal

    assert cal.SAMPLE_SIZE == 307
    assert cal.SAMPLE_DATE
    assert "Manheim" in cal.SAMPLE_SOURCE
    assert "307" in cal.summary()
