"""Odczytanie numeru z odpowiedzi klienta na ofertę.

Parser jest podpowiedzią dla brokera, więc łapie szeroko. Testy pilnują dwóch
rzeczy naraz: żeby zwykłe formy odpowiedzi trafiały (bo przeoczony wybór znaczy,
że klient czeka), i żeby liczby z opisu auta nie udawały wyboru (bo raport o
cudzym aucie to gorszy błąd niż brak podpowiedzi).
"""

import pytest

from sales.odpowiedz import numery_z_odpowiedzi


@pytest.mark.parametrize(
    "tekst,oczekiwane",
    [
        ("2", [2]),
        ("Dwójka.", []),  # liczebnik główny, nie porządkowy — świadomie pomijamy
        ("to drugie", [2]),
        ("Drugie proszę", [2]),
        ("interesuje mnie nr 3", [3]),
        ("1 i 3", [1, 3]),
        ("3 i 1", [3, 1]),  # kolejność klienta, nie nasza
        ("pierwsze albo trzecie", [1, 3]),
        ("to drugie, nie 1", [2, 1]),
    ],
)
def test_rozpoznaje_typowe_odpowiedzi(tekst: str, oczekiwane: list[int]) -> None:
    assert numery_z_odpowiedzi(tekst, ile=3) == oczekiwane


@pytest.mark.parametrize(
    "tekst",
    [
        "2021 Volvo mi się podoba",  # rocznik
        "56 097 zł to za dużo",  # cena; „56" i „097" poza zakresem, „097" z zerem wiodącym
        "mam 2 tysiace wiecej",  # jednostka po liczbie
        "za 3 dni dam znać",
        "wolę coś do 100 tys km",
    ],
)
def test_nie_bierze_liczb_z_opisu_za_wybor(tekst: str) -> None:
    assert numery_z_odpowiedzi(tekst, ile=3) == []


def test_zakres_ogranicza_liczba_aut_w_ofercie() -> None:
    """Trójka jest wyborem przy trzech autach, a przypadkową liczbą przy jednym."""
    assert numery_z_odpowiedzi("3", ile=3) == [3]
    assert numery_z_odpowiedzi("3", ile=1) == []


def test_powtorzenia_nie_dublują_pozycji() -> None:
    assert numery_z_odpowiedzi("2, drugie, to dwa razy 2", ile=3) == [2]


def test_pusta_odpowiedz_nie_wskazuje_niczego() -> None:
    assert numery_z_odpowiedzi("", ile=3) == []
    assert numery_z_odpowiedzi("ok", ile=3) == []
