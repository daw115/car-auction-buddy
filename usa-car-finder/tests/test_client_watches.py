"""Nasłuch aukcji pod klienta — trwałość, różnica i granica wysyłki."""
import time

import pytest

from parser.models import CarLot
from watch import db as watch_db

KRYTERIA = {"make": "Mazda", "model": "6", "year_from": 2018, "year_to": 2021}


@pytest.fixture(autouse=True)
def baza(tmp_path):
    """Baza przypięta na sztywno, nie przez zmienną środowiskową.

    APP_DATABASE_PATH nie wystarcza: moduły scrapera wołają
    `load_dotenv(override=True)` i w połowie testu przywracają wartość z .env —
    test zaczyna wtedy pisać do produkcyjnej bazy i nikt tego nie zauważa.
    """
    watch_db.use_database(tmp_path / "app.db")
    watch_db.init_db()
    yield
    watch_db.use_database(None)


def lot(lot_id="1", source="copart", score=8.0):
    return CarLot(
        source=source, lot_id=lot_id, url=f"https://x/{lot_id}", year=2019,
        make="Mazda", model="6", raw_data={"unified_score": {"score": score}},
    )


def test_watch_survives_and_reports_when_it_is_due():
    watch = watch_db.create(KRYTERIA, client_name="Wojciech", interval_hours=12)

    assert watch.is_due(), "świeży nasłuch ma pójść od razu, bez czekania cyklu"

    watch_db.record_run(watch.id, found=2)
    odczytany = watch_db.get(watch.id)

    assert odczytany.runs == 1 and odczytany.found_total == 2
    assert not odczytany.is_due(), "zaraz po przebiegu nasłuch nie jest wymagalny"
    assert odczytany.is_due(time.time() + 13 * 3600), "po odstępie znowu tak"


def test_broker_is_not_shown_the_same_car_twice():
    """Bez tego po trzech dobach broker dostaje co rano tę samą liste i przestaje ją czytać."""
    watch = watch_db.create(KRYTERIA)
    pierwsze = [lot("A"), lot("B")]

    assert len(watch_db.filter_unseen(watch.id, pierwsze)) == 2
    watch_db.mark_seen(watch.id, pierwsze)

    drugie = [lot("A"), lot("B"), lot("C")]
    nowe = watch_db.filter_unseen(watch.id, drugie)

    assert [l.lot_id for l in nowe] == ["C"]


def test_lot_identity_needs_the_exchange_not_just_the_number():
    """Numer lota jest unikalny dopiero w parze z giełdą."""
    watch = watch_db.create(KRYTERIA)
    watch_db.mark_seen(watch.id, [lot("777", source="copart")])

    nowe = watch_db.filter_unseen(watch.id, [lot("777", source="iaai")])

    assert len(nowe) == 1, "ten sam numer na innej giełdzie to inne auto"


def test_paused_watch_is_never_due():
    watch = watch_db.create(KRYTERIA)
    watch_db.set_active(watch.id, False)

    assert not watch_db.get(watch.id).is_due()
    assert watch_db.due() == []


def test_interval_has_a_floor():
    """Aukcje nie odświeżają się w minutach, a każdy przebieg to realny scrape."""
    watch = watch_db.create(KRYTERIA, interval_hours=0.01)
    assert watch.interval_hours == 1.0


def test_runner_notifies_the_broker_and_never_the_client(monkeypatch):
    """Granica całego systemu: nasłuch przygotowuje materiał, wysyła człowiek."""
    import asyncio

    from watch import runner

    watch = watch_db.create(KRYTERIA, client_name="Wojciech", client_phone="605083832")
    znalezione = [lot("A", score=8.5), lot("B", score=2.0)]

    class FakeScraper:
        async def search_cars(self, criteria, **kwargs):
            return znalezione

    monkeypatch.setattr("scraper.automated_scraper.AutomatedScraper", lambda: FakeScraper())
    monkeypatch.setattr("ai.analyzer._attach_unified_scores", lambda lots, criteria: None)

    wyslane = []
    monkeypatch.setattr(runner, "_telegram_chat_id", lambda: 42)
    monkeypatch.setattr(
        "notify.telegram.is_configured", lambda: True
    )
    monkeypatch.setattr(
        "notify.telegram.send_message",
        lambda chat_id, text, **kw: wyslane.append((chat_id, text)) or {},
    )

    wynik = asyncio.run(runner.run_watch(watch))

    assert wynik.checked == 2
    assert wynik.fresh == 1, "lot poniżej progu jakości nie budzi brokera"
    assert wynik.notified
    assert wyslane[0][0] == 42, "notka idzie na czat brokera"
    # Numer klienta nie może się pojawić jako adresat — to notka wewnętrzna.
    assert "605083832" not in wyslane[0][1]

    # Drugi przebieg na tych samych danych: nic nowego, brak powiadomienia.
    powtorka = asyncio.run(runner.run_watch(watch_db.get(watch.id)))
    assert powtorka.fresh == 0 and not powtorka.notified
