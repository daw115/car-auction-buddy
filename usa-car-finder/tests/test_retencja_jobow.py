"""Rejestr jobów nie może rosnąć bez końca.

`load_all_rows()` wczytuje przy starcie WSZYSTKO razem z `result_json`, i to
w dwóch miejscach. Na produkcji po 3,5 miesiąca: 115 jobów, 15,6 MB, czyli
~136 KB na job — i tyle samo w pamięci procesu API.

Dwa okna, bo to dwie różne potrzeby: wynik jest ciężki i przydatny krótko
(po trzech miesiącach aukcje dawno się skończyły), a sam wiersz waży tyle co nic
i niesie historię wyszukiwań.
"""

from datetime import datetime, timedelta, timezone

import pytest

from api import job_db


@pytest.fixture(autouse=True)
def baza(tmp_path):
    """Ścieżkę podajemy WPROST, nie przez zmienną środowiskową.

    Pierwsza wersja ustawiała `JOBS_DB_PATH`, a moduł czyta `JOB_DB_PATH` —
    testy pisały więc do prawdziwej bazy w repo i wywracały się na powtórzonym
    identyfikatorze przy drugim uruchomieniu.
    """
    poprzednia = job_db._db_path
    job_db._initialized = False
    job_db.init_db(tmp_path / "jobs.db")
    yield
    job_db._initialized = False
    if poprzednia:
        job_db.init_db(poprzednia)


def _dodaj(job_id: str, *, dni_temu: int, status: str = "done", wynik: str = '{"all_results": []}'):
    kiedy = (datetime.now(timezone.utc) - timedelta(days=dni_temu)).isoformat()
    with job_db._lock, job_db._connect() as conn:
        conn.execute(
            "INSERT INTO jobs (id, status, created_at, result_json) VALUES (?, ?, ?, ?)",
            (job_id, status, kiedy, wynik),
        )


def _wiersz(job_id: str):
    with job_db._lock, job_db._connect() as conn:
        r = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return dict(r) if r else None


def test_stary_wynik_znika_a_wiersz_zostaje() -> None:
    """Historia wyszukiwań przeżywa, ciężka treść nie."""
    _dodaj("stary", dni_temu=120)
    job_db.zwolnij_miejsce()
    w = _wiersz("stary")
    assert w is not None, "wiersz z historią zniknął za wcześnie"
    assert w["result_json"] is None


def test_swiezy_job_nietkniety() -> None:
    _dodaj("swiezy", dni_temu=5)
    job_db.zwolnij_miejsce()
    assert _wiersz("swiezy")["result_json"] is not None


def test_wiersz_starszy_niz_rok_znika() -> None:
    _dodaj("prehistoryczny", dni_temu=400)
    job_db.zwolnij_miejsce()
    assert _wiersz("prehistoryczny") is None


def test_praca_w_toku_jest_nietykalna() -> None:
    """`running` bez wyniku to robota w biegu, nie śmieć — nawet gdy data
    wygląda staro (zegar systemowy, przywrócona kopia)."""
    _dodaj("w_toku", dni_temu=400, status="running")
    job_db.zwolnij_miejsce()
    assert _wiersz("w_toku") is not None
