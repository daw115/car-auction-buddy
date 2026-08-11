"""
Kurs dolara do wyceny — z NBP, z narzutem i z pamięcią podręczną.

Kalkulator miał kurs 4,00 zł wpisany na sztywno. W sierpniu 2026 dolar kosztuje
około 3,72 zł, więc każda wycena była zawyżona o siedem procent po stronie kosztów
w USD — czyli o mniej więcej 4 000 zł na aucie za 15 000 dolarów. Kurs wpisany raz
starzeje się po cichu: nic się nie psuje, oferty po prostu przestają wygrywać.

DLACZEGO NARZUT, A NIE CZYSTY KURS NBP

Średni kurs NBP to notowanie referencyjne, nie cena, po której kupimy dolary. Bank
sprzeda je drożej, a między wystawieniem oferty a zamknięciem aukcji mija kilka dni,
w których kurs się rusza. Kwotowanie po kursie środkowym znaczy, że każdy ruch w górę
zjada prowizję albo wraca do klienta jako dopłata.

Narzut jest więc częścią wyceny, a nie ostrożnością: `FX_MARKUP_PCT`, domyślnie 2%.
Przy 3,72 daje to 3,79 — nadal wyraźnie poniżej starych 4,00.

DLACZEGO NIE PYTAMY NBP PRZY KAŻDYM LOCIE

Jedno wyszukiwanie to kilkadziesiąt wycen. NBP publikuje tabelę raz dziennie, więc
kurs trzymamy w pamięci procesu do końca dnia roboczego. Gdy API nie odpowiada,
schodzimy na ostatni znany kurs z dysku, a dopiero potem na wartość z `.env` — awaria
NBP nie może zatrzymać wyceny ani po cichu wrócić do kursu sprzed roku.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger("pricing.fx")

NBP_URL = "https://api.nbp.pl/api/exchangerates/rates/a/usd/?format=json"
NBP_TIMEOUT_S = 5

DEFAULT_MARKUP_PCT = 2.0
FALLBACK_RATE = 4.0

_lock = threading.Lock()
_cached: Optional["UsdRate"] = None


@dataclass(frozen=True)
class UsdRate:
    """Kurs użyty do wyceny — razem z tym, skąd się wziął."""

    rate: float
    mid: float
    markup_pct: float
    source: str
    as_of: str

    @property
    def stale(self) -> bool:
        return self.source != "nbp"

    def summary(self) -> str:
        """Zdanie do briefu brokera. Klient kursu nie widzi — widzi kwotę w złotych."""
        if self.source == "nbp":
            return f"kurs {self.rate:.4f} (NBP {self.mid:.4f} z {self.as_of} + {self.markup_pct:.1f}%)"
        return f"kurs {self.rate:.4f} — źródło zapasowe: {self.source}"


def _cache_path() -> Path:
    return Path(os.getenv("FX_CACHE_PATH", "./data/usd_rate.json"))


def _markup_pct() -> float:
    try:
        return float(os.getenv("FX_MARKUP_PCT", str(DEFAULT_MARKUP_PCT)))
    except ValueError:
        return DEFAULT_MARKUP_PCT


def _env_fallback() -> float:
    try:
        return float(os.getenv("DEFAULT_USD_RATE", str(FALLBACK_RATE)))
    except ValueError:
        return FALLBACK_RATE


def _apply_markup(mid: float) -> float:
    return round(mid * (1 + _markup_pct() / 100), 4)


def _fetch_nbp() -> Optional[tuple[float, str]]:
    """Średni kurs USD z tabeli A. None, gdy NBP nie odpowiada."""
    try:
        request = urllib.request.Request(NBP_URL, headers={"Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=NBP_TIMEOUT_S) as response:
            payload = json.loads(response.read().decode("utf-8"))
        rate = payload["rates"][0]
        return float(rate["mid"]), str(rate["effectiveDate"])
    except (urllib.error.URLError, OSError, KeyError, IndexError, ValueError, TypeError) as exc:
        logger.warning("NBP niedostępny (%s) — schodzę na kurs zapasowy", exc)
        return None


def _read_disk_cache() -> Optional[UsdRate]:
    path = _cache_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return UsdRate(
            rate=float(data["rate"]),
            mid=float(data["mid"]),
            markup_pct=float(data["markup_pct"]),
            source="nbp-cache",
            as_of=str(data["as_of"]),
        )
    except (OSError, KeyError, ValueError, TypeError):
        return None


def _write_disk_cache(rate: UsdRate) -> None:
    path = _cache_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "rate": rate.rate,
                    "mid": rate.mid,
                    "markup_pct": rate.markup_pct,
                    "as_of": rate.as_of,
                    "written_at": datetime.now().isoformat(timespec="seconds"),
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    except OSError as exc:
        logger.warning("Nie zapisałem kursu na dysk: %s", exc)


def _fresh_enough(rate: UsdRate) -> bool:
    """Kurs z dziś albo z ostatnich trzech dni — tyle trwa najdłuższy weekend świąteczny."""
    try:
        as_of = date.fromisoformat(rate.as_of)
    except ValueError:
        return False
    return date.today() - as_of <= timedelta(days=3)


def usd_rate(*, force_refresh: bool = False) -> UsdRate:
    """Kurs do wyceny. Bezpieczny wątkowo, pyta NBP najwyżej raz dziennie."""
    global _cached

    # Kurs przybity na sztywno: `FX_RATE_OVERRIDE`. Dwa zastosowania — testy, które
    # muszą dawać ten sam wynik bez sieci, i broker, który kupił dolary po znanym
    # kursie i chce wyceniać po nim, a nie po dzisiejszej tabeli NBP.
    pinned = os.getenv("FX_RATE_OVERRIDE")
    if pinned:
        try:
            value = float(pinned)
        except ValueError:
            logger.warning("FX_RATE_OVERRIDE='%s' nie jest liczbą — pomijam", pinned)
        else:
            return UsdRate(
                rate=value,
                mid=value,
                markup_pct=0.0,
                source="override",
                as_of=date.today().isoformat(),
            )

    with _lock:
        if _cached is not None and not force_refresh and _fresh_enough(_cached):
            return _cached

        fetched = _fetch_nbp()
        if fetched is not None:
            mid, as_of = fetched
            result = UsdRate(
                rate=_apply_markup(mid),
                mid=mid,
                markup_pct=_markup_pct(),
                source="nbp",
                as_of=as_of,
            )
            _write_disk_cache(result)
            _cached = result
            return result

        from_disk = _read_disk_cache()
        if from_disk is not None:
            _cached = from_disk
            return from_disk

        fallback = _env_fallback()
        result = UsdRate(
            rate=fallback,
            mid=fallback,
            markup_pct=0.0,
            source="env",
            as_of=date.today().isoformat(),
        )
        _cached = result
        return result


def current_rate() -> float:
    """Sama liczba — dla miejsc, które nie potrzebują wiedzieć, skąd pochodzi."""
    return usd_rate().rate


def reset_cache() -> None:
    """Czyści pamięć procesu. Do testów."""
    global _cached
    with _lock:
        _cached = None
