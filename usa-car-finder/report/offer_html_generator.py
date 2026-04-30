"""
Generator profesjonalnej oferty HTML dla klienta.
- TOP 5 rekomendacji (wybrane przez AI)
- Lista do 10 (do ręcznego doboru)
Używany zarówno jako podgląd Telegram jak i treść maila.
"""
from datetime import datetime
from typing import List
from parser.models import AnalyzedLot
from pricing.import_calculator import calculate_lot_import_costs, format_percent, format_pln, format_usd


_STYLES = """
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: Arial, Helvetica, sans-serif;
    background: #eef2f7;
    color: #111827;
    font-size: 15px;
    line-height: 1.6;
  }
  .wrapper {
    max-width: 760px;
    margin: 0 auto;
    padding: 24px 16px;
  }

  /* ─── HEADER ─── */
  .header {
    background: #163b66;
    border-radius: 14px 14px 0 0;
    padding: 28px 30px;
    color: white;
  }
  .header-logo {
    font-size: 12px;
    letter-spacing: .08em;
    text-transform: uppercase;
    color: #b9d6ff;
    font-weight: 700;
    margin-bottom: 6px;
  }
  .header h1 {
    font-size: 26px;
    font-weight: 800;
    margin-bottom: 6px;
    line-height: 1.2;
  }
  .header-sub {
    font-size: 15px;
    color: #dbeafe;
    line-height: 1.5;
  }
  .header-date {
    margin-top: 12px;
    font-size: 12px;
    color: #b9d6ff;
  }

  /* ─── STATS BAR ─── */
  .stats-bar {
    background: white;
    padding: 20px 30px;
    display: flex;
    gap: 10px;
    flex-wrap: wrap;
    border-bottom: 1px solid #e6e8ee;
  }
  .stat-card {
    flex: 1;
    min-width: 100px;
    background: #f8fafc;
    border-radius: 10px;
    padding: 14px;
    text-align: center;
  }
  .stat-num { font-size: 24px; font-weight: 800; }
  .stat-label { font-size: 11px; text-transform: uppercase; color: #667085; margin-top: 2px; }
  .stat-green .stat-num { color: #163b66; }
  .stat-yellow .stat-num { color: #9a3412; }
  .stat-red .stat-num { color: #cf222e; }
  .stat-blue .stat-num { color: #163b66; }

  /* ─── NOTICE ─── */
  .notice {
    background: #fff8e6;
    border: 1px solid #f4d27a;
    border-radius: 10px;
    padding: 12px 14px;
    margin: 16px 30px;
    font-size: 13px;
    line-height: 1.5;
    color: #7a4f00;
  }

  /* ─── SECTION TITLE ─── */
  .section-title {
    font-size: 12px;
    font-weight: 700;
    letter-spacing: .08em;
    text-transform: uppercase;
    color: #163b66;
    margin: 24px 30px 12px;
    padding-left: 12px;
    border-left: 4px solid #163b66;
  }

  /* ─── CAR CARD ─── */
  .car-card {
    background: white;
    border-radius: 12px;
    overflow: hidden;
    border: 1px solid #e6e8ee;
    margin: 0 0 18px 0;
  }
  .car-card.top-pick { border-color: #163b66; border-width: 2px; }

  .car-photo {
    width: 100%;
    height: 190px;
    object-fit: cover;
    display: block;
  }
  .car-photo-placeholder {
    width: 100%;
    height: 190px;
    background: #f0f4f8;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 13px;
    color: #999;
  }

  .car-body { padding: 18px 20px 16px; }

  .car-meta-top {
    font-size: 12px;
    color: #667085;
    font-weight: 700;
    letter-spacing: .03em;
    text-transform: uppercase;
  }
  .car-name {
    font-size: 20px;
    line-height: 1.25;
    color: #111827;
    font-weight: 800;
    margin: 4px 0;
  }
  .car-location {
    font-size: 13px;
    color: #667085;
    margin-bottom: 14px;
  }

  .car-head-row {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: 10px;
    flex-wrap: wrap;
    margin-bottom: 14px;
  }

  .badge {
    display: inline-block;
    border-radius: 999px;
    padding: 7px 12px;
    font-size: 12px;
    font-weight: 800;
    white-space: nowrap;
  }
  .badge-green { background: #e8f5e9; color: #1b5e20; }
  .badge-yellow { background: #fff8e1; color: #8a5a00; }
  .badge-orange { background: #fff3e0; color: #9a3412; }
  .badge-red { background: #fde8e8; color: #cf222e; }
  .badge-score { font-size: 12px; color: #667085; margin-top: 6px; text-align: right; }

  .stats-grid {
    display: grid;
    grid-template-columns: 1fr 12px 1fr;
    gap: 0 0;
    margin-bottom: 14px;
  }
  .stats-row { display: contents; }
  .stats-spacer-row { height: 10px; display: contents; }
  .stats-spacer-row .spacer { height: 10px; grid-column: 1 / -1; }

  .info-cell {
    background: #f8fafc;
    border-radius: 8px;
    padding: 8px 10px;
  }
  .info-cell-gap { background: transparent; }
  .info-label { font-size: 11px; color: #667085; text-transform: uppercase; margin-bottom: 2px; }
  .info-value { font-size: 14px; color: #111827; font-weight: 700; }

  .description-box {
    background: #f9fbff;
    border-left: 4px solid #244c8f;
    border-radius: 0 8px 8px 0;
    padding: 12px 14px;
    margin-bottom: 14px;
    font-size: 14px;
    color: #344054;
    line-height: 1.5;
  }

  .cost-summary {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 12px 0 14px;
    border-top: 1px solid #e6e8ee;
    margin-top: 12px;
  }
  .cost-label { font-size: 14px; color: #667085; }
  .cost-total { font-size: 20px; font-weight: 800; color: #111827; }

  .cost-details {
    background: #f8fafc;
    border-radius: 8px;
    padding: 12px 14px;
    margin-bottom: 14px;
    font-size: 13px;
    color: #4a5568;
  }
  .cost-detail-row {
    display: flex;
    justify-content: space-between;
    padding: 4px 0;
    border-bottom: 1px solid #e8edf2;
  }
  .cost-detail-row:last-child { border-bottom: none; }
  .cost-detail-bold {
    font-weight: 700;
    color: #111827;
    font-size: 14px;
    padding-top: 8px;
    margin-top: 4px;
  }

  .flags-box {
    background: #fff8e6;
    border-left: 4px solid #e6a817;
    border-radius: 0 8px 8px 0;
    padding: 10px 14px;
    margin-bottom: 14px;
    font-size: 13px;
    color: #7a4f00;
  }
  .flags-box ul { padding-left: 16px; margin-top: 4px; }
  .flags-box li { margin-bottom: 3px; }

  .auction-btn {
    display: inline-block;
    background: #244c8f;
    color: white;
    text-decoration: none;
    padding: 10px 14px;
    border-radius: 8px;
    font-size: 14px;
    font-weight: 700;
  }

  /* ─── COMPACT LIST ─── */
  .compact-card {
    background: white;
    border-radius: 10px;
    border: 1px solid #e6e8ee;
    padding: 14px 20px;
    margin-bottom: 12px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    flex-wrap: wrap;
    gap: 8px;
  }
  .compact-name { font-size: 16px; font-weight: 700; color: #111827; }
  .compact-sub { font-size: 12px; color: #667085; margin-top: 2px; }
  .compact-right { text-align: right; }
  .compact-price { font-size: 18px; font-weight: 800; color: #163b66; }
  .compact-score { font-size: 12px; color: #667085; }

  /* ─── DISCLAIMER ─── */
  .disclaimer {
    background: #fff8e6;
    border: 1px solid #f4d27a;
    border-radius: 10px;
    padding: 16px 20px;
    margin: 24px 0;
    font-size: 13px;
    color: #7a4f00;
  }
  .disclaimer ul { padding-left: 18px; margin-top: 6px; }
  .disclaimer li { margin-bottom: 4px; }

  /* ─── FOOTER ─── */
  .footer {
    text-align: center;
    margin-top: 32px;
    padding-top: 20px;
    border-top: 2px solid #e8edf2;
    font-size: 13px;
    color: #888;
  }
  .footer a { color: #163b66; text-decoration: none; }
</style>
"""


def _badge(recommendation: str) -> str:
    mapping = {
        "POLECAM":  ("badge-green",  "✅ POLECAMY"),
        "RYZYKO":   ("badge-yellow", "⚠️ WARUNKOWO"),
        "ODRZUĆ":  ("badge-red",   "❌ NIE POLECAMY"),
    }
    cls, label = mapping.get(recommendation, ("badge-green", recommendation))
    return f'<span class="badge {cls}">{label}&nbsp;&nbsp;'


def _score_label(score: float) -> str:
    if score >= 8:
        return f'<span style="color:#1a7f37;font-weight:700;">{score:.1f}/10</span>'
    elif score >= 6:
        return f'<span style="color:#9a6700;font-weight:700;">{score:.1f}/10</span>'
    else:
        return f'<span style="color:#cf222e;font-weight:700;">{score:.1f}/10</span>'


def _car_card(item: AnalyzedLot, rank: int, is_top: bool = True) -> str:
    lot = item.lot
    ai = item.analysis
    desc = (ai.client_description_pl or "").replace("NAJLEPSZA OPCJA", "Dobra opcja") \
                                          .replace("IDEALNIE", "Odpowiednio")

    top_class = "top-pick" if is_top else ""
    rank_label = f"#{rank} REKOMENDACJA" if is_top else f"#{rank} Z LISTY"

    odometer = f"{lot.odometer_mi:,} mi ({lot.odometer_km:,} km)" if lot.odometer_mi else "—"
    damage = lot.damage_primary or "—"
    title = lot.title_type or "—"
    airbags = "⚠️ ODPALONE" if lot.airbags_deployed else "✓ OK"
    auction_date = lot.auction_date[:10] if lot.auction_date else "—"
    keys = "✓ Tak" if lot.keys else ("✗ Brak" if lot.keys is False else "—")
    seller = (lot.seller_type or "—").capitalize()

    bid = f"${lot.current_bid_usd:,.0f}" if lot.current_bid_usd else "—"
    repair = f"${ai.estimated_repair_usd:,}" if ai.estimated_repair_usd else "—"
    total = f"${ai.estimated_total_cost_usd:,}" if ai.estimated_total_cost_usd else "—"
    costs = calculate_lot_import_costs(lot)

    if costs:
        excise = format_percent(costs["excise_rate"])
        costs_html = f"""
      <div class="cost-row"><span>Aktualna oferta aukcyjna</span><span>{format_usd(costs["bid_usd"])}</span></div>
      <div class="cost-row"><span>Prowizja aukcyjna 8%</span><span>{format_usd(costs["auction_fee_usd"])}</span></div>
      <div class="cost-row"><span>Towing</span><span>{format_usd(costs["towing_usd"])}</span></div>
      <div class="cost-row"><span>Suma USA</span><span>{format_usd(costs["usa_total_usd"])}</span></div>
      <div class="cost-row cost-total"><span>Osoba prywatna z akcyzą {excise}</span><span>{format_pln(costs["private_total_pln"])}</span></div>
      <div class="cost-row cost-total"><span>Firma brutto z akcyzą {excise}</span><span>{format_pln(costs["company_gross_pln"])}</span></div>
      <div class="cost-row"><span>Prowizja 1800 + 2% brutto</span><span>{format_pln(costs["broker_basic_gross_pln"])}</span></div>
      <div class="cost-row"><span>Prowizja 3600 + 4% brutto</span><span>{format_pln(costs["broker_premium_gross_pln"])}</span></div>
      <div class="cost-row"><span>Pracownik - wariant 1</span><span>{format_pln(costs["employee_basic_pln"])}</span></div>
      <div class="cost-row"><span>Pracownik - wariant 2</span><span>{format_pln(costs["employee_premium_pln"])}</span></div>
      <div class="cost-row"><span>Szacowany koszt naprawy</span><span>{repair}</span></div>
"""
    else:
        costs_html = f"""
      <div class="cost-row"><span>Aktualna oferta aukcyjna</span><span>{bid}</span></div>
      <div class="cost-row"><span>Szacowany koszt naprawy</span><span>{repair}</span></div>
      <div class="cost-row"><span>Transport (USA→PL)</span><span>~$1,400–1,600</span></div>
      <div class="cost-row cost-total"><span>CAŁKOWITY KOSZT SZACUNKOWY</span><span>{total}</span></div>
"""

    flags_html = ""
    if ai.red_flags:
        flags_html = '<div class="flags-box"><strong>⚠️ Uwagi:</strong><ul>'
        for flag in ai.red_flags[:4]:
            flags_html += f"<li>{flag}</li>"
        flags_html += "</ul></div>"

    link_btn = f'<a href="{lot.url}" class="auction-btn">🔗 Zobacz aukcję →</a>' if lot.url else ""

    return f"""
<div class="car-card {top_class}">
  <div class="car-card-header">
    <div>
      <div class="car-rank">{rank_label}</div>
      <div class="car-name">{lot.year or '?'} {lot.make or ''} {lot.model or ''} {lot.trim or ''}</div>
      <div class="car-meta">{lot.source.upper()} · Lot {lot.lot_id} · {lot.location_city or ''}, {lot.location_state or ''} · Aukcja: {auction_date}</div>
    </div>
    <div>
      {_badge(ai.recommendation)}{_score_label(ai.score)}</span>
    </div>
  </div>
  <div class="car-body">
    <div class="car-grid">
      <div class="info-box"><div class="info-box-label">Przebieg</div><div class="info-box-value">{odometer}</div></div>
      <div class="info-box"><div class="info-box-label">Uszkodzenie</div><div class="info-box-value">{damage}</div></div>
      <div class="info-box"><div class="info-box-label">Tytuł własności</div><div class="info-box-value">{title}</div></div>
      <div class="info-box"><div class="info-box-label">Poduszki powietrzne</div><div class="info-box-value">{airbags}</div></div>
      <div class="info-box"><div class="info-box-label">Kluczyki</div><div class="info-box-value">{keys}</div></div>
      <div class="info-box"><div class="info-box-label">Sprzedawca</div><div class="info-box-value">{seller}</div></div>
    </div>

    <div class="description-box">{desc[:400]}{'…' if len(desc) > 400 else ''}</div>

    <div class="cost-box">
{costs_html}
    </div>

    {flags_html}
    {link_btn}
  </div>
</div>
"""


def _compact_card(item: AnalyzedLot, rank: int) -> str:
    lot = item.lot
    ai = item.analysis
    bid = f"${lot.current_bid_usd:,.0f}" if lot.current_bid_usd else "—"
    costs = calculate_lot_import_costs(lot)
    total = format_pln(costs["private_total_pln"]) if costs else (f"${ai.estimated_total_cost_usd:,}" if ai.estimated_total_cost_usd else "—")
    auction_date = lot.auction_date[:10] if lot.auction_date else "—"
    damage = lot.damage_primary or "—"
    odometer = f"{lot.odometer_mi:,} mi" if lot.odometer_mi else "—"

    badge_cls = {"POLECAM": "badge-green", "RYZYKO": "badge-yellow", "ODRZUĆ": "badge-red"}.get(ai.recommendation, "badge-green")
    badge_txt = {"POLECAM": "✅", "RYZYKO": "⚠️", "ODRZUĆ": "❌"}.get(ai.recommendation, "")

    link = f'<a href="{lot.url}" style="font-size:12px;color:#1a3a5c;text-decoration:none;">🔗 Aukcja</a>' if lot.url else ""

    return f"""
<div class="compact-card">
  <div>
    <div class="compact-name">#{rank} {lot.year or '?'} {lot.make or ''} {lot.model or ''} <span class="badge {badge_cls}" style="font-size:11px;">{badge_txt} {ai.score:.1f}/10</span></div>
    <div class="compact-sub">{lot.source.upper()} · {lot.location_state or ''} · Aukcja: {auction_date} · {odometer} · {damage}</div>
  </div>
  <div class="compact-right">
    <div class="compact-price">{bid}</div>
    <div class="compact-score">Łącznie: {total}</div>
    {link}
  </div>
</div>
"""


