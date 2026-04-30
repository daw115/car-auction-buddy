"""
Generator maili HTML z ofertą aut z USA.

Struktura odpowiada opisowi z `przyklady_maili_README.md`:
- mail ofertowy budowany z danych zapytania klienta,
- do maila trafiają tylko auta zatwierdzone w panelu raportu,
- każde auto dostaje kolejny `recommended_rank`,
- brakujące dane są oznaczane jako "brak danych" zamiast dopowiadania faktów.
"""
import os
from datetime import datetime
from html import escape
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv

from parser.models import AnalyzedLot, ClientCriteria
from pricing.import_calculator import calculate_lot_import_costs, format_pln, format_usd

load_dotenv()

REPORTS_DIR = Path(os.getenv("REPORTS_DIR", "./data/reports"))


def _text(value) -> str:
    if value is None or value == "":
        return "brak danych"
    return escape(str(value), quote=False)


def _attr(value) -> str:
    if value is None:
        return ""
    return escape(str(value), quote=True)


def _money_usd(value) -> str:
    if value is None:
        return "brak danych"
    try:
        return format_usd(float(value))
    except (TypeError, ValueError):
        return _text(value)


def _mileage(value) -> str:
    if value is None:
        return "brak danych"
    try:
        return f"{int(value):,} mi".replace(",", " ")
    except (TypeError, ValueError):
        return _text(value)


def _vehicle_name(item: AnalyzedLot) -> str:
    lot = item.lot
    parts = [lot.year, lot.make, lot.model, lot.trim]
    return " ".join(str(part) for part in parts if part) or "Auto z USA"


def _damage(item: AnalyzedLot) -> str:
    lot = item.lot
    parts = [lot.damage_primary, lot.damage_secondary]
    return " + ".join(part for part in parts if part) or "brak danych"


def _location(item: AnalyzedLot) -> str:
    lot = item.lot
    return ", ".join(part for part in [lot.location_city, lot.location_state] if part) or "brak danych"


def _search_label(criteria: Optional[ClientCriteria], lots: List[AnalyzedLot]) -> str:
    if criteria:
        vehicle = " ".join(part for part in [criteria.make, criteria.model] if part)
        year = ""
        if criteria.year_from and criteria.year_to:
            year = f", roczniki {criteria.year_from}-{criteria.year_to}"
        elif criteria.year_from:
            year = f", rocznik od {criteria.year_from}"
        budget = f", budżet do {_money_usd(criteria.budget_usd)}" if criteria.budget_usd else ""
        mileage = f", przebieg do {_mileage(criteria.max_odometer_mi)}" if criteria.max_odometer_mi else ""
        return f"{vehicle or 'auta z USA'}{year}{budget}{mileage}"

    if lots:
        first = lots[0].lot
        vehicle = " ".join(part for part in [first.make, first.model] if part)
        if vehicle:
            return vehicle

    return "auta z USA"


def _status(item: AnalyzedLot) -> tuple[str, str, str]:
    recommendation = item.analysis.recommendation
    if recommendation == "POLECAM":
        return "Rekomendacja", "#e8f5e9", "#1b5e20"
    if recommendation == "RYZYKO":
        return "Warunkowo", "#fff8e1", "#8a5a00"
    if recommendation == "ODRZUĆ":
        return "Nie rekomendujemy", "#fde8e8", "#b42318"
    return "Do weryfikacji", "#eef2f7", "#344054"


def _client_greeting(client_name: Optional[str]) -> str:
    client_name = (client_name or "").strip()
    return f"Dzień dobry {client_name}," if client_name else "Dzień dobry,"


def _total_cost_pln(item: AnalyzedLot) -> str:
    costs = calculate_lot_import_costs(item.lot)
    if costs:
        return format_pln(costs["private_total_pln"])
    return "brak danych"


def _cost_note(item: AnalyzedLot) -> str:
    costs = calculate_lot_import_costs(item.lot)
    if not costs:
        return "Brak pełnej kalkulacji importu - do potwierdzenia po aktualnym bidzie i lokalizacji."
    return (
        f"Szacunek dla osoby prywatnej przy akcyzie 3,1%. "
        f"Towing: {format_usd(costs['towing_usd'])}, suma USA: {format_usd(costs['usa_total_usd'])}."
    )


