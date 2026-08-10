"""
Krótka wiadomość na WhatsApp z gotowymi ofertami — do wysłania przez brokera.

Ten moduł NICZEGO NIE WYSYŁA. Generuje treść i link wa.me, a decyzję o wysłaniu
podejmuje człowiek. To świadoma decyzja: wiadomość idzie do klienta pod nazwiskiem
brokera i musi przejść przez jego akceptację.

Zasady treści (wypracowane na realnych leadach z arkusza):
  * ceny podajemy W ZŁOTÓWKACH POD KLUCZ. Klient mówi "budżet 50/60 tys" i tak myśli;
    cena aukcyjna w dolarach nic mu nie mówi, a podana bez kontekstu wygląda na ukrywanie
    kosztów;
  * żadnego wewnętrznego score. Poprzednia wersja wysyłała "wynik AI 8/10", co jest
    naszą metryką roboczą, a klientowi brzmi jak ocena wystawiona przez maszynę;
  * 3-4 pozycje. Więcej paraliżuje wybór, mniej wygląda na brak oferty;
  * kończymy pytaniem. Celem wiadomości jest rozmowa, nie zamknięcie sprzedaży.
"""
from dataclasses import dataclass
from typing import Iterable, Optional
from urllib.parse import quote

from parser.models import CarLot
from scoring.budget import Settlement, landed_cost_pln

MAX_OFFERS = 4
MIN_OFFERS = 3


@dataclass(frozen=True)
class OfferLine:
    lot: CarLot
    landed_pln: float

    def render(self) -> str:
        parts = [str(self.lot.year or ""), self.lot.make or "", self.lot.model or ""]
        name = " ".join(part for part in parts if part).strip()
        if self.lot.odometer_mi:
            name += f", {self.lot.odometer_mi / 1000:.0f} tys. mil"
        # Spacja jako separator tysięcy, ale TYLKO w liczbie — zamiana przecinków
        # w całej linii zjadałaby ten po nazwie modelu.
        price = f"{self.landed_pln:,.0f}".replace(",", "\u00a0")
        return f"• {name} — {price} zł"


@dataclass(frozen=True)
class WhatsappDraft:
    """Gotowa treść. Wysyła broker, nie system."""

    text: str
    offers: int

    def wa_me_url(self, phone: str) -> str:
        """Link otwierający WhatsApp z wpisaną treścią — broker klika i wysyła."""
        return f"https://wa.me/{_normalize_phone(phone)}?text={quote(self.text)}"


def _normalize_phone(phone: str) -> str:
    """Numer z arkusza ("605083832") na format międzynarodowy bez plusa."""
    digits = "".join(ch for ch in str(phone) if ch.isdigit())
    if len(digits) == 9:  # numer krajowy bez kierunkowego
        return f"48{digits}"
    return digits


def _greeting(client_name: Optional[str]) -> str:
    if not client_name:
        return "Dzień dobry"
    first = client_name.strip().split()[0]
    return f"Dzień dobry, {first}"


def build_draft(
    lots: Iterable[CarLot],
    *,
    client_name: Optional[str] = None,
    budget_pln: Optional[float] = None,
    settlement: Settlement = "private",
    usd_rate: Optional[float] = None,
) -> Optional[WhatsappDraft]:
    """Treść wiadomości dla 3-4 najlepszych ofert.

    Zwraca None, gdy nie ma ani jednej oferty — pusta wiadomość jest gorsza niż jej brak.
    """
    lines: list[OfferLine] = []
    for lot in list(lots)[:MAX_OFFERS]:
        price = lot.current_bid_usd or lot.buy_now_price_usd
        if not price:
            continue
        landed = landed_cost_pln(
            price, settlement=settlement, state=lot.location_state, usd_rate=usd_rate
        )
        lines.append(OfferLine(lot=lot, landed_pln=landed))

    if not lines:
        return None

    budget_note = f" pod Pana budżet {budget_pln / 1000:.0f} tys. zł" if budget_pln else ""
    header = (
        f"{_greeting(client_name)}, mam {len(lines)} "
        f"{'auto' if len(lines) == 1 else 'auta'}{budget_note} — ceny pod klucz w Polsce:"
    )
    footer = (
        "W każdej cenie: zakup, transport, cło, akcyza i rejestracja — bez dopłat po drodze.\n"
        "Podesłać pełną kalkulację?"
    )

    text = "\n".join([header, "", *(line.render() for line in lines), "", footer])
    return WhatsappDraft(text=text, offers=len(lines))
