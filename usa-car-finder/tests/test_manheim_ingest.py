"""Magazyn próbek z rozszerzenia manheim-collector."""
import json

import pytest

from api import manheim_ingest

# Kształt wzięty z realnego przechwytu onesearch-api.manheim.com/graphql:
# SPA rozbija pojazd na osobne zapytania, a kwoty owija w obiekt.
BID_STATUS = {
    "__typename": "Listing",
    "vin": "2C4RC1EG4JR177880",
    "id": "454022371",
    "highBid": {"amount": 14250, "currency": "USD"},
    "endTime": "2026-08-12T18:00:00Z",
    "bidCount": 7,
}
VEHICLE = {
    "vin": "2C4RC1EG4JR177880",
    "year": 2018,
    "make": "Chrysler",
    "model": "Pacifica",
    "odometer": 61234,
}


def _capture(payload: object) -> dict:
    return {
        "kind": "fetch",
        "url": "https://onesearch-api.manheim.com/graphql",
        "method": "POST",
        "responseBody": json.dumps(payload),
        "pageUrl": "https://home.manheim.com/landingPage",
    }


@pytest.fixture(autouse=True)
def _clean_store(monkeypatch, tmp_path):
    monkeypatch.setenv("MANHEIM_INGEST_DIR", str(tmp_path / "ingest"))
    monkeypatch.setenv("MANHEIM_INGEST_KEEP_RAW", "0")
    manheim_ingest.clear()
    yield
    manheim_ingest.clear()


def test_split_records_are_merged_into_one_vehicle():
    summary = manheim_ingest.store(
        [_capture({"data": {"search": {"results": [BID_STATUS, VEHICLE]}}})]
    )

    assert summary["vehicles"] == 2  # dwa rozpoznane rekordy...
    assert summary["stored"] == 1  # ...ale jeden pojazd

    stored = manheim_ingest.vehicles()
    assert len(stored) == 1
    assert stored[0]["year"] == 2018
    assert stored[0]["bidCount"] == 7


def test_repeated_ingest_updates_instead_of_duplicating():
    manheim_ingest.store([_capture({"results": [VEHICLE]})])
    manheim_ingest.store([_capture({"results": [BID_STATUS]})])

    stored = manheim_ingest.vehicles()
    assert len(stored) == 1
    assert stored[0]["make"] == "Chrysler"
    assert stored[0]["endTime"] == "2026-08-12T18:00:00Z"


def test_non_vehicle_payloads_are_ignored():
    summary = manheim_ingest.store(
        [_capture({"data": {"user": {"name": "WEST2EAST_4", "id": "abc"}}})]
    )

    assert summary["vehicles"] == 0
    assert manheim_ingest.vehicles() == []


def test_unparsable_body_does_not_raise():
    assert manheim_ingest.store([{"responseBody": "<html>nie JSON</html>"}])["vehicles"] == 0
    assert manheim_ingest.store([{}])["vehicles"] == 0
    assert manheim_ingest.store(["nie slownik"])["vehicles"] == 0


def test_entries_expire_after_ttl(monkeypatch):
    monkeypatch.setenv("MANHEIM_INGEST_TTL_MINUTES", "1")
    manheim_ingest.store([_capture({"results": [VEHICLE]})])
    assert len(manheim_ingest.vehicles()) == 1

    real_time = manheim_ingest.time.time
    monkeypatch.setattr(manheim_ingest.time, "time", lambda: real_time() + 3600)
    assert manheim_ingest.vehicles() == []


def test_gzipped_stringified_payload_is_unpacked():
    """Manheim pakuje duże wyniki: `compressed: true` + gzip w base64.

    Kształt i nazwy pól wzięte z realnej odpowiedzi getExecuteSearchId
    (1,13 MB, 100 lotów). Bez rozpakowania backend widział tylko napis.
    """
    import base64
    import gzip

    item = {
        "vin": "JTMRWRFV9PD204814",
        "unifiedId": "OVE.FAAO.453999130",
        "sourceYear": "2023",
        "sourceMake": "Toyota",
        "sourceModel": "RAV4",
        "sourceTrim": "Hybrid XLE",
        "odometer": 10393,
        "bidPrice": 35750,
        "buyNowPrice": 35950,
        "conditionGrade": "5",
        "saleDate": "2026-08-10T20:00:00Z",
        "pickupLocation": "FL - Manheim Orlando",
    }
    inner = json.dumps({"count": 1, "items": [item]}).encode()
    packed = base64.b64encode(gzip.compress(inner)).decode()

    summary = manheim_ingest.store(
        [_capture({"data": {"getExecuteSearchId": {"compressed": True, "stringifiedJSON": packed}}})]
    )

    assert summary["stored"] == 1
    stored = manheim_ingest.vehicles()[0]
    assert stored["sourceMake"] == "Toyota"
    assert stored["bidPrice"] == 35750


def test_plain_stringified_payload_still_works():
    inner = json.dumps({"items": [VEHICLE]})
    summary = manheim_ingest.store(
        [_capture({"data": {"getSearches": {"compressed": False, "stringifiedJSON": inner}}})]
    )
    assert summary["stored"] == 1
    assert manheim_ingest.vehicles()[0]["make"] == "Chrysler"


def test_templates_are_harvested_from_ordinary_captures(monkeypatch, tmp_path):
    """Szablon wyciągamy z tego, co kolektor i tak przysyła.

    Osobna ścieżka "wyślij szablon" w rozszerzeniu okazała się zawodna, a paczki
    z ruchem strony niosą komplet: URL, nagłówki i ciało żądania.
    """
    from api import manheim_jobs

    monkeypatch.setenv("MANHEIM_TEMPLATES_PATH", str(tmp_path / "t.json"))
    manheim_jobs.clear()

    capture = {
        "kind": "fetch",
        "url": "https://onesearch-api.manheim.com/graphql",
        "method": "POST",
        "requestHeaders": {"Authorization": "Bearer abc"},
        "requestBody": json.dumps(
            {
                "operationName": "getSearches",
                "variables": {"payload": '{"keyword":"toyota rav4"}'},
                "query": "query getSearches(...)",
            }
        ),
        "responseBody": json.dumps({"data": {"getSearches": {}}}),
    }
    manheim_ingest.store([capture])

    stored = manheim_jobs.templates()
    assert "getSearches" in stored
    assert stored["getSearches"]["headers"]["Authorization"] == "Bearer abc"
    assert stored["getSearches"]["body"]["operationName"] == "getSearches"


def test_unrelated_operations_are_not_treated_as_templates(monkeypatch, tmp_path):
    from api import manheim_jobs

    monkeypatch.setenv("MANHEIM_TEMPLATES_PATH", str(tmp_path / "t2.json"))
    manheim_jobs.clear()

    manheim_ingest.store(
        [
            {
                "url": "https://onesearch-api.manheim.com/graphql",
                "requestBody": json.dumps({"operationName": "getWorkbooks"}),
            }
        ]
    )
    assert manheim_jobs.templates() == {}