def build_client_offer_subject(criteria: Optional[ClientCriteria], analyzed_lots: List[AnalyzedLot]) -> str:
    query = _search_label(criteria, analyzed_lots)
    count = len([item for item in analyzed_lots if item.included_in_report])
    suffix = "propozycja" if count == 1 else "propozycje"
    return f"Oferta aut z USA - {query} - {count} {suffix}"


def _info_row(label: str, value: str) -> str:
    return f"""
        <tr>
          <td style="padding:8px 10px;border-bottom:1px solid #e6e8ee;color:#667085;width:42%;">{_text(label)}</td>
          <td style="padding:8px 10px;border-bottom:1px solid #e6e8ee;font-weight:700;color:#111827;">{value}</td>
        </tr>
"""


def _car_block(item: AnalyzedLot, rank: int) -> str:
    lot = item.lot
    ai = item.analysis
    status_label, status_bg, status_color = _status(item)
    image_html = ""
    if lot.images:
        image_url = lot.images[0]
        image_html = f"""
          <img src="{_attr(image_url)}" alt="{_attr(_vehicle_name(item))}" width="640"
               style="display:block;width:100%;max-width:640px;height:auto;border-radius:10px;margin:14px 0;border:1px solid #e6e8ee;">
"""

    flags = "".join(
        f"<li style=\"margin:0 0 4px 0;\">{_text(flag)}</li>"
        for flag in (ai.red_flags or [])
    )
    flags_html = ""
    if flags:
        flags_html = f"""
        <div style="background:#fff8e6;border-left:4px solid #e6a817;padding:10px 12px;margin:12px 0;color:#7a4f00;">
          <strong>Ryzyka do sprawdzenia:</strong>
          <ul style="margin:6px 0 0 18px;padding:0;">{flags}</ul>
        </div>
"""

    auction_button = ""
    if lot.url:
        auction_button = f"""
        <p style="margin:16px 0 0 0;">
          <a href="{_attr(lot.url)}"
             style="display:inline-block;background:#244c8f;color:#ffffff;text-decoration:none;padding:10px 14px;border-radius:6px;font-weight:700;">
            Otwórz aukcję
          </a>
        </p>
"""

    description = ai.client_description_pl or "Brak opisu analizy. Wymagana ręczna weryfikacja przed licytacją."
    broker_notes = ai.ai_notes or "Do ręcznej weryfikacji przed licytacją."

    return f"""
  <tr>
    <td style="padding:0 30px 20px 30px;">
      <table role="presentation" width="100%" cellspacing="0" cellpadding="0"
             style="border:1px solid #d9e2ec;border-radius:12px;background:#ffffff;overflow:hidden;">
        <tr>
          <td style="padding:18px 20px;border-bottom:1px solid #e6e8ee;">
            <div style="font-size:12px;text-transform:uppercase;letter-spacing:.06em;color:#667085;font-weight:700;">
              Rekomendacja #{rank} - {_text(lot.source.upper() if lot.source else 'aukcja')}
            </div>
            <h2 style="font-size:22px;line-height:1.25;margin:4px 0 6px 0;color:#111827;">
              {_text(_vehicle_name(item))}
            </h2>
            <div style="font-size:13px;color:#667085;">
              Lot {_text(lot.lot_id)} - {_text(_location(item))} - aukcja: {_text(lot.auction_date)}
            </div>
            <div style="margin-top:10px;">
              <span style="display:inline-block;background:{status_bg};color:{status_color};padding:6px 10px;border-radius:999px;font-size:12px;font-weight:800;">
                {_text(status_label)} - {_text(f'{ai.score:.1f}/10')}
              </span>
            </div>
            {image_html}
          </td>
        </tr>
        <tr>
          <td style="padding:0 20px 14px 20px;">
            <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="font-size:14px;border-collapse:collapse;">
              {_info_row("Przebieg", _text(_mileage(lot.odometer_mi)))}
              {_info_row("Uszkodzenie", _text(_damage(item)))}
              {_info_row("Tytuł", _text(lot.title_type))}
              {_info_row("Sprzedawca", _text(lot.seller_type))}
              {_info_row("Aktualna oferta", _text(_money_usd(lot.current_bid_usd)))}
              {_info_row("Kup teraz", _text(_money_usd(lot.buy_now_price_usd)))}
              {_info_row("Szacowana naprawa", _text(_money_usd(ai.estimated_repair_usd)))}
              {_info_row("Szacowany koszt PL", _text(_total_cost_pln(item)))}
            </table>

            <div style="background:#f9fbff;border-left:4px solid #244c8f;padding:12px 14px;margin:14px 0;color:#344054;font-size:14px;line-height:1.5;">
              {_text(description)}
            </div>

            {flags_html}

            <p style="margin:12px 0 0 0;color:#4a5568;font-size:13px;line-height:1.5;">
              <strong>Notatka:</strong> {_text(broker_notes)}
            </p>
            <p style="margin:8px 0 0 0;color:#4a5568;font-size:13px;line-height:1.5;">
              {_text(_cost_note(item))}
            </p>
            {auction_button}
          </td>
        </tr>
      </table>
    </td>
  </tr>
"""


