"""Przebieg nasłuchów — sprawdza giełdy i odzywa się DO BROKERA.

Uruchamiany z timera systemd (`usacar-watch.timer`), nie z API: scrape trwa
kilkanaście minut i nie ma prawa blokować requestu.

Granica, której ten moduł nie przekracza: **nic nie idzie do klienta**. Nasłuch
przygotowuje materiał — nowe loty i gotową treść wiadomości — a wysyła człowiek.
To ta sama zasada, co przy ofertach: wiadomość idzie pod nazwiskiem brokera.

Powiadamiamy tylko o lotach, których broker w tym nasłuchu jeszcze nie widział.
Bez tego po trzech dobach dostawałby co rano tę samą listę i przestałby ją czytać.
"""
from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from typing import Optional

from parser.models import ClientCriteria
from watch import db as watch_db
from report.uszkodzenia import po_polsku

logger = logging.getLogger(__name__)

# Próg jakości dla powiadomienia. Nasłuch ma budzić brokera, gdy wjedzie coś
# wartego uwagi — nie przy każdym locie pasującym do marki i rocznika.
MIN_SCORE = float(os.getenv("WATCH_MIN_SCORE", "6.0"))


@dataclass
class WatchResult:
    watch_id: int
    checked: int = 0
    fresh: int = 0
    notified: bool = False
    error: Optional[str] = None


def _telegram_chat_id() -> Optional[int]:
    raw = (os.getenv("TELEGRAM_CHAT_ID") or "").strip()
    try:
        return int(raw) if raw else None
    except ValueError:
        return None


def _summary(watch: watch_db.Watch, lots: list) -> str:
    """Krótka notka DLA BROKERA — tu cyfry i żargon są dozwolone."""
    who = watch.client_name or watch.client_phone or f"nasłuch #{watch.id}"
    criteria = watch.criteria
    czego = " ".join(
        str(part) for part in (criteria.get("make"), criteria.get("model")) if part
    ).strip() or "auto"

    linie = [f"<b>Nowe auta w nasłuchu: {who}</b>", f"Szukane: {czego}", ""]
    for lot in lots[:5]:
        score = ((lot.raw_data or {}).get("unified_score") or {}).get("score")
        cena = lot.current_bid_usd or lot.buy_now_price_usd
        linie.append(
            "• {rok} {marka} {model}{wersja} — {przebieg}, {cena}, {stan}{ocena}".format(
                rok=lot.year or "?",
                marka=lot.make or "",
                model=lot.model or "",
                wersja=f" {lot.trim}" if lot.trim else "",
                przebieg=f"{lot.odometer_mi:,} mi" if lot.odometer_mi else "przebieg nieznany",
                cena=f"{cena:,.0f} USD" if cena else "licytacja jeszcze nieotwarta",
                stan=po_polsku(lot.damage_primary or "", mala=True) or "stan nieznany",
                ocena=f", ocena {score:.1f}" if score else "",
            )
        )
    if len(lots) > 5:
        linie.append(f"…i {len(lots) - 5} więcej")
    linie += ["", "Treść dla klienta czeka w dashboardzie — wysyłasz Ty."]
    return "\n".join(linie)


def _notify(watch: watch_db.Watch, lots: list) -> bool:
    """Wysyła notkę do brokera. Zwraca False, gdy nie ma czym — to nie błąd."""
    chat_id = _telegram_chat_id()
    if not chat_id:
        logger.info("[watch] brak TELEGRAM_CHAT_ID — pomijam powiadomienie")
        return False
    try:
        from notify import telegram

        if not telegram.is_configured():
            logger.info("[watch] Telegram nieskonfigurowany — pomijam powiadomienie")
            return False
        telegram.send_message(chat_id, _summary(watch, lots))
        return True
    except Exception:
        # Brak powiadomienia nie może zgubić wyniku — loty są już zapisane
        # jako widziane, a przebieg zapisany w bazie.
        logger.exception("[watch] powiadomienie nie poszło")
        return False


async def run_watch(watch: watch_db.Watch) -> WatchResult:
    """Jeden przebieg nasłuchu: scrape, ocena, różnica, powiadomienie."""
    result = WatchResult(watch_id=watch.id)
    try:
        criteria = ClientCriteria(**watch.criteria)
    except Exception as exc:
        result.error = f"kryteria nie do odczytania: {exc}"
        watch_db.record_run(watch.id, error=result.error)
        return result

    try:
        from ai.analyzer import _attach_unified_scores
        from scraper.automated_scraper import AutomatedScraper

        scraper = AutomatedScraper()
        lots = await scraper.search_cars(criteria)
        result.checked = len(lots)

        _attach_unified_scores(lots, criteria)
        warte = [
            lot
            for lot in lots
            if ((lot.raw_data or {}).get("unified_score") or {}).get("score", 0) >= MIN_SCORE
        ]

        logger.info(
            "[watch] #%s: %d lotów, %d powyżej progu %.1f",
            watch.id, len(lots), len(warte), MIN_SCORE,
        )
        fresh = watch_db.filter_unseen(watch.id, warte)
        result.fresh = len(fresh)

        # Oznaczamy WSZYSTKIE warte uwagi, nie tylko powiadomione — inaczej lot
        # tuż pod progiem wracałby przy każdym przebiegu.
        watch_db.mark_seen(watch.id, warte)

        if fresh:
            watch_db.record_hits(watch.id, fresh)
            result.notified = _notify(watch, fresh)
        watch_db.record_run(watch.id, found=len(fresh))
        logger.info(
            "[watch] #%s: %d lotów, %d wartych uwagi, %d nowych%s",
            watch.id, result.checked, len(warte), result.fresh,
            " (powiadomiono)" if result.notified else "",
        )
    except Exception as exc:
        result.error = str(exc)
        watch_db.record_run(watch.id, error=result.error)
        logger.exception("[watch] #%s przebieg nieudany", watch.id)

    return result


async def run_due() -> list[WatchResult]:
    """Wszystkie nasłuchy, którym minął odstęp. Kolejno, nie równolegle —
    scrape zajmuje przeglądarkę i dwurdzeniowy CPU serwera."""
    watches = watch_db.due()
    if not watches:
        logger.info("[watch] nic nie czeka")
        return []
    logger.info("[watch] do sprawdzenia: %d", len(watches))
    return [await run_watch(watch) for watch in watches]


def main() -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s | %(message)s"
    )
    results = asyncio.run(run_due())
    bledy = [r for r in results if r.error]
    for r in results:
        print(
            f"nasłuch #{r.watch_id}: sprawdzono {r.checked}, nowych {r.fresh}"
            + (f", BŁĄD: {r.error}" if r.error else "")
        )
    return 1 if bledy else 0


if __name__ == "__main__":
    raise SystemExit(main())
