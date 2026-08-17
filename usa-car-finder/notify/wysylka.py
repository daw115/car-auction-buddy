"""Dostarczanie gotowych plików na Telegram brokera.

Jedno miejsce, bo droga jest zawsze ta sama i zawsze kończy się tak samo: plik
ląduje na telefonie BROKERA, a nie u klienta. Do klienta trafia dopiero to, co
broker sam przekaże w rozmowie — ta zasada ma jeden punkt egzekwowania i to jest
ten plik.

Powód techniczny jest osobny i też jeden: link `wa.me` przenosi wyłącznie tekst,
więc panel nie ma jak podać klientowi załącznika. Bot dociera natomiast na ten sam
telefon, na którym toczy się rozmowa.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger("notify.wysylka")


class BrakOdbiorcow(RuntimeError):
    """Bot nieskonfigurowany albo nikt nie kliknął /start."""


class NicNieDoszlo(RuntimeError):
    """Telegram odrzucił wysyłkę do wszystkich odbiorców."""


def odbiorcy() -> list[int]:
    """Ci sami odbiorcy, co przy nocnych trafieniach z nasłuchów.

    Jedna lista dla wszystkich powiadomień znaczy jedno miejsce do wypisania się.
    """
    from notify import telegram as tg

    if not tg.is_configured():
        raise BrakOdbiorcow(
            "Bot Telegrama nie jest skonfigurowany — sprawdź Ustawienia → Powiadomienia."
        )

    from api import telegram_database as tdb

    chaty = [s["chat_id"] for s in tdb.list_active_subscribers()]
    if not chaty:
        raise BrakOdbiorcow(
            "Nikt nie jest zapisany do bota. Napisz do niego /start ze swojego telefonu."
        )
    return chaty


def wyslij_plik(
    dane: bytes,
    nazwa: str,
    podpis: str,
    *,
    jako_zdjecie: bool = False,
    chaty: Optional[list[int]] = None,
) -> int:
    """Wysyła jeden plik do wszystkich odbiorców. Zwraca, ilu go dostało.

    `jako_zdjecie` decyduje o tym, co broker może zrobić dalej: zdjęcie przekazuje
    się jednym gestem i u klienta ląduje jako obrazek w wątku, dokument przychodzi
    jako plik do pobrania. Dla pierwszej oferty chcemy tego pierwszego.

    Błąd u jednego odbiorcy nie przerywa reszty — broker może mieć dwa telefony,
    a jeden z nich wyłączony.
    """
    from notify import telegram as tg

    cele = chaty if chaty is not None else odbiorcy()
    with tempfile.NamedTemporaryFile(suffix=Path(nazwa).suffix or ".bin", delete=False) as tmp:
        tmp.write(dane)
        sciezka = tmp.name

    doszlo = 0
    try:
        for chat_id in cele:
            try:
                if jako_zdjecie:
                    tg.send_photo(chat_id, sciezka, caption=podpis, filename=nazwa)
                else:
                    tg.send_document(chat_id, sciezka, caption=podpis, filename=nazwa)
                doszlo += 1
            except Exception:  # noqa: BLE001 — jeden padnięty czat nie kończy wysyłki
                logger.warning("[telegram] nie udało się wysłać %s do %s", nazwa, chat_id, exc_info=True)
    finally:
        Path(sciezka).unlink(missing_ok=True)

    if not doszlo:
        raise NicNieDoszlo("Bot nie dostarczył pliku. Sprawdź logi.")
    return doszlo
