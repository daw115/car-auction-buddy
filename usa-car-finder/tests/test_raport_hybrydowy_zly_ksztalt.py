"""Zły kształt odpowiedzi modelu nie może dać raportu z samymi nagłówkami.

`render_pair_hybrid` brało `pair_fragments.get("client") or {}` bez sprawdzenia
kształtu. Model potrafi oddać poprawny składniowo JSON, ale płaski — bez podziału
na „client" i „broker" — albo tylko z jedną sekcją. `_parse_json_loose`
przepuszcza to bez słowa, a `.get(...) or {}` zamienia brak w pustkę: klient
dostawał sekcję „Historia tego auta" z nagłówkiem i zerem akapitów oraz pusty
werdykt. Wygląda to na przeoczenie autora, nie na brak danych od modelu.
"""

import re
from pathlib import Path

SZABLON = (
    Path(__file__).resolve().parents[1] / "report" / "templates" / "hybrid" / "client_hybrid.html.j2"
)


def test_sekcja_historii_znika_gdy_nie_ma_tresci() -> None:
    """Szukamy samego znacznika `<h2>`, nie napisu — ten pada też w komentarzu
    nad kodem i pierwsze wystąpienie trafiało właśnie tam."""
    tresc = SZABLON.read_text(encoding="utf-8")
    naglowek = tresc.index("<h2>📖 Historia tego auta</h2>")
    assert "{% if story_paragraphs %}" in tresc[:naglowek][-300:], (
        "nagłówek historii stoi bez warunku — pusta sekcja nadal się wyrenderuje"
    )


def test_puste_haslo_i_werdykt_nie_zostawiaja_dziury() -> None:
    tresc = SZABLON.read_text(encoding="utf-8")
    assert re.search(r"\{%\s*if tagline\s*%\}", tresc)
    assert re.search(r"\{%\s*if verdict_headline\s*%\}", tresc)
