"""
Wiedza handlowa agenta: cel każdego etapu, obiekcje i fakty rynkowe.

Ten moduł jest jedynym miejscem, w którym trzymamy to, co agent ma WIEDZIEĆ o rynku.
Prompt systemowy (`agent-sprzedaz-usa.md`) opisuje, JAK agent ma pisać, i musi zostawać
bajt w bajt identyczny między wywołaniami, żeby trafiać w cache promptów. Fakty się
zmieniają, styl nie — dlatego są osobno i wjeżdżają do wiadomości użytkownika.

FAKTY MAJĄ DATY. Każdy niesie stan na dzień, w którym go sprawdzono, i źródło. Bez tego
za pół roku nikt nie odróżni ustalenia od domysłu, a agent będzie z przekonaniem
powtarzał klientom nieaktualne stawki — czyli robił dokładnie tę szkodę, którą ten plik
ma likwidować.

CZEGO TU NIE MA: kwot. Ceny liczy `pricing/import_calculator.py` i wchodzą do rozmowy
gotowe. Wpisana tutaj cena rozjechałaby się z ofertą przy pierwszej zmianie kursu.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sales.models import Stage


@dataclass(frozen=True)
class MarketFact:
    """Jedno ustalenie o rynku — z datą i źródłem, bo inaczej się zestarzeje po cichu."""

    key: str
    fact: str
    as_of: str
    source: str


# Stan na 11 sierpnia 2026. Przy aktualizacji zmieniaj też `as_of` — data jest częścią
# faktu, a nie ozdobą.
MARKET_FACTS: tuple[MarketFact, ...] = (
    MarketFact(
        key="clo_zero",
        fact=(
            "Od 1 lipca 2026 auta osobowe zmontowane w USA wjeżdżają do UE bez cła "
            "(rozporządzenie UE 2026/1455, preferencja do 31 grudnia 2029). Decyduje kraj "
            "montażu, nie marka — sprawdzamy go po pierwszym znaku VIN. Auta zmontowane "
            "w Meksyku, Kanadzie czy Japonii płacą cło 10% mimo zakupu w USA."
        ),
        as_of="2026-08-11",
        source="rozporządzenie UE 2026/1455",
    ),
    MarketFact(
        key="clo_ev",
        fact=(
            "Samochody elektryczne są wyłączone ze zniesienia ceł — płacą pełne 10%, "
            "nawet zmontowane w USA. Akcyzy nie płacą wcale."
        ),
        as_of="2026-08-11",
        source="rozporządzenie UE 2026/1455, wykaz wyłączeń",
    ),
    MarketFact(
        key="akcyza_hybrydy",
        fact=(
            "Akcyza ma cztery stawki: 3,1% (spalinowy do 2000 cm³), 18,6% (spalinowy "
            "powyżej), 1,55% (hybryda do 2000 cm³) i 9,3% (hybryda 2000–3500 cm³). "
            "Interpretacja ogólna Ministra Finansów z 26 lutego 2026 objęła preferencją "
            "także łagodne hybrydy 48 V. Powyżej 3500 cm³ preferencji nie ma."
        ),
        as_of="2026-08-11",
        source="ustawa o podatku akcyzowym + interpretacja ogólna MF z 26.02.2026",
    ),
    MarketFact(
        key="rynek",
        fact=(
            "W pierwszym półroczu 2026 sprowadzono z USA do Polski 38 276 aut używanych, "
            "o 5,3% więcej niż rok wcześniej. USA są trzecim źródłem importu po Niemczech "
            "i Francji, przy czym import z obu tych krajów w tym czasie spadł."
        ),
        as_of="2026-08-11",
        source="dane o rejestracjach, I półrocze 2026",
    ),
    MarketFact(
        key="czas",
        fact=(
            "Od wygranej aukcji do odbioru auta w Polsce mija zwykle 6–10 tygodni: "
            "transport lądowy do portu, 14–21 dni rejsu, odprawa i transport do kraju."
        ),
        as_of="2026-08-11",
        source="praktyka rynkowa 2026",
    ),
    MarketFact(
        key="oszczednosc",
        fact=(
            "Typowa oszczędność wobec ceny podobnego auta na polskim rynku to 20–30% "
            "po doliczeniu wszystkich kosztów sprowadzenia — bez kosztu naprawy."
        ),
        as_of="2026-08-11",
        source="analizy rynkowe 2026",
    ),
)


def facts_text() -> str:
    """Fakty rynkowe w formie, którą wkładamy do wiadomości użytkownika."""
    return "\n".join(f"- [{f.as_of}] {f.fact}" for f in MARKET_FACTS)


# ────────────────────────────────────────────────────────────── cele etapów


STAGE_GOALS: dict[Stage, str] = {
    Stage.NOWY: (
        "Potwierdź, że rozumiesz zapytanie, i zadaj JEDNO brakujące pytanie. "
        "Nie sprzedawaj — na tym etapie klient sprawdza, czy w ogóle odpisujemy."
    ),
    Stage.KWALIFIKACJA: (
        "Zdobądź brakujące dane: budżet pod klucz, rocznik, zgodę na auto po szkodzie. "
        "Jedno pytanie w wiadomości. Trzy pytania naraz zostają bez odpowiedzi."
    ),
    Stage.SZUKANIE: (
        "Daj znać, że szukamy, i powiedz kiedy wrócisz z konkretem. Nie obiecuj auta, "
        "którego jeszcze nie widzieliśmy."
    ),
    Stage.OFERTA: (
        "Oferta poszła. Zapytaj o reakcję na konkret — które auto najbardziej pasuje — "
        "zamiast pytać ogólnie, co sądzi."
    ),
    Stage.ROZMOWA: (
        "Odpowiedz na to, o co klient faktycznie zapytał. Jedna obiekcja, jedna "
        "odpowiedź. Zamknij pytaniem, które posuwa sprawę o krok."
    ),
    Stage.DECYZJA: (
        "Klient wybrał auto. Ustal limit licytacji i termin aukcji. To jedyny etap, "
        "na którym mówimy o kwocie granicznej."
    ),
    Stage.LICYTACJA: (
        "Poinformuj o terminie i o tym, że stawka może pójść w górę. Nie obiecuj wygranej."
    ),
    Stage.WYGRANA: (
        "Potwierdź zakup i powiedz, co dzieje się dalej oraz kiedy klient dostanie "
        "kolejną wiadomość."
    ),
    Stage.PRZEGRANA: (
        "Aukcja poszła wyżej niż limit. Powiedz to wprost i zaproponuj kolejne auta — "
        "przegrana licytacja jest normalna i nie jest niczyją winą."
    ),
    Stage.STRACONY: (
        "Nie pisz nic sprzedażowego. Najwyżej zamknij rozmowę uprzejmie."
    ),
}


# ────────────────────────────────────────────────────────────── obiekcje


@dataclass(frozen=True)
class Objection:
    """Obiekcja klienta i sposób odpowiedzi — nie gotowa formułka, tylko kierunek."""

    key: str
    trigger: str          # jak brzmi w wiadomości klienta
    answer: str           # czym odpowiadamy
    never: str            # czego przy tej obiekcji nie wolno powiedzieć


OBJECTIONS: tuple[Objection, ...] = (
    Objection(
        key="za_drogo",
        trigger="„za drogo”, „myślałem że taniej”, „w Polsce znajdę podobne”",
        answer=(
            "Pokaż, co składa się na cenę i że nie ma w niej dopłat po drodze. Jeśli "
            "klient porównuje do auta bezwypadkowego z polskiego rynku, porównanie jest "
            "nie do obrony i lepiej to przyznać niż przekonywać."
        ),
        never="Nie obniżaj prowizji w wiadomości. To decyzja brokera, nie agenta.",
    ),
    Objection(
        key="rozbite",
        trigger="„a jak bardzo rozbite”, „czy to się da naprawić”",
        answer=(
            "Nazwij uszkodzenie wprost i powiedz, czego z aukcji nie wiadomo: zakresu "
            "naprawy nie oceniamy zdalnie. Auto jest tańsze właśnie dlatego, że jest po "
            "szkodzie — to nie jest informacja do ukrycia."
        ),
        never="Nie szacuj kosztu naprawy. Nie widzieliśmy auta i każda liczba będzie zmyślona.",
    ),
    Objection(
        key="rejestracja",
        trigger="„czy da się zarejestrować”, „co z przeglądem”",
        answer=(
            "Auto po naprawie przechodzi badanie techniczne i da się zarejestrować. "
            "Rejestracji nie ma w naszej cenie i trzeba to powiedzieć wprost."
        ),
        never="Nie obiecuj rejestracji w cenie ani terminu jej załatwienia.",
    ),
    Objection(
        key="czas",
        trigger="„ile to trwa”, „kiedy będzie w Polsce”",
        answer="Podaj widełki 6–10 tygodni od wygranej aukcji i powiedz, z czego się składają.",
        never="Nie podawaj konkretnej daty dostawy. Rejs i odprawa nie chodzą według obietnic.",
    ),
    Objection(
        key="aukcja_wyzej",
        trigger="„a jak ktoś przebije”, „co jeśli pójdzie drożej”",
        answer=(
            "Powiedz, że cena w ofercie jest stawką na dziś, a limit licytacji ustala "
            "klient. Przegrana aukcja nic nie kosztuje — szukamy dalej."
        ),
        never="Nie obiecuj wygrania aukcji ani ceny końcowej.",
    ),
    Objection(
        key="niemcy",
        trigger="„czemu nie z Niemiec”, „w Niemczech taniej”",
        answer=(
            "Z Niemiec przywozimy auto z rynku wtórnego po cenie rynkowej. Z USA "
            "kupujemy na aukcji auto po szkodzie, więc różnica bierze się ze stanu, "
            "a nie z kraju. Powiedz to bez przekonywania — klient sam policzy."
        ),
        never="Nie mów, że auta z Niemiec są gorsze. Klient słyszy wtedy sprzedawcę, nie doradcę.",
    ),
    Objection(
        key="gwarancja",
        trigger="„jaka gwarancja”, „co jeśli będzie problem”",
        answer=(
            "Gwarancji na auto z aukcji nie ma i trzeba to powiedzieć wprost. "
            "Odpowiadamy za prowadzenie zakupu, transport i odprawę, nie za stan auta."
        ),
        never="Nie sugeruj żadnej gwarancji ani rękojmi — to obietnica, której nie dotrzymamy.",
    ),
    Objection(
        key="zaliczka",
        trigger="„ile z góry”, „kiedy płacę”",
        answer="Odeślij do brokera. Warunków płatności agent nie ustala.",
        never="Nie podawaj kwot zaliczki, numerów kont ani terminów płatności.",
    ),
)


def objection_hints(text: str) -> list[Objection]:
    """Obiekcje, które mogą siedzieć w wiadomości klienta.

    Dopasowanie jest zgrubne i celowo hojne: agent dostaje kilka kandydatów i sam
    rozstrzyga, o co klientowi chodziło. Zgadywanie jednej właściwej po słowie
    kluczowym kończyło się odpowiadaniem na obiekcję, której nikt nie zgłosił.
    """
    lowered = (text or "").lower()
    hits: list[Objection] = []
    for objection, words in _OBJECTION_WORDS.items():
        if any(word in lowered for word in words):
            found = next((o for o in OBJECTIONS if o.key == objection), None)
            if found:
                hits.append(found)
    return hits


_OBJECTION_WORDS: dict[str, tuple[str, ...]] = {
    "za_drogo": ("drogo", "taniej", "za dużo", "nie stać", "obniż", "rabat", "zniż"),
    "rozbite": ("rozbit", "uszkodz", "szkod", "napraw", "wypadk", "blachar"),
    "rejestracja": ("rejestr", "przegląd", "badanie techniczne", "homologac", "tablic"),
    "czas": ("ile to trwa", "kiedy będzie", "jak długo", "termin", "czekać", "tygodni"),
    "aukcja_wyzej": ("przebij", "licytac", "wyżej", "przelicytu"),
    "niemcy": ("niemiec", "niemczech", "z europy", "krajowy"),
    "gwarancja": ("gwaranc", "rękojm", "reklamac", "co jeśli będzie"),
    "zaliczka": ("zaliczk", "przedpłat", "z góry", "przelew", "konto", "płatnoś"),
}


def objections_text(hits: Optional[list[Objection]] = None) -> str:
    """Obiekcje do wstawienia w wiadomość użytkownika — wybrane albo wszystkie."""
    chosen = hits if hits else list(OBJECTIONS)
    return "\n".join(
        f"- {o.key}: gdy klient pisze {o.trigger}\n"
        f"  odpowiadasz: {o.answer}\n"
        f"  nigdy: {o.never}"
        for o in chosen
    )
