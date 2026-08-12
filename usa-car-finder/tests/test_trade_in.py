"""Auto w rozliczeniu — dla wielu klientów TO JEST budżet."""
from sales.intake import _detect_engine_hint, _detect_trade_in

ROZMOWA = (
    "Mam teraz tą Octavię w RS-ie z 17 roku po lifcie i chciałbym ją pogonić, "
    "sobie dołożyć i wtedy kupić BMW. Chodzą między 65 a 70 tysięcy w Polsce. "
    "Interesuje mnie ta dwulitrówka, te 248 koni."
)


def test_trade_in_is_read_from_natural_speech():
    """Z prawdziwej rozmowy telefonicznej, nie z formularza."""
    model, rocznik, wartosc = _detect_trade_in(ROZMOWA)

    assert model == "Octavia"
    assert rocznik == 2017, "'z 17 roku' to rocznik, nie liczba"
    assert wartosc == 65_000, "z widełek bierzemy dolną — wycena właściciela bywa optymistyczna"


def test_car_the_client_is_looking_for_is_not_a_trade_in():
    """Najgroźniejszy fałszywy trop: wzięcie szukanego auta za rozliczane."""
    assert _detect_trade_in("Szukam BMW G30 z 2018 roku, budżet 90 tysięcy") == (None, None, None)


def test_polish_declension_does_not_hide_the_car():
    """„Octavię", „Golfa", „Passatem" — pełne nazwy nie wystarczą."""
    assert _detect_trade_in("Sprzedaję Golfa")[0] == "Golf"
    assert _detect_trade_in("Mam Passata")[0] == "Passat"


def test_engine_hint_catches_the_spoken_form():
    """Przy 2.0 akcyza to 3,1% zamiast 18,6% — to bywa warunek, nie preferencja."""
    assert _detect_engine_hint(ROZMOWA) == "2.0"
    assert _detect_engine_hint("chciałbym 3.0") == "3.0"
    assert _detect_engine_hint("Szukam BMW") is None
