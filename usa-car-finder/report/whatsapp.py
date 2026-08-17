"""
Krótka wiadomość na WhatsApp z gotowymi ofertami — do wysłania przez brokera.

Ten moduł NICZEGO NIE WYSYŁA. Generuje treść i link wa.me, a decyzję o wysłaniu
podejmuje człowiek. To świadoma decyzja: wiadomość idzie do klienta pod nazwiskiem
brokera i musi przejść przez jego akceptację.

Zasady treści (wypracowane na realnych leadach z arkusza):
  * ceny podajemy W ZŁOTÓWKACH POD KLUCZ, razem z prowizją. Klient mówi "budżet 50/60 tys"
    i tak myśli; cena aukcyjna w dolarach nic mu nie mówi, a podana bez kontekstu wygląda
    na ukrywanie kosztów. Prowizja doliczona dopiero po ofercie to dokładnie ta dopłata
    po drodze, której obiecujemy nie robić — liczy to pricing/import_calculator.client_price_pln;
  * rejestracji NIE obiecujemy w cenie. Kalkulator jej nie liczy, więc nie ma jej w kwocie;
  * żadnego wewnętrznego score. Poprzednia wersja wysyłała "wynik AI 8/10", co jest
    naszą metryką roboczą, a klientowi brzmi jak ocena wystawiona przez maszynę;
  * 3-4 pozycje. Więcej paraliżuje wybór, mniej wygląda na brak oferty;
  * kończymy pytaniem. Celem wiadomości jest rozmowa, nie zamknięcie sprzedaży.
"""
import re
from dataclasses import dataclass
from typing import Iterable, Optional
from urllib.parse import quote

from parser.models import CarLot
from pricing.import_calculator import calculate_lot_import_costs
from scoring.budget import Settlement, landed_cost_for_lot, landed_cost_pln

MAX_OFFERS = 4
MIN_OFFERS = 3


@dataclass(frozen=True)
class OfferLine:
    lot: CarLot
    landed_pln: float
    over_budget: bool = False
    usd_rate: Optional[float] = None

    def render(self) -> str:
        name = f"{self.lot.year or ''} {_short_name(self.lot)}".strip()
        if self.lot.odometer_mi:
            # Klient liczy w kilometrach; mila zostaje w nawiasie, bo to ona
            # widnieje na liczniku i w dokumentach aukcji.
            km = self.lot.odometer_mi * 1.609344
            name += f", {km / 1000:.0f} tys. km ({self.lot.odometer_mi / 1000:.0f} tys. mil)"
        # Spacja jako separator tysięcy, ale TYLKO w liczbie — zamiana przecinków
        # w całej linii zjadałaby ten po nazwie modelu.
        price = f"{self.landed_pln:,.0f}".replace(",", "\u00a0")
        # Dolary w nawiasie: klient płaci w złotówkach, ale auto pochodzi z USA
        # i sam przelicza, żeby porównać z ogłoszeniami. Ta sama kwota po tym
        # samym kursie, nie cena aukcyjna.
        w_nawiasie = ""
        if self.usd_rate:
            w_dolarach = f"{self.landed_pln / self.usd_rate:,.0f}".replace(",", "\u00a0")
            w_nawiasie = f" ({w_dolarach} $)"
        # Klient zobaczy kwotę i sam policzy, że to więcej niż mówił. Napisane wprost
        # brzmi jak propozycja; przemilczane brzmi jak próba przemycenia.
        suffix = " (powyżej budżetu)" if self.over_budget else ""
        return f"• {name}: {price} zł{w_nawiasie}{suffix}"


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


# Aukcje podają nazwę wersji w całości i wersalikami: "AUDI Q7 PREMIUM PLUS 45
# TFSI QUATTRO TIPTRONIC". W wiadomości do klienta to szum, który zjada linijkę
# i brzmi jak przeklejone z systemu.
MAX_NAME_TOKENS = 4


