"""Kształty żądania, które realnie przychodzą do /report/*.

Panel kandydatów trzyma auta w postaci z `sales/search._candidates_from_result`
(`{lot, score, recommendation, ...}`), a nie jako `AnalyzedLot`, i wysyłał je
wprost. Endpoint odpowiadał 422, więc przycisk „wyślij ofertę" nie działał ani
razu — a testy tego nie łapały, bo sprawdzały renderowanie, nie drogę przez API.
"""

import pytest
from pydantic import ValidationError

from api.main import ApproveReportRequest

LOT = {
    "source": "manheim",
    "lot_id": "555",
    "url": "https://example.test/555",
    "year": 2021,
    "make": "Volvo",
    "model": "XC60",
}


def test_surowy_lot_z_panelu_przechodzi() -> None:
    """Dokładnie to, co wysyłał panel: lot plus znacznik raportu."""
    zadanie = ApproveReportRequest(approved_lots=[{**LOT, "included_in_report": True}])
    assert zadanie.approved_lots[0].lot.lot_id == "555"
    assert zadanie.approved_lots[0].included_in_report


def test_kandydat_zachowuje_ocene() -> None:
    """Ocena nie jest zmyślana ani gubiona — brief brokera ma pokazać wynik."""
    zadanie = ApproveReportRequest(
        approved_lots=[
            {
                "lot": LOT,
                "score": 8.2,
                "recommendation": "POLECAM",
                "reasoning": "czysty tytuł, niski przebieg",
                "is_top": True,
            }
        ]
    )
    analiza = zadanie.approved_lots[0].analysis
    assert analiza.score == 8.2
    assert analiza.recommendation == "POLECAM"
    assert zadanie.approved_lots[0].is_top_recommendation


def test_lot_bez_oceny_dostaje_zero_a_nie_wymyslona_liczbe() -> None:
    zadanie = ApproveReportRequest(approved_lots=[dict(LOT)])
    assert zadanie.approved_lots[0].analysis.score == 0.0
    assert zadanie.approved_lots[0].analysis.recommendation == ""


def test_pelny_analyzed_lot_dziala_jak_dotad() -> None:
    """Stara droga (wyniki wyszukiwania z panelu głównego) nie może się zmienić."""
    zadanie = ApproveReportRequest(
        approved_lots=[
            {
                "lot": LOT,
                "analysis": {
                    "lot_id": "555",
                    "score": 6.8,
                    "recommendation": "RYZYKO",
                    "client_description_pl": "opis",
                },
            }
        ]
    )
    assert zadanie.approved_lots[0].analysis.score == 6.8


def test_smiec_nadal_odpada() -> None:
    """Tolerancja na kształt nie znaczy tolerancji na brak danych."""
    with pytest.raises(ValidationError):
        ApproveReportRequest(approved_lots=[{"nic": "tu nie ma"}])
