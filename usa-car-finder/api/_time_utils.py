"""Aware UTC datetime helpers.

Wszystkie timestampy w DB/JSON zapisujemy jako aware UTC ISO string
(z sufiksem `+00:00`). Operacje subtract (duration calc) działają na
aware datetime — bez ryzyka pomylenia z naive local time.

Legacy compat: stare wpisy zapisywane przez `datetime.utcnow().isoformat()`
nie mają tzinfo (naive UTC string). `parse_iso_to_utc()` traktuje takie
jako UTC.
"""
from datetime import datetime, timezone


def utc_now() -> datetime:
    """Zwraca aktualny aware UTC datetime."""
    return datetime.now(timezone.utc)


def utc_now_iso(timespec: str = "seconds") -> str:
    """Zwraca ISO 8601 string aktualnego UTC z sufiksem '+00:00'.

    Format: '2026-05-13T01:36:18+00:00' (z timespec='seconds').
    Używany do zapisu created_at / started_at / finished_at w DB i jobs.
    """
    return utc_now().isoformat(timespec=timespec)


def parse_iso_to_utc(iso_str: str) -> datetime:
    """Parsuj ISO 8601 string do aware UTC datetime.

    - Jeśli string ma tzinfo (np. '+00:00', '+02:00', 'Z') → konwertuj do UTC.
    - Jeśli string nie ma tzinfo (legacy naive UTC zapisany przez
      `datetime.utcnow().isoformat()`) → ZAKŁADA że to UTC (bo to historyczny
      bug w kodzie — wszystkie naive stringi powstały z `utcnow()`).
    """
    # Python 3.11+ obsługuje `Z` suffix; dla starszych podmieniamy
    if iso_str.endswith("Z"):
        iso_str = iso_str[:-1] + "+00:00"
    dt = datetime.fromisoformat(iso_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt
