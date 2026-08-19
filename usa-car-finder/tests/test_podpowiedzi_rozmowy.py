"""Podpowiedzi do rozmowy z nowym klientem.

`missing` mówi CZEGO nie wiemy („budżet pod drzwi w złotówkach"), a broker
w rozmowie potrzebuje ZDANIA. Musiał je układać sam, przy telefonie, na gorąco —
a pytanie o zgodę na auto po szkodzie jest najtrudniejsze i najbardziej kosztowne
w całej tej sprzedaży: odmowa klienta to najczęstsza przyczyna utraty leada.

Testy pilnują trzech rzeczy naraz: kompletu (każdy brak ma zdanie), zgodności
z produktem (nie obiecujemy naprawy) i polszczyzny, o którą prosił właściciel.
"""

import pytest

from sales.models import Lead
from sales.podpowiedzi import PODPOWIEDZI, dla_brakow
from sales.qualification import _ETYKIETY_BRAKOW, _klucze_brakow, score_lead


def test_kazdy_brak_ma_gotowe_zdanie() -> None:
    """Brak bez podpowiedzi to pole, które broker znów musi ubrać w słowa sam."""
    assert set(_ETYKIETY_BRAKOW) == set(PODPOWIEDZI), (
        "braki i podpowiedzi rozjechały się — to ten sam mechanizm, który wcześniej "
        "rozjechał dwie tabele tłumaczeń uszkodzeń"
    )


def test_nowy_klient_dostaje_komplet_pytan() -> None:
    lead = Lead(name="Nowy", raw_request="Szukam auta z USA")
    ocena = score_lead(lead)
    assert len(ocena.podpowiedzi) == len(ocena.missing) > 0


def test_szkoda_idzie_pierwsza() -> None:
    """Rozmowa telefoniczna ma ograniczoną uwagę, więc najpierw to pytanie,
    które może ją zakończyć."""
    lead = Lead(name="Nowy", raw_request="cokolwiek")
    assert score_lead(lead).podpowiedzi[0]["klucz"] == "damage_ok"


@pytest.mark.parametrize("klucz", sorted(PODPOWIEDZI))
def test_zdania_nie_obiecuja_naprawy(klucz: str) -> None:
    """Auto przyjeżdża w stanie z aukcji, a naprawę możemy najwyżej wstępnie
    wycenić. Podpowiedź obiecująca więcej każe brokerowi obiecać to samo."""
    p = PODPOWIEDZI[klucz]
    for tekst in (p.przez_telefon, p.na_pismie):
        nizsze = tekst.lower()
        assert "naprawimy" not in nizsze
        assert "naprawiamy" not in nizsze
        assert "w cenie naprawa" not in nizsze


@pytest.mark.parametrize("klucz", sorted(PODPOWIEDZI))
def test_bez_dlugich_myslnikow(klucz: str) -> None:
    """Właściciel prosił o to wprost: „nie używaj długich myślników"."""
    p = PODPOWIEDZI[klucz]
    assert "—" not in p.przez_telefon
    assert "—" not in p.na_pismie


@pytest.mark.parametrize("klucz", sorted(PODPOWIEDZI))
def test_wersja_pisemna_jest_krotsza(klucz: str) -> None:
    """Długi tekst na WhatsAppie zostaje bez odpowiedzi."""
    p = PODPOWIEDZI[klucz]
    assert len(p.na_pismie) < len(p.przez_telefon)
    assert len(p.na_pismie) <= 220, "za długie jak na wiadomość"


def test_znane_dane_nie_generuja_pytan() -> None:
    """Podpowiedź o coś, co już wiemy, kazałaby brokerowi pytać dwa razy."""
    lead = Lead(
        name="Znany", raw_request="BMW X5", phone="600100200", make="BMW",
        year_from=2020, budget_pln=250_000, damage_ok=True, timeline_days=60,
    )
    assert _klucze_brakow(lead) == []
    assert dla_brakow([]) == []
