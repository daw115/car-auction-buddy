"""
Stałe wyuczone z realnych danych aukcyjnych — razem z tym, skąd pochodzą.

Wszystko w tym pliku jest zmierzone, nie wymyślone. Przy każdej wartości stoi próbka,
na której powstała, i data pomiaru — bo stała bez metryczki starzeje się po cichu
i po pół roku nikt nie odróżni pomiaru od domysłu.

PRÓBKA

307 lotów pobranych z Manheimu (`data/manheim_ingest/`, odpowiedzi GraphQL rozpakowane
z gzip+base64), z czego 306 z pełnym modelem wyceny. Skład: 175 BMW, 114 Toyota,
11 Ford, 3 Hyundai, 3 Mercedes. Wszystkie mają `isAutoGradeOrManheimGrade: true`,
czyli grade policzony algorytmem, a nie wystawiony ręcznie.

OGRANICZENIA TEJ PRÓBKI — czytaj, zanim uogólnisz

  * Jedna giełda. Copart i IAAI nie mają w niej ani jednego lota, więc wyuczony prior
    opisuje auta dealerskie i poaukcyjne z Manheimu, a nie auta powypadkowe.
  * Skos ku górze: średni grade 4,49, dwie trzecie lotów powyżej 4,5. To są auta
    z rynku hurtowego, nie ze szkód całkowitych.
  * Dwie marki to 94% próbki.
  * Jeden dzień notowań (10 sierpnia 2026).

Na aukcjach powypadkowych te liczby będą inne. Traktuj je jako punkt startowy do
przeliczenia, gdy pojawią się dane z Copartu, a nie jako prawdę o całym rynku.
"""
from __future__ import annotations

SAMPLE_SIZE = 307
SAMPLE_DATE = "2026-08-10"
SAMPLE_SOURCE = "Manheim (OVE + aukcje fizyczne)"


# ──────────────────────────────────────────── ile wart jest brak raportu stanu

# NAJWAŻNIEJSZY POMIAR W TYM PLIKU.
#
# 280 z 307 lotów (91%) nie ma w danych ustrukturyzowanych ŻADNEGO sygnału uszkodzenia:
# `hasFrameDamage: false`, `hasPriorPaint: false`, brak czerwonego światła, czyste
# ogłoszenia. Naiwnie znaczyłoby to auto bez wad, czyli grade 5,0.
#
# Ich prawdziwy grade:  średnia 4,58 · mediana 4,60 · p10 4,0 · p90 5,0 · minimum 2,2
#
# Czyli 103 z tych 280 aut (37%) NIE jest „Extra Clean", a 19 nie jest nawet „Clean".
# Grade powstaje z pozycjowanego raportu stanu, którego w tych polach po prostu nie ma —
# a nie z tego, że raport jest pusty. To dwie różne rzeczy i mylenie ich zawyżało
# naszą ocenę systematycznie o 0,42 punktu.
#
# Kosztem tego błędu jest klient, któremu sprzedaliśmy „Extra Clean", a odebrał czwórkę.
NO_REPORT_PRIOR = 4.6
NO_REPORT_P10 = 4.0
NO_REPORT_P90 = 5.0
NO_REPORT_MIN = 2.2
NO_REPORT_SAMPLE = 280

# O tyle nasza rekonstrukcja zawyżała ocenę przed kalibracją.
MEASURED_OVERESTIMATION = 0.42


# ─────────────────────────────────────── model wyceny odtworzony z danych Manheimu

# `valuationsMmr` odsłania własny model giełdy i da się go zweryfikować:
#
#   mmrPrice == adjustedValue                                    w 100% przypadków
#   adjustedValue == baseValue + condition + odometer + color    w  98% przypadków
#
# Czyli notowanie MMR to wycena PO korektach, a model jest addytywny. To pozwala
# wyceniać loty bez MMR (Copart, IAAI) tą samą logiką, o ile ma się wartość bazową
# z innego źródła.
MMR_MODEL_ADDITIVE_MATCH = 0.98
MMR_EQUALS_ADJUSTED = 1.00

# Korekta za stan, mediana jako procent wartości bazowej. Punkt grade'u kosztuje
# 350-770 USD zależnie od tego, jaki grade przyjmie się za bazowy — sam Manheim
# bazy nie ujawnia, więc podajemy zakres, a nie jedną liczbę udającą pewność.
CONDITION_ADJUSTMENT_PCT_OF_BASE = 0.017
CONDITION_USD_PER_GRADE_POINT_LOW = 350
CONDITION_USD_PER_GRADE_POINT_HIGH = 770

# Korekta za przebieg, jako procent wartości bazowej.
ODOMETER_ADJUSTMENT_PCT_OF_BASE = 0.019
ODOMETER_LOW_MILEAGE_BONUS_PCT = 0.056   # poniżej 15 tys. mil
ODOMETER_HIGH_MILEAGE_PENALTY_PCT = -0.008  # powyżej 60 tys. mil
ODOMETER_LOW_THRESHOLD_MI = 15_000
ODOMETER_HIGH_THRESHOLD_MI = 60_000


def condition_value_usd(base_value_usd: float, grade_delta: float) -> float:
    """Ile dolarów wart jest ruch o `grade_delta` punktów przy tej wartości bazowej.

    Do jednego zastosowania: pokazać brokerowi, ile realnie kosztuje niepewność oceny.
    Przy aucie za 40 000 USD wahanie grade'u o pół punktu to kilkaset dolarów — czyli
    mniej, niż zwykle się zakłada, i wyraźnie mniej niż ryzyko nieopisanej szkody.
    """
    return base_value_usd * CONDITION_ADJUSTMENT_PCT_OF_BASE * grade_delta


def summary() -> str:
    return (
        f"Kalibracja z {SAMPLE_SIZE} lotów {SAMPLE_SOURCE}, {SAMPLE_DATE}. "
        f"Prior przy braku raportu stanu: {NO_REPORT_PRIOR} "
        f"(p10 {NO_REPORT_P10}, p90 {NO_REPORT_P90}, n={NO_REPORT_SAMPLE})."
    )
