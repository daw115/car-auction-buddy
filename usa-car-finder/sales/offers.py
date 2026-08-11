"""Most między wynikami wyszukiwania a agentem sprzedaży.

Do tej pory `propose_reply(offers=...)` przyjmowało listę aut, ale żaden endpoint
jej nie przekazywał — więc na etapie „oferta" agent pisał do klienta, **nie znając
aut**, które mu proponujemy. Pisał ogólniki tam, gdzie miał podać konkrety.

Auta wybiera broker, nie automat. To ta sama zasada, co przy wysyłce: system
liczy i pisze, człowiek decyduje, co klient zobaczy.

Cena pod klucz idzie przez tę samą funkcję, co reszta systemu
(`pricing.import_calculator.client_price_pln` przez `scoring.budget`), żeby klient
nie dostał w rozmowie innej kwoty niż w mailu i w wiadomości WhatsApp.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from parser.models import CarLot

logger = logging.getLogger(__name__)

MAX_OFFERS = 4


def _short_name(lot: CarLot) -> str:
    parts = [str(lot.year or ""), lot.make or "", lot.model or ""]
    name = " ".join(part for part in parts if part).strip()
    return name or "auto z aukcji"


def offer_from_lot(
    lot: CarLot,
    *,
    budget_pln: Optional[float] = None,
    settlement: str = "private",
) -> Optional[dict[str, Any]]:
    """Jedno auto w formie, którą rozumie agent. None, gdy nie da się go wycenić.

    Bez ceny nie ma oferty: auto bez stawki na aukcji (licytacja jeszcze nieotwarta)
    trafiłoby do wiadomości jako pozycja bez kwoty, a to jest gorsze niż jej brak.
    """
    price_usd = lot.current_bid_usd or lot.buy_now_price_usd
    if not price_usd:
        return None

    try:
        from scoring.budget import landed_cost_pln

        landed = landed_cost_pln(
            price_usd,
            settlement="company" if settlement == "company" else "private",
            state=lot.location_state,
        )
    except Exception:
        logger.warning("[offers] nie policzyłem ceny pod klucz dla %s", lot.lot_id, exc_info=True)
        return None

    return {
        "nazwa": _short_name(lot),
        "cena_pln": round(landed),
        "ponad_budzet": bool(budget_pln and landed > budget_pln),
        "uszkodzenie": lot.damage_primary or None,
    }


def offers_from_lots(
    lots: list[CarLot],
    *,
    budget_pln: Optional[float] = None,
    settlement: str = "private",
    limit: int = MAX_OFFERS,
) -> list[dict[str, Any]]:
    """Lista aut dla agenta — w kolejności, w jakiej podał je broker.

    Nie sortujemy i nie dobieramy nic sami: broker wybrał te auta i tę kolejność,
    a przestawianie ich za jego plecami znaczyłoby, że klient dostaje inną
    propozycję niż ta, którą zatwierdził.
    """
    offers: list[dict[str, Any]] = []
    for lot in lots:
        if len(offers) >= limit:
            break
        offer = offer_from_lot(lot, budget_pln=budget_pln, settlement=settlement)
        if offer:
            offers.append(offer)
    return offers
