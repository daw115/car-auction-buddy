"""
Rodzaj napędu z opisu aukcyjnego — wejście do stawki cła i akcyzy.

Napęd decyduje o dwóch rzeczach naraz, w przeciwnych kierunkach:

  * CŁO — elektryki są WYŁĄCZONE ze zniesienia ceł z 1.07.2026. Tesla zmontowana
    we Fremont płaci pełne 10%, choć spalinowy Ford z tej samej hali płaci 0%.
  * AKCYZA — hybrydy mają stawki obniżone: 1,55% do 2000 cm³ i 9,3% od 2000 do
    3500 cm³, wobec 3,1% i 18,6% dla spalinowych. Interpretacja ogólna Ministra
    Finansów z 26 lutego 2026 rozstrzygnęła, że łagodne hybrydy (MHEV, instalacja
    48 V bez jazdy na samym prądzie) też się kwalifikują.

Druga z tych rzeczy jest wielka pieniężnie. Amerykański SUV z V6 3.5 MHEV to
akcyza 9,3% zamiast 18,6% — przy locie za 15 000 USD około 5 000 zł różnicy.
A takich aut na Copart jest coraz więcej, bo w USA mild hybrid jest od lat
standardem w segmencie, który sprowadzamy.

DLACZEGO TO JEST OSTROŻNE. Rozpoznajemy napęd ze stringów aukcyjnych ("2.5L I4
HYBRID", "SPORT HYBRID AWD"), a nie z homologacji. Pomyłka w stronę hybrydy zaniża
akcyzę o połowę, czyli wystawia klientowi cenę, której nie dotrzymamy — a to jest
dokładnie ten "koszt po drodze", którego obiecujemy nie robić. Dlatego hybrydę
uznajemy tylko przy jednoznacznym słowie w danych, a wszystko niepewne idzie jako
spalinowe, czyli po stawce wyższej.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class Drivetrain(str, Enum):
    """Napęd w podziale, który ma znaczenie podatkowe — nie technicznym."""

    ICE = "ice"          # spalinowy, w tym diesel
    MHEV = "mhev"        # łagodna hybryda 48 V
    HEV = "hev"          # pełna hybryda
    PHEV = "phev"        # hybryda plug-in
    BEV = "bev"          # wyłącznie elektryczny
    UNKNOWN = "unknown"

    @property
    def is_hybrid(self) -> bool:
        """Czy kwalifikuje się do obniżonej akcyzy (1,55% / 9,3%)."""
        return self in (Drivetrain.MHEV, Drivetrain.HEV, Drivetrain.PHEV)

    @property
    def is_electric(self) -> bool:
        """Czy to elektryk — zero akcyzy, ale też brak prawa do zerowego cła."""
        return self is Drivetrain.BEV


@dataclass(frozen=True)
class DrivetrainGuess:
    kind: Drivetrain
    confident: bool
    matched: Optional[str]
    reason: str


# Kolejność ma znaczenie: "PLUG-IN HYBRID" musi trafić w PHEV zanim samo "HYBRID"
# złapie je jako HEV. Stawka akcyzy wychodzi ta sama, ale opis dla brokera nie.
#
# \b na krawędziach chroni przed trafieniem w środek słowa — bez tego "EV" łapało
# "CHEVROLET" i robiło z Silverado elektryka zwolnionego z akcyzy.
_PATTERNS: tuple[tuple[Drivetrain, str], ...] = (
    (Drivetrain.PHEV, r"\bPLUG[\s-]?IN\b|\bPHEV\b|\bPRIME\b|\bRECHARGE\b|\bE[\s-]?HYBRID\b"),
    (Drivetrain.MHEV, r"\bMHEV\b|\bMILD[\s-]?HYBRID\b|\bEQ[\s-]?BOOST\b|\b48V\b|\bETORQUE\b|\bBSG\b"),
    (Drivetrain.HEV, r"\bHYBRID\b|\bHEV\b|\bHYBRYDA\b"),
    (Drivetrain.BEV, r"\bELECTRIC\b|\bBEV\b|\bEV\b|\bE[\s-]?TRON\b|\bIONIQ\s?[56]\b|\bID\.?[34567]\b"),
)

# Modele elektryczne, których nazwa nie zawiera żadnego z powyższych słów.
#
# To nie jest lista dla kompletności, tylko dla jednego konkretnego ryzyka: elektryk
# wzięty za spalinowego dostaje cło 0% zamiast 10%, czyli JEDYNĄ pomyłkę w tym module,
# która ZANIŻA cenę. BMW iX i Mercedes EQE przechodziły przez sito jako spalinowe,
# bo "iX" nie zawiera ani "EV", ani "ELECTRIC".
# UWAGA NA OZNACZENIA SILNIKÓW. "I4" i "I6" to układ cylindrów (rzędowy czterocylindrowy),
# a nie BMW i4 — wzorzec `\bI[3457]\b` łapał "2.5L I4 HYBRID" i robił z hybrydy Toyoty
# elektryka, czyli zabierał jej preferencyjną akcyzę i dokładał cło. Dlatego modele BMW
# i-serii wymagają marki BEZPOŚREDNIO przed nazwą: "BMW I4" trafia, "BMW X3 2.0L I4" nie.
_BEV_MODELS = (
    r"\bBMW\s+I[3457]\b|\bBMW\s+IX[1-3]?\b",        # BMW i3, i4, i5, i7, iX
    r"\bEQ[ABCESV]\b",                              # Mercedes EQA, EQB, EQC, EQE, EQS, EQV
    r"\bARIYA\b|\bLEAF\b",                          # Nissan
    r"\bMACH[\s-]?E\b|\bF[\s-]?150\s+LIGHTNING\b",  # Ford
    r"\bBLAZER\s+EV\b|\bEQUINOX\s+EV\b|\bSILVERADO\s+EV\b",  # Chevrolet
    r"\bLYRIQ\b|\bCELESTIQ\b|\bVISTIQ\b",           # Cadillac
    r"\bHUMMER\s+EV\b",
    r"\bRIVIAN\b|\bR1[TS]\b",                       # Rivian
    r"\bLUCID\b",                                   # Lucid
    r"\bSOLTERRA\b|\bBZ4X\b",                       # Subaru / Toyota
    r"\bKONA\s+ELECTRIC\b|\bNIRO\s+EV\b|\bEV[69]\b",  # Hyundai / Kia
    r"\bPOLESTAR\b|\bEX30\b|\bEX90\b",              # Polestar / Volvo
    r"\bTAYCAN\b",                                  # Porsche
)

# Modele, których nazwa nie zawiera słowa "hybrid", a hybrydami są zawsze. Aukcje
# podają "2019 TOYOTA PRIUS" bez żadnego dopisku i bez tej listy Prius szedłby
# po stawce spalinowej.
_ALWAYS: tuple[tuple[Drivetrain, str], ...] = (
    (Drivetrain.BEV, r"\bTESLA\b|\bMODEL\s?[3SXY]\b|\bMACH[\s-]?E\b|\bBOLT\b|\bLEAF\b|\bLYRIQ\b|\bRIVIAN\b|\bLUCID\b"),
    (Drivetrain.PHEV, r"\bVOLT\b|\bOUTLANDER\s?PHEV\b|\bWRANGLER\s?4XE\b|\b4XE\b"),
    (Drivetrain.HEV, r"\bPRIUS\b|\bINSIGHT\b|\bC[\s-]?MAX\b|\bMAVERICK\b"),
)

# "MODEL 3" i "BOLT" złapane wyżej występują też w nazwach, które elektrykami nie są
# (Chevrolet Bolt EUV jest, ale "BOLT ON" w opisie uszkodzeń już nie). Tekst do
# dopasowania budujemy więc wyłącznie z pól identyfikujących auto, nigdy z opisu szkód.
_SPLIT = re.compile(r"\s+")


def _haystack(*sources: Optional[str]) -> str:
    parts = [str(s).upper() for s in sources if s]
    return " ".join(_SPLIT.split(" ".join(parts)))


def detect(*sources: Optional[str]) -> DrivetrainGuess:
    """Napęd z marki, modelu i wersji wyposażenia.

    Podawaj tylko pola opisujące sam pojazd (make, model, trim). Wrzucenie tu opisu
    uszkodzeń albo notatki sprzedawcy skończy się fałszywym trafieniem.
    """
    text = _haystack(*sources)
    if not text.strip():
        return DrivetrainGuess(Drivetrain.UNKNOWN, False, None, "brak danych o wersji")

    for kind, pattern in _ALWAYS:
        match = re.search(pattern, text)
        if match:
            return DrivetrainGuess(kind, True, match.group(0), f"model zawsze {kind.value}: '{match.group(0)}'")

    for pattern in _BEV_MODELS:
        match = re.search(pattern, text)
        if match:
            return DrivetrainGuess(
                Drivetrain.BEV, True, match.group(0), f"model elektryczny: '{match.group(0)}'"
            )

    for kind, pattern in _PATTERNS:
        match = re.search(pattern, text)
        if match:
            return DrivetrainGuess(kind, True, match.group(0), f"słowo '{match.group(0)}' w opisie wersji")

    # Brak słowa-klucza traktujemy jako spalinowy, a nie jako "nie wiem". Spalinowy
    # to stawka wyższa, więc pomyłka w tę stronę zawyża wycenę zamiast ją zaniżać —
    # a zawyżoną cenę można obniżyć po weryfikacji, zaniżonej nie da się podnieść.
    return DrivetrainGuess(
        Drivetrain.ICE,
        False,
        None,
        "brak oznaczenia hybrydy lub elektryka — liczymy jak spalinowe",
    )


def detect_for_lot(lot) -> DrivetrainGuess:
    """Napęd dla lota z aukcji."""
    return detect(
        getattr(lot, "make", None),
        getattr(lot, "model", None),
        getattr(lot, "trim", None),
    )
