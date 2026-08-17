"""Wiadomość, która idzie razem z obrazkiem oferty.

Nagłówek zszedł z obrazka do treści wiadomości: powitanie i prośba o odpowiedź
to rozmowa, nie dokument. Testy pilnują, żeby ta wiadomość niosła wszystko, bez
czego obrazek jest niezrozumiały — kto pisze, czego dotyczy, że cena jest pod
drzwi i co klient ma zrobić.
"""

import pytest

from report.whatsapp import tekst_do_oferty


def test_mowi_ze_ceny_sa_pod_drzwi() -> None:
    """Bez tego zdania kwota z obrazka wygląda na cenę aukcyjną, do której coś dojdzie."""
    assert "pod drzwi w Polsce" in tekst_do_oferty(3, client_name="Jan Kowalski")


def test_prosi_o_numer_gdy_aut_jest_kilka() -> None:
    tekst = tekst_do_oferty(3, client_name="Jan Kowalski")
    assert "samym numerem" in tekst
    assert "Wybrałem 3 auta" in tekst


def test_przy_jednym_aucie_nie_prosi_o_numer() -> None:
    """Numer bez wyboru brzmi jak wysłane z szablonu."""
    tekst = tekst_do_oferty(1, client_name="Jan Kowalski")
    assert "numerem" not in tekst
    assert "Znalazłem auto" in tekst


@pytest.mark.parametrize("ile,fragment", [(2, "2 auta"), (4, "4 auta"), (5, "5 aut")])
def test_liczebnik_zgadza_sie_z_liczba(ile: int, fragment: str) -> None:
    """„5 auta" to pierwszy sygnał, że tekst składa maszyna."""
    assert fragment in tekst_do_oferty(ile)


def test_zwraca_sie_po_imieniu_gdy_je_znamy() -> None:
    assert tekst_do_oferty(3, client_name="Jan Kowalski").startswith("Dzień dobry, Jan.")
    assert tekst_do_oferty(3).startswith("Dzień dobry.")


def test_miesci_sie_w_podpisie_telegrama() -> None:
    """Podpis zdjęcia ma limit 1024 znaków — dłuższy zostałby ucięty w połowie zdania."""
    assert len(tekst_do_oferty(4, client_name="Jan Kowalski")) < 1024
