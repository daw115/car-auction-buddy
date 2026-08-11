"""
Kraj montażu z numeru VIN — jedyne kryterium zerowej stawki cła.

Od 1 lipca 2026 (rozporządzenie UE 2026/1455) auto sprowadzone z USA ma cło 0%,
ale TYLKO jeśli zostało zmontowane w Stanach. Decyduje miejsce produkcji, nie marka
i nie miejsce zakupu: BMW X5 ze Spartanburga ma 0%, a Audi Q5 z Meksyku kupione na
tej samej aukcji w San Diego ma pełne 10%. Ta różnica to około 12% ceny pod klucz
(cło plus VAT liczony od podstawy powiększonej o cło) i przesądza, czy wygramy ofertę.

Kraj montażu siedzi w PIERWSZYM znaku VIN-u. To ma praktyczne znaczenie u nas: Copart
maskuje sześć ostatnich znaków, ale pierwszy jest zawsze widoczny. Kwalifikację do 0%
da się więc ustalić z listy wyników, przed otwarciem szczegółów i przed wygraniem aukcji.

Zasada rozstrzygania wątpliwości jest jedna w całym module: gdy nie wiemy, zakładamy
wariant DROŻSZY dla nas, czyli cło 10%. Zaniżona wycena wraca jako dopłata po fakcie —
dokładnie to, czego obiecujemy klientowi nie robić.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# Pierwszy znak VIN → kraj montażu. Lista obejmuje kraje, które realnie widujemy
# na Copart/IAAI; reszta świata trafia do "innego kraju", co i tak daje cło 10%.
#
# Uwaga na 3: cały zakres 3A-3W to Meksyk, a stamtąd jedzie sporo aut europejskich
# marek (Audi Q5, VW Tiguan/Jetta, Mercedes GLB) i amerykańskich (Ford Fusion,
# Ram, Chevrolet Equinox). To najczęstsza pułapka — auto "amerykańskie" bez 0% cła.
_WMI_COUNTRY: dict[str, tuple[str, str]] = {
    "1": ("US", "Stany Zjednoczone"),
    "4": ("US", "Stany Zjednoczone"),
    "5": ("US", "Stany Zjednoczone"),
    "2": ("CA", "Kanada"),
    "3": ("MX", "Meksyk"),
    "6": ("AU", "Australia"),
    "8": ("AR", "Argentyna / Chile"),
    "9": ("BR", "Brazylia"),
    "J": ("JP", "Japonia"),
    "K": ("KR", "Korea Południowa"),
    "L": ("CN", "Chiny"),
    "M": ("IN", "Indie / Indonezja"),
    "N": ("TR", "Turcja"),
    "R": ("TW", "Tajwan"),
    "S": ("GB", "Wielka Brytania"),
    "T": ("CH", "Szwajcaria / Czechy / Węgry"),
    "U": ("SK", "Słowacja / Rumunia"),
    "V": ("FR", "Francja / Hiszpania"),
    "W": ("DE", "Niemcy"),
    "X": ("RU", "Rosja"),
    "Y": ("SE", "Szwecja / Finlandia"),
    "Z": ("IT", "Włochy"),
}

# Litery, których w VIN-ie nie ma — I, O i Q wyleciały, żeby nie myliły się z 1 i 0.
# Znak spoza tego zbioru znaczy, że pole nie jest VIN-em, tylko śmieciem z parsera.
_VIN_ALPHABET = set("0123456789ABCDEFGHJKLMNPRSTUVWXYZ")

MIN_USABLE_LENGTH = 8


@dataclass(frozen=True)
class VinOrigin:
    """Skąd pochodzi auto i na ile jesteśmy tego pewni."""

    country_code: Optional[str]
    country_name: str
    assembled_in_usa: bool
    confident: bool
    reason: str

    @property
    def unknown(self) -> bool:
        return self.country_code is None


UNKNOWN = VinOrigin(
    country_code=None,
    country_name="nieznany",
    assembled_in_usa=False,
    confident=False,
    reason="brak VIN-u",
)


def normalize(vin: Optional[str]) -> str:
    """VIN bez separatorów i wielkimi literami. Aukcje bywają niechlujne."""
    if not vin:
        return ""
    return "".join(ch for ch in str(vin).upper() if ch.isalnum())


def looks_like_vin(vin: Optional[str]) -> bool:
    """Czy to w ogóle VIN, a nie numer lota albo pusty placeholder.

    Nie wymagamy 17 znaków: Copart pokazuje zamaskowany numer w rodzaju
    'JTMBFREV0JD******', a gwiazdki odpadają przy normalizacji. Do ustalenia kraju
    wystarczy początek, więc odrzucamy tylko to, co początkiem VIN-u być nie może.
    """
    cleaned = normalize(vin)
    if len(cleaned) < MIN_USABLE_LENGTH:
        return False
    return all(ch in _VIN_ALPHABET for ch in cleaned)


def origin(vin: Optional[str]) -> VinOrigin:
    """Kraj montażu z VIN-u.

    Zwraca `confident=False`, gdy VIN-u brakuje albo jest nieczytelny. Wywołujący ma
    wtedy policzyć cło po wyższej stawce, a nie zgadywać po marce — "Ford" nie znaczy
    "zmontowany w USA" (Ford Fusion jechał z Meksyku, Transit Connect z Hiszpanii).
    """
    cleaned = normalize(vin)
    if not looks_like_vin(cleaned):
        return UNKNOWN

    entry = _WMI_COUNTRY.get(cleaned[0])
    if entry is None:
        return VinOrigin(
            country_code=None,
            country_name="nieznany",
            assembled_in_usa=False,
            confident=False,
            reason=f"nierozpoznany kod kraju '{cleaned[0]}'",
        )

    code, name = entry
    in_usa = code == "US"
    return VinOrigin(
        country_code=code,
        country_name=name,
        assembled_in_usa=in_usa,
        confident=True,
        reason=(
            f"VIN zaczyna się od '{cleaned[0]}' — montaż w USA"
            if in_usa
            else f"VIN zaczyna się od '{cleaned[0]}' — montaż poza USA ({name})"
        ),
    )


def origin_for_lot(lot) -> VinOrigin:
    """Kraj montażu dla lota — z pełnego VIN-u, a gdy go nie ma, z zamaskowanego.

    `full_vin` pochodzi z rozszerzenia i bywa pusty. Zamaskowany `vin` z listy wyników
    niesie ten sam pierwszy znak, więc do cła jest tak samo dobry — a jest dostępny
    zanim w ogóle otworzymy szczegóły aukcji.
    """
    for candidate in (getattr(lot, "full_vin", None), getattr(lot, "vin", None)):
        result = origin(candidate)
        if result.confident:
            return result
    return UNKNOWN
