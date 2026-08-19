"""Każda zmienna użyta w szablonie musi być przez kod przekazana.

Ten test powstał po realnej wpadce. Podmieniłem w `client_hybrid.html.j2`
`lot.damage_primary` na `uszkodzenie_pl`, a wartość dodałem tylko do danych dla
modelu — do kontekstu Jinja już nie. Jinja nie protestuje: brakująca zmienna to
po prostu `Undefined`, więc `{{ uszkodzenie_pl or 'bez uwag' }}` wypisywało
„bez uwag" KAŻDEMU klientowi, także przy aucie zalanym i po pożarze. Raport
wyglądał na kompletny.

Test czyta szablony i kod, nie renderuje — chodzi o pytanie „czy ta zmienna ma
skąd przyjść", a nie o wygląd wyniku.
"""

import re
from pathlib import Path

KATALOG = Path(__file__).resolve().parents[1] / "report"

#: Zmienne wstrzykiwane przez Jinja albo przez `_env()`, nie przez wywołanie render().
WBUDOWANE = {"loop", "range", "dict", "lipsum", "cycler", "joiner", "namespace"}


def _zmienne_szablonu(sciezka: Path) -> set[str]:
    tresc = sciezka.read_text(encoding="utf-8")
    # `{{ nazwa }}`, `{{ nazwa.pole }}`, `{% if nazwa %}`, `{% for x in nazwa %}`
    surowe = re.findall(
        r"\{\{-?\s*([a-z_][a-z0-9_]*)"
        r"|{%-?\s*(?:if|for\s+\w+\s+in|elif)\s+(?:not\s+)?([a-z_][a-z0-9_]*)",
        tresc,
    )
    uzyte = {a or b for a, b in surowe}
    # Nazwy związane w samym szablonie: `{% for auto in auta %}`, `{% set x = %}`.
    # One nie mają przychodzić z kodu i zgłaszanie ich byłoby szumem, który każe
    # ignorować cały test.
    zwiazane = set(re.findall(r"{%-?\s*for\s+([a-z_][a-z0-9_]*(?:\s*,\s*[a-z_][a-z0-9_]*)*)\s+in", tresc))
    zwiazane = {n.strip() for grupa in zwiazane for n in grupa.split(",")}
    zwiazane |= set(re.findall(r"{%-?\s*set\s+([a-z_][a-z0-9_]*)", tresc))
    return uzyte - WBUDOWANE - zwiazane


def _przekazywane(kod: str, nazwa_szablonu: str) -> set[str]:
    """Nazwy podane w którymkolwiek `render(...)` w module — wystarczy, że któryś
    je przekazuje, bo jeden szablon bywa renderowany z kilku miejsc."""
    return set(re.findall(r"^\s*([a-z_][a-z0-9_]*)=", kod, re.M)) | set(
        re.findall(r'"([a-z_][a-z0-9_]*)":', kod)
    )


def test_szablon_klienta_hybrydowy_ma_komplet_zmiennych() -> None:
    szablon = KATALOG / "templates" / "hybrid" / "client_hybrid.html.j2"
    kod = (KATALOG / "hybrid_reports.py").read_text(encoding="utf-8")
    brakujace = sorted(_zmienne_szablonu(szablon) - _przekazywane(kod, szablon.name))
    assert not brakujace, f"szablon używa zmiennych, których kod nie przekazuje: {brakujace}"


def test_szablon_oferty_ma_komplet_zmiennych() -> None:
    szablon = KATALOG / "templates" / "client_shortlist.html.j2"
    kod = (KATALOG / "html_reports.py").read_text(encoding="utf-8")
    brakujace = sorted(_zmienne_szablonu(szablon) - _przekazywane(kod, szablon.name))
    assert not brakujace, f"szablon używa zmiennych, których kod nie przekazuje: {brakujace}"


def test_uszkodzenie_trafia_do_szablonu_klienta() -> None:
    """Konkretny przypadek, od którego się zaczęło — pilnowany osobno, bo to
    on decyduje, czy klient przeczyta prawdę o stanie auta."""
    kod = (KATALOG / "hybrid_reports.py").read_text(encoding="utf-8")
    render_klienta = kod[kod.index("def render_client_hybrid") : kod.index("def render_broker_hybrid")]
    assert "uszkodzenie_pl=" in render_klienta