def _short_name(lot: CarLot) -> str:
    """Marka i model w formie, w jakiej mówi o aucie człowiek."""
    make = (lot.make or "").strip()
    model = (lot.model or "").strip()
    # Model bywa powtórzony razem z marką ("AUDI Q7 ..." przy make="AUDI").
    if make and model.upper().startswith(make.upper()):
        model = model[len(make):].strip()
    tokens = [t for t in f"{make} {model}".split() if t][:MAX_NAME_TOKENS]
    return " ".join(t.title() if t.isupper() and t.isalpha() else t for t in tokens)


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
    allow_over_budget: bool = False,
) -> Optional[WhatsappDraft]:
    """Treść wiadomości dla 3-4 najlepszych ofert.

    Zwraca None, gdy nie ma ani jednej oferty — pusta wiadomość jest gorsza niż jej brak.

    Auta droższe niż budżet klienta domyślnie nie wchodzą do wiadomości. Wchodzą
    tylko wtedy, gdy broker świadomie je dopuści (allow_over_budget) — i wtedy są
    w treści oznaczone, a nagłówek przestaje twierdzić, że wszystko mieści się
    w kwocie, którą klient podał.
    """
    lines: list[OfferLine] = []
    for lot in lots:
        if len(lines) >= MAX_OFFERS:
            break
        price = lot.current_bid_usd or lot.buy_now_price_usd
        if not price:
            continue
        # Cenę bierzemy z wersji "per lot", bo tylko ona zna kraj montażu i napęd —
        # a od nich zależy cło (0% albo 10%) i akcyza. Wariant po samej cenie zostaje
        # jako awaryjny dla wywołań z jawnym kursem, np. z testów porównawczych.
        if usd_rate:
            landed = landed_cost_pln(
                price, settlement=settlement, state=lot.location_state, usd_rate=usd_rate
            )
        else:
            landed = landed_cost_for_lot(lot, settlement=settlement)
        if landed is None:
            continue
        over = bool(budget_pln and landed > budget_pln)
        if over and not allow_over_budget:
            continue
        # Kurs bierzemy z tej samej kalkulacji, która policzyła cenę pod klucz.
        # Osobne pytanie o kurs mogłoby trafić na inny dzień notowań i klient
        # dostałby dwie kwoty, które się nie przeliczają.
        kurs = usd_rate
        if kurs is None:
            koszty = calculate_lot_import_costs(lot)
            kurs = float(koszty["usd_rate"]) if koszty and koszty.get("usd_rate") else None
        lines.append(OfferLine(lot=lot, landed_pln=landed, over_budget=over, usd_rate=kurs))

    if not lines:
        return None

    any_over = any(line.over_budget for line in lines)
    budget_note = (
        f" pod Pana budżet {budget_pln / 1000:.0f} tys. zł"
        if budget_pln and not any_over
        else ""
    )
    header = (
        f"{_greeting(client_name)}, mam {len(lines)} "
        f"{'auto' if len(lines) == 1 else 'auta'}{budget_note}. Ceny pod klucz w Polsce:"
    )
    # „Bez dopłat po drodze" było prawdą tylko dla aut bez szkody. Kalkulacja nie
    # zawiera naprawy, a przy locie po szkodzie to różnica rzędu kilkunastu tysięcy
    # złotych — klient dowiadywał się o niej dopiero z raportu albo przy odbiorze.
    po_szkodzie = any(
        (line.lot.damage_primary or "").strip()
        and not re.search(r"(?:condition\s*grade|grade)\s*[0-5]", line.lot.damage_primary or "", re.I)
        for line in lines
    )
    czesci_stopki = [
        "W każdej cenie: zakup, transport, cło, akcyza i prowizja, bez dopłat po drodze."
    ]
    if po_szkodzie:
        czesci_stopki.append(
            "Ceny nie obejmują naprawy. W razie zainteresowania możemy wstępnie "
            "ocenić jej koszt."
        )
    czesci_stopki.append("Podesłać pełną kalkulację?")
    footer = "\n".join(czesci_stopki)

    text = "\n".join([header, "", *(line.render() for line in lines), "", footer])
    return WhatsappDraft(text=text, offers=len(lines))
