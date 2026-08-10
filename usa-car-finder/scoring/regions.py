"""
Podział stanów USA wg kosztu i czasu transportu do Polski.

Wydzielone z ai/analyzer.py, bo scoring musi z tego korzystać, a nie może ciągnąć
za sobą całego analizatora (ten importuje klientów AI i uruchamia wywołania sieciowe
przy imporcie modułu).
"""
from typing import Optional

# Wschód — najtańszy i najszybszy fracht (1400-1600 USD, 3-4 tygodnie).
EASTERN_STATES = frozenset(
    {"NY", "NJ", "PA", "CT", "MA", "RI", "VT", "NH", "ME", "MD", "DE", "VA", "NC", "SC", "GA", "FL"}
)

# Zachód — najdroższy (1800-2200 USD, 5-6 tygodni).
WESTERN_STATES = frozenset({"CA", "OR", "WA", "NV", "AZ", "UT", "CO", "NM"})


def region_of(state: Optional[str]) -> str:
    """'east' | 'central' | 'west' | 'unknown'."""
    if not state:
        return "unknown"
    code = state.strip().upper()[:2]
    if code in EASTERN_STATES:
        return "east"
    if code in WESTERN_STATES:
        return "west"
    return "central" if len(code) == 2 and code.isalpha() else "unknown"
