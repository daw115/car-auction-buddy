"""Wspólne ustawienia dla całej suity.

KURS DOLARA JEST PRZYBITY. Odkąd `pricing/fx.py` bierze kurs z NBP, wycena zmienia się
codziennie razem z tabelą. Bez przybicia każdy test porównujący kwotę do wpisanej liczby
byłby testem kursu walutowego, a nie logiki — zielony w poniedziałek, czerwony we wtorek,
i czerwony bez internetu.

Wartość 4,00 nie jest przypadkowa: to kurs, który do sierpnia 2026 był wpisany na sztywno
w kalkulatorze, więc wszystkie kwoty oczekiwane w istniejących testach zostają ważne.
Różnice, które te testy pokazują po zmianie, biorą się wtedy wyłącznie ze stawek cła
i akcyzy — czyli z tego, co faktycznie zmienialiśmy.

Testów samego `fx.py` to nie dotyczy: one czyszczą tę zmienną same, bo sprawdzają
właśnie zachowanie wobec NBP.
"""
import os

import pytest

PINNED_USD_RATE = "4.0"


@pytest.fixture(autouse=True)
def _pin_usd_rate(monkeypatch):
    monkeypatch.setenv("FX_RATE_OVERRIDE", PINNED_USD_RATE)
    # Agent sprzedażowy nie woła modelu w testach. Wywołanie chodzi po sieci, wymaga
    # zalogowanej sesji i kosztuje — a testujemy tu regułę i walidator, nie model.
    monkeypatch.setenv("SALES_AGENT_MODEL_ENABLED", "false")
    # To samo dotyczy parsera zgłoszeń: bez wyłącznika każdy test przyjmujący lead
    # czeka na ponawiane wywołania sieciowe. Suita rosła przez to z sekund do minut.
    monkeypatch.setenv("SALES_PARSER_ENABLED", "false")
    yield


@pytest.fixture(autouse=True)
def _isolated_sales_db(tmp_path):
    """Baza agenta sprzedażowego w katalogu tymczasowym — dla KAŻDEGO testu.

    Nie przez `APP_DATABASE_PATH`: kilka modułów scrapera woła `load_dotenv(override=True)`
    przy imporcie, a importują się leniwie w trakcie obsługi żądania, więc zmienna wraca
    w połowie testu do wartości z `.env`. Testy zaczynały wtedy dopisywać leady do
    produkcyjnej bazy aplikacji i nic tego nie zgłaszało.
    """
    from sales import db

    db.use_database(tmp_path / "sales.db")
    yield
    db.use_database(None)
