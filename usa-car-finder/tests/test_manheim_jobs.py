"""Kolejka zleceń wyszukiwania dla rozszerzenia manheim-collector."""
import asyncio

import pytest

from api import manheim_jobs
from parser.models import ClientCriteria
from scraper import manheim as manheim_scraper


@pytest.fixture(autouse=True)
def _clean_queue():
    manheim_jobs.clear()
    yield
    manheim_jobs.clear()


def test_job_is_handed_out_once_and_then_completed():
    job_id = manheim_jobs.create("toyota rav4")

    taken = manheim_jobs.next_pending()
    # Do zlecenia dołączane są szablony żądań — świeżo otwarta karta swoich
    # jeszcze nie ma, a bez nich nie powtórzy zapytania.
    assert taken == {"id": job_id, "keyword": "toyota rav4", "templates": {}}
    # Drugi odbiorca nie dostaje tego samego zadania.
    assert manheim_jobs.next_pending() is None

    assert manheim_jobs.complete(job_id, [{"vin": "X"}]) is True
    job = manheim_jobs.get(job_id)
    assert job["status"] == "done" and job["records"] == [{"vin": "X"}]


def test_abandoned_job_returns_to_the_queue(monkeypatch):
    """Service worker MV3 bywa usypiany w trakcie — zadanie nie może przepaść."""
    monkeypatch.setenv("MANHEIM_JOB_LEASE_SECONDS", "10")
    job_id = manheim_jobs.create("bmw x5")
    assert manheim_jobs.next_pending()["id"] == job_id
    assert manheim_jobs.next_pending() is None

    real_time = manheim_jobs.time.time
    monkeypatch.setattr(manheim_jobs.time, "time", lambda: real_time() + 30)
    assert manheim_jobs.next_pending()["id"] == job_id


def test_completing_an_unknown_job_is_not_an_error():
    assert manheim_jobs.complete("nie-ma-takiego", []) is False


def test_error_from_the_extension_is_preserved():
    job_id = manheim_jobs.create("bmw x5")
    manheim_jobs.complete(job_id, [], error="Brak otwartej karty Manheima")
    job = manheim_jobs.get(job_id)
    assert job["status"] == "error"
    assert "Brak otwartej karty" in job["error"]


def test_scraper_uses_records_delivered_for_its_job(monkeypatch, tmp_path):
    """Ścieżka docelowa: źródło zleca hasło i dostaje wynik zlecenia."""
    monkeypatch.setenv("MANHEIM_SOURCE_MODE", "collector")
    monkeypatch.setenv("MANHEIM_JOB_TIMEOUT_SECONDS", "5")
    monkeypatch.setenv("HTML_CACHE_DIR", str(tmp_path))
    monkeypatch.delenv("MANHEIM_MAX_RESULTS", raising=False)
    # Magazyn ogólny pusty — wynik ma pochodzić WYŁĄCZNIE ze zlecenia.
    monkeypatch.setattr(
        manheim_scraper.ManheimScraper, "_collector_records", staticmethod(list)
    )

    delivered = [
        {
            "vin": f"JTMRWRFV9PD20481{i}",
            "unifiedId": f"OVE.FAAO.45399{i}",
            "sourceYear": "2023",
            "sourceMake": "Toyota",
            "sourceModel": "RAV4",
            "odometer": 20_000 + i,
            "conditionGrade": "5",
            "pickupLocation": "GA - Manheim Atlanta",
        }
        for i in range(5)
    ]

    async def scenario():
        task = asyncio.ensure_future(
            manheim_scraper.ManheimScraper().scrape(
                ClientCriteria(make="Toyota", model="RAV4", sources=["manheim"])
            )
        )
        # Udajemy rozszerzenie: odbieramy zadanie i odsyłamy wynik.
        for _ in range(20):
            job = manheim_jobs.next_pending()
            if job:
                # normalize_model_for_query mapuje RAV4 -> rav4 (wspólna
                # tablica aliasów z Copart/IAAI); Manheim i tak szuka bez
                # rozróżniania wielkości liter.
                assert job["keyword"].lower() == "toyota rav4"
                manheim_jobs.complete(job["id"], delivered)
                break
            await asyncio.sleep(0.1)
        return await task

    saved = asyncio.run(scenario())
    assert len(saved) == 3


def test_scraper_falls_back_to_the_store_when_nobody_takes_the_job(monkeypatch, tmp_path):
    monkeypatch.setenv("MANHEIM_SOURCE_MODE", "collector")
    monkeypatch.setenv("MANHEIM_JOB_TIMEOUT_SECONDS", "1")
    monkeypatch.setenv("HTML_CACHE_DIR", str(tmp_path))
    stored = [
        {
            "vin": "5UXCR6C05L9C12345",
            "unifiedId": "OVE.FAAO.111111",
            "sourceYear": "2020",
            "sourceMake": "BMW",
            "sourceModel": "X5",
            "odometer": 42_110,
        }
    ]
    monkeypatch.setattr(
        manheim_scraper.ManheimScraper, "_collector_records", staticmethod(lambda: stored)
    )

    saved = asyncio.run(
        manheim_scraper.ManheimScraper().scrape(
            ClientCriteria(make="BMW", model="X5", sources=["manheim"])
        )
    )
    assert len(saved) == 1


def test_templates_survive_and_ride_along_with_the_job():
    """Szablon żyje na backendzie, nie w przeglądarce.

    chrome.storage ginie przy restarcie przeglądarki (i przy skasowaniu
    profilu), a bez szablonu kolektor nie powtórzy zapytania — więc trwałym
    miejscem jest backend, a szablon jedzie do karty razem ze zleceniem.
    """
    template = {
        "url": "https://onesearch-api.manheim.com/graphql",
        "method": "POST",
        "headers": {"Authorization": "Bearer x"},
        "body": {"operationName": "getSearches", "variables": {"payload": "{}"}},
    }
    assert manheim_jobs.store_templates({"getSearches": template}) == 1
    # Śmieci bez url-a nie wchodzą.
    assert manheim_jobs.store_templates({"getExecuteSearchId": {"brak": "url"}}) == 1

    job_id = manheim_jobs.create("bmw x5")
    taken = manheim_jobs.next_pending()
    assert taken["templates"]["getSearches"]["url"].endswith("/graphql")