def generate_offer_html(
    top_lots: List[AnalyzedLot],
    remaining_lots: List[AnalyzedLot],
    client_name: str = "Kliencie",
    search_query: str = "",
) -> str:
    """
    Generuje profesjonalną ofertę HTML.

    Args:
        top_lots: TOP 5 rekomendacji wybranych przez AI
        remaining_lots: Kolejne loty (do 10 łącznie) do ręcznego doboru
        client_name: Imię klienta
        search_query: Opis zapytania (np. "Toyota Camry 2019-2022, budżet $15,000")
    """
    date_str = datetime.now().strftime("%d.%m.%Y")
    total = len(top_lots) + len(remaining_lots)

    polecam_cnt = sum(1 for x in top_lots + remaining_lots if x.analysis.recommendation == "POLECAM")
    ryzyko_cnt  = sum(1 for x in top_lots + remaining_lots if x.analysis.recommendation == "RYZYKO")
    odrzuc_cnt  = sum(1 for x in top_lots + remaining_lots if x.analysis.recommendation == "ODRZUĆ")

    html = f"""<!DOCTYPE html>
<html lang="pl">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Oferta aut z USA — {date_str}</title>
  {_STYLES}
</head>
<body>
<div class="wrapper">

  <div class="header">
    <div class="header-logo">🚗 USA Car Finder</div>
    <h1>Profesjonalna oferta zakupu auta z USA</h1>
    <div class="header-sub">Witaj <strong>{client_name}</strong> — przygotowaliśmy dla Ciebie zestawienie {total} najlepszych ofert z aukcji Copart i IAAI.</div>
    {"<div class='header-sub' style='margin-top:6px;'>Zapytanie: <em>" + search_query + "</em></div>" if search_query else ""}
    <div class="header-date">📅 Data raportu: {date_str}</div>
  </div>

  <div class="stats-bar">
    <div class="stat-card stat-blue"><div class="stat-num">{total}</div><div class="stat-label">Przeanalizowane</div></div>
    <div class="stat-card stat-green"><div class="stat-num">{polecam_cnt}</div><div class="stat-label">Polecamy</div></div>
    <div class="stat-card stat-yellow"><div class="stat-num">{ryzyko_cnt}</div><div class="stat-label">Warunkowo</div></div>
    <div class="stat-card stat-red"><div class="stat-num">{odrzuc_cnt}</div><div class="stat-label">Odrzucamy</div></div>
  </div>

  <div class="section-title">⭐ TOP {len(top_lots)} REKOMENDACJI AI</div>
"""

    for i, item in enumerate(top_lots, 1):
        html += _car_card(item, i, is_top=True)

    if remaining_lots:
        html += f"""
  <div class="section-title">📋 POZOSTAŁE PROPOZYCJE (#{len(top_lots)+1}–{len(top_lots)+len(remaining_lots)})</div>
  <p style="font-size:13px;color:#666;margin-bottom:14px;">Dodatkowe opcje do samodzielnego wyboru — mogą być brane pod uwagę jeśli żadna z TOP rekomendacji nie spełnia Twoich oczekiwań.</p>
"""
        for i, item in enumerate(remaining_lots, len(top_lots) + 1):
            html += _compact_card(item, i)

    html += """
  <div class="disclaimer">
    <strong>⚠️ Ważne informacje:</strong>
    <ul>
      <li>Ceny podane w USD — mogą ulec zmianie w trakcie licytacji</li>
      <li>Koszty transportu i naprawy są <strong>szacunkowe</strong> — wymagają weryfikacji u importera</li>
      <li>Tytuł własności (Salvage/Clean) determinuje możliwość rejestracji w Polsce</li>
      <li>Wszystkie informacje wymagają weryfikacji przed dokonaniem zakupu</li>
      <li>Raport wygenerowany automatycznie — skontaktuj się z nami w razie pytań</li>
    </ul>
  </div>

  <div class="footer">
    <p><strong>USA Car Finder</strong> — Profesjonalne wyszukiwanie i import aut z USA</p>
    <p style="margin-top:8px;">Pytania? Odpowiedz na tego maila lub skontaktuj się bezpośrednio.</p>
    <p style="margin-top:12px;color:#bbb;font-size:11px;">© 2026 USA Car Finder · Raport wygenerowany automatycznie · Wszelkie prawa zastrzeżone</p>
  </div>

</div>
</body>
</html>"""

    return html