def generate_offer_email_html(
    analyzed_lots: List[AnalyzedLot],
    *,
    criteria: Optional[ClientCriteria] = None,
    client_name: Optional[str] = None,
    client_email: Optional[str] = None,
    tracking_url: Optional[str] = None,
) -> str:
    offer_lots = [item for item in analyzed_lots if item.included_in_report]
    subject = build_client_offer_subject(criteria, offer_lots)
    query = _search_label(criteria, offer_lots)
    generated_at = datetime.now().strftime("%d.%m.%Y %H:%M")
    greeting = _client_greeting(client_name)

    if offer_lots:
        car_blocks = "\n".join(_car_block(item, index + 1) for index, item in enumerate(offer_lots))
        intro = (
            f"Przygotowaliśmy ranking {len(offer_lots)} wybranych ofert spełniających aktualne kryteria. "
            "Każda pozycja wymaga końcowego potwierdzenia dokumentów, zdjęć, opłat aukcyjnych i limitu licytacji."
        )
    else:
        car_blocks = """
  <tr>
    <td style="padding:0 30px 24px 30px;">
      <div style="background:#fff8e6;border:1px solid #f4d27a;border-radius:10px;padding:16px;color:#7a4f00;">
        Na ten moment nie mamy auta, które można uczciwie pokazać jako rekomendację. Warto poszerzyć kryteria albo poczekać na kolejne aukcje.
      </div>
    </td>
  </tr>
"""
        intro = "Nie znaleźliśmy obecnie ofert, które warto wysłać jako rekomendacje."

    tracking_button = ""
    if tracking_url:
        tracking_button = f"""
        <p style="margin:16px 0 0 0;">
          <a href="{_attr(tracking_url)}"
             style="display:inline-block;background:#163b66;color:#ffffff;text-decoration:none;padding:10px 14px;border-radius:6px;font-weight:700;">
            Sprawdź status zapytania
          </a>
        </p>
"""

    return f"""<!doctype html>
<html lang="pl">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{_text(subject)}</title>
</head>
<body style="margin:0;padding:0;background:#eef2f7;color:#111827;font-family:Arial,Helvetica,sans-serif;">
  <span style="display:none!important;visibility:hidden;opacity:0;color:transparent;height:0;width:0;overflow:hidden;">
    {_text(subject)}
  </span>
  <!-- Subject: {_text(subject)} -->
  <!-- Client email: {_text(client_email) if client_email else 'brak danych'} -->
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#eef2f7;margin:0;padding:24px 0;">
    <tr>
      <td align="center">
        <table role="presentation" width="720" cellspacing="0" cellpadding="0"
               style="width:720px;max-width:100%;background:#ffffff;border-radius:14px;overflow:hidden;">
          <tr>
            <td style="background:#163b66;color:#ffffff;padding:28px 30px;">
              <div style="font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:#b9d6ff;font-weight:700;">
                USA Car Finder
              </div>
              <h1 style="font-size:26px;line-height:1.2;margin:8px 0 8px 0;">Oferta aut z USA</h1>
              <p style="font-size:15px;line-height:1.5;margin:0;color:#dbeafe;">{_text(greeting)}</p>
              <p style="font-size:15px;line-height:1.5;margin:8px 0 0 0;color:#dbeafe;">{_text(intro)}</p>
              <p style="font-size:13px;line-height:1.5;margin:12px 0 0 0;color:#b9d6ff;">
                Zapytanie: {_text(query)}<br>
                Wygenerowano: {_text(generated_at)}
              </p>
              {tracking_button}
            </td>
          </tr>
          <tr>
            <td style="padding:18px 30px;background:#ffffff;border-bottom:1px solid #e6e8ee;">
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0">
                <tr>
                  <td style="background:#f8fafc;border-radius:10px;padding:14px;text-align:center;">
                    <div style="font-size:24px;font-weight:800;color:#163b66;">{len(offer_lots)}</div>
                    <div style="font-size:11px;text-transform:uppercase;color:#667085;">oferty w mailu</div>
                  </td>
                  <td width="10"></td>
                  <td style="background:#f8fafc;border-radius:10px;padding:14px;text-align:center;">
                    <div style="font-size:24px;font-weight:800;color:#163b66;">{sum(1 for x in offer_lots if x.analysis.recommendation == 'POLECAM')}</div>
                    <div style="font-size:11px;text-transform:uppercase;color:#667085;">rekomendacje</div>
                  </td>
                  <td width="10"></td>
                  <td style="background:#f8fafc;border-radius:10px;padding:14px;text-align:center;">
                    <div style="font-size:24px;font-weight:800;color:#9a3412;">{sum(1 for x in offer_lots if x.analysis.recommendation == 'RYZYKO')}</div>
                    <div style="font-size:11px;text-transform:uppercase;color:#667085;">warunkowo</div>
                  </td>
                </tr>
              </table>
            </td>
          </tr>
          {car_blocks}
          <tr>
            <td style="padding:18px 30px 28px 30px;background:#ffffff;">
              <div style="background:#fff8e6;border:1px solid #f4d27a;border-radius:10px;padding:14px;color:#7a4f00;font-size:13px;line-height:1.5;">
                Ceny i koszty są szacunkowe i mogą zmienić się w trakcie licytacji. Przed zakupem trzeba potwierdzić VIN, tytuł,
                zdjęcia wysokiej rozdzielczości, poduszki SRS, klucze, opłaty aukcyjne, transport oraz maksymalny limit bid.
              </div>
              <p style="margin:18px 0 0 0;color:#667085;font-size:13px;line-height:1.5;text-align:center;">
                Pytania? Odpowiedz na tego maila lub skontaktuj się bezpośrednio.
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""


def generate_email_html(analyzed_lots: List[AnalyzedLot], client_name: str = "Kliencie") -> str:
    """Zgodność wsteczna ze starszą nazwą funkcji."""
    return generate_offer_email_html(analyzed_lots, client_name=client_name)


def write_offer_email_html(
    analyzed_lots: List[AnalyzedLot],
    *,
    criteria: Optional[ClientCriteria] = None,
    client_name: Optional[str] = None,
    client_email: Optional[str] = None,
    tracking_url: Optional[str] = None,
    output_filename: Optional[str] = None,
) -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    if not output_filename:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_filename = f"mail_oferta_{ts}.html"

    output_path = REPORTS_DIR / output_filename
    html = generate_offer_email_html(
        analyzed_lots,
        criteria=criteria,
        client_name=client_name,
        client_email=client_email,
        tracking_url=tracking_url,
    )
    output_path.write_text(html, encoding="utf-8")
    print(f"[Report] Mail HTML zapisany: {output_path}")
    return output_path
