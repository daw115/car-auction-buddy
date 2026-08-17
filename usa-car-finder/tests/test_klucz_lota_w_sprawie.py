"""Identyfikator auta w obrębie sprawy.

`lot_id` wygląda na gotowy klucz i nim nie jest: Manheim go nie podaje. Przy
takim aucie panel numerował pozycją, backend zapisywał napis „None" i wybór
klienta trafiał w próżnię — auto wracało jako „spoza oferty", mimo że sami je
wysłaliśmy. Testy pilnują, żeby klucz był zawsze i żeby obie strony liczyły go
tak samo.
"""

from sales.pipeline import klucz_lota, klucz_wpisu, _opis_lota


def test_numer_lota_wygrywa_gdy_jest() -> None:
    assert klucz_lota({"lot_id": "12345", "vin": "WBA123"}, 0) == "12345"


def test_vin_gdy_aukcja_nie_podaje_numeru_lota() -> None:
    """Tak wyglądają loty z Manheimu — VIN jest wtedy jedynym trwałym śladem."""
    assert klucz_lota({"lot_id": None, "vin": "WBA123", "source": "manheim"}, 0) == "WBA123"


def test_pozycja_gdy_nie_ma_ani_numeru_ani_vin() -> None:
    assert klucz_lota({"source": "manheim"}, 1) == "manheim-2"
    assert klucz_lota({}, 0) == "lot-1"


def test_klucz_nigdy_nie_jest_pusty_ani_none() -> None:
    """Napis „None" jako klucz to dokładnie ten błąd, który to naprawia."""
    for lot in ({}, {"lot_id": None}, {"lot_id": "", "vin": ""}):
        klucz = klucz_lota(lot, 0)
        assert klucz and klucz != "None"


def test_opis_lota_niesie_klucz_dla_panelu() -> None:
    opis = _opis_lota({"lot_id": None, "vin": "WBA9", "year": 2021, "make": "BMW"}, 2)
    assert opis["klucz"] == "WBA9"
    # Surowego `lot_id` nie podmieniamy — pole ma znaczyć to, co znaczy.
    assert opis["lot_id"] is None


def test_sprawy_sprzed_zmiany_daja_sie_odczytac() -> None:
    """Wiersze zapisane wcześniej nie mają pola `klucz` i muszą działać dalej."""
    assert klucz_wpisu({"lot_id": "999"}, 0) == "999"
    assert klucz_wpisu({}, 3) == "lot-4"
