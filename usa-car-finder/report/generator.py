import os
from datetime import datetime
from pathlib import Path
from typing import List, Optional
from parser.models import AnalyzedLot
from pricing.import_calculator import calculate_lot_import_costs, format_percent, format_pln, format_usd
from dotenv import load_dotenv

load_dotenv()

REPORTS_DIR = Path(os.getenv("REPORTS_DIR", "./data/reports"))


def download_image(url: str, width: float, height: float):
    """Pobiera zdjęcie z URL i zwraca obiekt Image reportlab."""
    from reportlab.platypus import Image
    import urllib.request
    import tempfile

    if os.getenv("REPORT_DOWNLOAD_IMAGES", "false").lower() != "true":
        return None

    try:
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        timeout = float(os.getenv("REPORT_IMAGE_TIMEOUT_SECONDS", "3"))
        max_bytes = int(os.getenv("REPORT_IMAGE_MAX_BYTES", str(2 * 1024 * 1024)))
        with urllib.request.urlopen(request, timeout=timeout) as response:
            image_bytes = response.read(max_bytes + 1)
        if len(image_bytes) > max_bytes:
            return None
        with tempfile.NamedTemporaryFile(delete=False, suffix='.jpg') as tmp_file:
            tmp_file.write(image_bytes)
            return Image(tmp_file.name, width=width, height=height)
    except Exception:
        return None


def auction_link_paragraph(url: str, style):
    """Zwraca krótki klikalny link. Długie URL-e potrafią blokować layout PDF."""
    from reportlab.platypus import Paragraph
    from xml.sax.saxutils import escape, quoteattr

    href = quoteattr(url)
    label = escape("Otwórz aukcję")
    return Paragraph(f'<link href={href}><u>{label}</u></link>', style)


def create_bullet_list(items: List[str], style):
    """Tworzy listę punktowaną."""
    from reportlab.platypus import Paragraph
    result = []
    for item in items:
        result.append(Paragraph(f"• {item}", style))
    return result


def generate_comparison_table(analyzed_lots: List[AnalyzedLot], styles):
    """Generuje tabelę porównawczą wszystkich aut."""
    from reportlab.platypus import Table, TableStyle, Paragraph
    from reportlab.lib import colors
    from reportlab.lib.units import cm

    headers = [
        Paragraph('<b>Zdjęcie</b>', styles['table_header']),
        Paragraph('<b>Auto</b>', styles['table_header']),
        Paragraph('<b>Score</b>', styles['table_header']),
        Paragraph('<b>Rekomendacja</b>', styles['table_header']),
        Paragraph('<b>Przebieg</b>', styles['table_header']),
        Paragraph('<b>Uszkodzenie</b>', styles['table_header']),
        Paragraph('<b>Cena</b>', styles['table_header']),
        Paragraph('<b>Lokalizacja</b>', styles['table_header']),
        Paragraph('<b>Koszt PL</b>', styles['table_header'])
    ]

    data = [headers]

    for item in analyzed_lots:
        lot = item.lot
        ai = item.analysis

        img = None
        if lot.images and lot.images[0]:
            img = download_image(lot.images[0], width=1.8*cm, height=1.3*cm)

        costs = calculate_lot_import_costs(lot)
        calculated_total = format_pln(costs["private_total_pln"]) if costs else "—"

        row = [
            img or '',
            Paragraph(f'{lot.year or "?"} {lot.make or ""} {lot.model or ""}', styles['table_cell']),
            Paragraph(f'<b>{ai.score:.1f}</b>', styles['table_cell_center']),
            Paragraph(f'<b>{ai.recommendation}</b>', styles['table_cell_center']),
            Paragraph(f'{lot.odometer_mi or "—"} mi', styles['table_cell']),
            Paragraph(f'{lot.damage_primary or "—"}', styles['table_cell']),
            Paragraph(f'${lot.current_bid_usd or "—"}', styles['table_cell']),
            Paragraph(f'{lot.location_state or "—"}', styles['table_cell']),
            Paragraph(calculated_total, styles['table_cell'])
        ]
        data.append(row)

    col_widths = [2*cm, 4*cm, 2*cm, 2.5*cm, 2.5*cm, 3*cm, 2*cm, 2.5*cm, 2.5*cm]
    table = Table(data, colWidths=col_widths, repeatRows=1)

    table_style = [
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a3a5c')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('FONTSIZE', (0, 0), (-1, 0), 9),
        ('FONTSIZE', (0, 1), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
    ]

    for idx, item in enumerate(analyzed_lots, start=1):
        if item.analysis.recommendation == "POLECAM":
            bg_color = colors.HexColor('#d4edda')
        elif item.analysis.recommendation == "RYZYKO":
            bg_color = colors.HexColor('#fff3cd')
        else:
            bg_color = colors.HexColor('#f8d7da')
        table_style.append(('BACKGROUND', (0, idx), (-1, idx), bg_color))

    table.setStyle(TableStyle(table_style))
    return table


def generate_car_detail_page(item: AnalyzedLot, styles):
    """Generuje profesjonalną stronę A4 dla pojedynczego auta."""
    from reportlab.platypus import Paragraph, Spacer, Table, TableStyle
    from reportlab.lib import colors
    from reportlab.lib.units import cm

    lot = item.lot
    ai = item.analysis
    elements = []

    # Kolor tła według rekomendacji
    if ai.recommendation == "POLECAM":
        bg_color = colors.HexColor('#d4edda')
        badge_color = colors.HexColor('#28a745')
    elif ai.recommendation == "RYZYKO":
        bg_color = colors.HexColor('#fff3cd')
        badge_color = colors.HexColor('#ffc107')
    else:
        bg_color = colors.HexColor('#f8d7da')
        badge_color = colors.HexColor('#dc3545')

    # === NAGŁÓWEK Z TYTUŁEM I SCORE ===
    title_text = f"<b>{lot.year or '?'} {lot.make or ''} {lot.model or ''}</b>"
    score_text = f"<font size='18' color='#1a3a5c'><b>{ai.score:.1f}/10</b></font>"

    header_data = [[
        Paragraph(title_text, styles['car_title']),
        Paragraph(score_text, styles['score_big'])
    ]]
    header_table = Table(header_data, colWidths=[12*cm, 4.5*cm])
    header_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), bg_color),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ALIGN', (1, 0), (1, 0), 'CENTER'),
        ('TOPPADDING', (0, 0), (-1, -1), 12),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
        ('LEFTPADDING', (0, 0), (-1, -1), 15),
        ('RIGHTPADDING', (0, 0), (-1, -1), 15),
    ]))
    elements.append(header_table)
    elements.append(Spacer(1, 0.4*cm))

    # === BADGE REKOMENDACJI ===
    badge_table = Table([[Paragraph(f"<b>{ai.recommendation}</b>", styles['badge'])]], colWidths=[16.5*cm])
    badge_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), badge_color),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
    ]))
    elements.append(badge_table)
    elements.append(Spacer(1, 0.5*cm))

    # === ZDJĘCIE (DUŻE, WYCENTROWANE) ===
    if lot.images and lot.images[0]:
        img = download_image(lot.images[0], width=12*cm, height=8*cm)
        if img:
            img_table = Table([[img]], colWidths=[16.5*cm])
            img_table.setStyle(TableStyle([
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ]))
            elements.append(img_table)
            elements.append(Spacer(1, 0.5*cm))

    # === DANE TECHNICZNE (LISTA PUNKTOWANA) ===
    elements.append(Paragraph("<b>Dane techniczne</b>", styles['section_header']))
    elements.append(Spacer(1, 0.2*cm))

    tech_items = [
        f"<b>Źródło:</b> {lot.source.upper()} | <b>Lot ID:</b> {lot.lot_id}",
        f"<b>Przebieg:</b> {lot.odometer_mi or '—'} mil ({lot.odometer_km or '—'} km)",
        f"<b>Uszkodzenie:</b> {lot.damage_primary or '—'}",
        f"<b>Tytuł:</b> {lot.title_type or '—'}",
        f"<b>Lokalizacja:</b> {lot.location_city or ''}, {lot.location_state or ''}",
    ]

    if lot.full_vin or lot.vin:
        tech_items.append(f"<b>VIN:</b> {lot.full_vin or lot.vin}")

    tech_items.append(f"<b>Poduszki powietrzne:</b> {'ODPALONE' if lot.airbags_deployed else 'OK'}")

    for item in tech_items:
        elements.append(Paragraph(f"• {item}", styles['bullet']))

    elements.append(Spacer(1, 0.4*cm))

    # === CENY (LISTA PUNKTOWANA) ===
    elements.append(Paragraph("<b>Ceny</b>", styles['section_header']))
    elements.append(Spacer(1, 0.2*cm))

    price_items = [
        f"<b>Aktualna oferta:</b> ${lot.current_bid_usd or '—'}",
    ]

    if lot.seller_reserve_usd:
        price_items.append(f"<b>Cena rezerwowa:</b> ${lot.seller_reserve_usd}")

    if lot.seller_type:
        price_items.append(f"<b>Typ sprzedawcy:</b> {lot.seller_type}")

    for item in price_items:
        elements.append(Paragraph(f"• {item}", styles['bullet']))

    elements.append(Spacer(1, 0.4*cm))

    # === OPIS I ANALIZA ===
    elements.append(Paragraph("<b>Opis i analiza</b>", styles['section_header']))
    elements.append(Spacer(1, 0.2*cm))

    desc_box = Table([[Paragraph(ai.client_description_pl, styles['description'])]], colWidths=[16.5*cm])
    desc_box.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#f7f9fc')),
        ('TOPPADDING', (0, 0), (-1, -1), 12),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
        ('LEFTPADDING', (0, 0), (-1, -1), 15),
        ('RIGHTPADDING', (0, 0), (-1, -1), 15),
        ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#1a3a5c')),
    ]))
    elements.append(desc_box)
    elements.append(Spacer(1, 0.4*cm))

    # === KOSZTY (TABELA) ===
    elements.append(Paragraph("<b>Szacunkowe koszty</b>", styles['section_header']))
    elements.append(Spacer(1, 0.2*cm))

    costs = calculate_lot_import_costs(lot)
    if costs:
        excise = format_percent(costs["excise_rate"])
        cost_data = [
            [Paragraph('<b>Pozycja</b>', styles['table_header_small']),
             Paragraph('<b>Kwota</b>', styles['table_header_small'])],
            [Paragraph('Kwota licytacji', styles['normal']),
             Paragraph(format_usd(costs["bid_usd"]), styles['normal'])],
            [Paragraph('Prowizja aukcyjna 8%', styles['normal']),
             Paragraph(format_usd(costs["auction_fee_usd"]), styles['normal'])],
            [Paragraph('Towing', styles['normal']),
             Paragraph(format_usd(costs["towing_usd"]), styles['normal'])],
            [Paragraph('Suma USA', styles['normal']),
             Paragraph(format_usd(costs["usa_total_usd"]), styles['normal'])],
            [Paragraph(f'Osoba prywatna z akcyzą {excise}', styles['bold']),
             Paragraph(f'<b>{format_pln(costs["private_total_pln"])}</b>', styles['bold'])],
            [Paragraph(f'Firma brutto z akcyzą {excise}', styles['bold']),
             Paragraph(f'<b>{format_pln(costs["company_gross_pln"])}</b>', styles['bold'])],
            [Paragraph('Prowizja 1800 + 2% brutto', styles['normal']),
             Paragraph(format_pln(costs["broker_basic_gross_pln"]), styles['normal'])],
            [Paragraph('Prowizja 3600 + 4% brutto', styles['normal']),
             Paragraph(format_pln(costs["broker_premium_gross_pln"]), styles['normal'])],
            [Paragraph('Pracownik - wariant 1', styles['normal']),
             Paragraph(format_pln(costs["employee_basic_pln"]), styles['normal'])],
            [Paragraph('Pracownik - wariant 2', styles['normal']),
             Paragraph(format_pln(costs["employee_premium_pln"]), styles['normal'])],
            [Paragraph('Szacowana naprawa AI', styles['normal']),
             Paragraph(format_usd(ai.estimated_repair_usd) if ai.estimated_repair_usd else "—", styles['normal'])],
        ]
    else:
        cost_data = [
            [Paragraph('<b>Pozycja</b>', styles['table_header_small']),
             Paragraph('<b>Kwota</b>', styles['table_header_small'])],
            [Paragraph('Naprawa', styles['normal']),
             Paragraph(f'${ai.estimated_repair_usd or "—"}', styles['normal'])],
            [Paragraph('<b>CAŁKOWITY KOSZT</b>', styles['bold']),
             Paragraph(f'<b>${ai.estimated_total_cost_usd or "—"}</b>', styles['bold'])]
        ]

    cost_table = Table(cost_data, colWidths=[10*cm, 6.5*cm])
    cost_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a3a5c')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('BACKGROUND', (0, min(5, len(cost_data) - 1)), (-1, min(6, len(cost_data) - 1)), colors.HexColor('#f0f4f8')),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('LEFTPADDING', (0, 0), (-1, -1), 10),
        ('RIGHTPADDING', (0, 0), (-1, -1), 10),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
    ]))
    elements.append(cost_table)
    elements.append(Spacer(1, 0.4*cm))

    # === UWAGI TECHNICZNE ===
    if ai.red_flags or ai.ai_notes:
        elements.append(Paragraph("<b>Uwagi techniczne</b>", styles['section_header']))
        elements.append(Spacer(1, 0.2*cm))

        if ai.red_flags:
            elements.append(Paragraph("<b>Czerwone flagi:</b>", styles['bold']))
            for flag in ai.red_flags:
                elements.append(Paragraph(f"• {flag}", styles['warning']))
            elements.append(Spacer(1, 0.2*cm))

        if ai.ai_notes:
            notes_text = ai.ai_notes
            if len(notes_text) > 500:
                notes_text = notes_text[:500] + "..."
            elements.append(Paragraph(notes_text, styles['small']))

        elements.append(Spacer(1, 0.3*cm))

    # === LINK DO AUKCJI ===
    if lot.url:
        elements.append(auction_link_paragraph(lot.url, styles['link']))

    return elements


def generate_pdf_report(
    analyzed_lots: List[AnalyzedLot],
    output_filename: Optional[str] = None,
) -> Path:
    """Generuje profesjonalny raport PDF."""
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak, BaseDocTemplate, PageTemplate, Frame
    from reportlab.lib.units import cm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    try:
        pdfmetrics.registerFont(TTFont('ArialUnicode', '/System/Library/Fonts/Supplemental/Arial Unicode.ttf'))
        font_name = 'ArialUnicode'
    except:
        font_name = 'Helvetica'

    if not output_filename:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_filename = f"raport_{ts}.pdf"

    output_path = REPORTS_DIR / output_filename

    polecam = [x for x in analyzed_lots if x.analysis.recommendation == "POLECAM"]
    ryzyko = [x for x in analyzed_lots if x.analysis.recommendation == "RYZYKO"]
    odrzuc = [x for x in analyzed_lots if x.analysis.recommendation == "ODRZUĆ"]

    doc = BaseDocTemplate(str(output_path), pagesize=A4)

    frame_portrait = Frame(
        doc.leftMargin, doc.bottomMargin, doc.width, doc.height,
        id='portrait'
    )

    frame_landscape = Frame(
        doc.leftMargin, doc.bottomMargin,
        landscape(A4)[0] - doc.leftMargin - doc.rightMargin,
        landscape(A4)[1] - doc.topMargin - doc.bottomMargin,
        id='landscape'
    )

    template_portrait = PageTemplate(id='portrait', frames=[frame_portrait], pagesize=A4)
    template_landscape = PageTemplate(id='landscape', frames=[frame_landscape], pagesize=landscape(A4))

    doc.addPageTemplates([template_portrait, template_landscape])

    # === STYLE PROFESJONALNEGO RAPORTU ===
    styles = {
        'title': ParagraphStyle(
            'Title',
            fontName=font_name,
            fontSize=28,
            textColor=colors.HexColor('#1a3a5c'),
            alignment=TA_CENTER,
            spaceAfter=16,
            leading=34
        ),
        'subtitle': ParagraphStyle(
            'Subtitle',
            fontName=font_name,
            fontSize=12,
            textColor=colors.HexColor('#666666'),
            alignment=TA_CENTER,
            spaceAfter=24
        ),
        'section_header': ParagraphStyle(
            'SectionHeader',
            fontName=font_name,
            fontSize=12,
            textColor=colors.HexColor('#1a3a5c'),
            spaceAfter=6,
            leading=16
        ),
        'car_title': ParagraphStyle(
            'CarTitle',
            fontName=font_name,
            fontSize=16,
            textColor=colors.HexColor('#1a3a5c'),
            leading=20
        ),
        'score_big': ParagraphStyle(
            'ScoreBig',
            fontName=font_name,
            fontSize=18,
            alignment=TA_CENTER,
            leading=22
        ),
        'badge': ParagraphStyle(
            'Badge',
            fontName=font_name,
            fontSize=14,
            textColor=colors.white,
            alignment=TA_CENTER,
            leading=18
        ),
        'bullet': ParagraphStyle(
            'Bullet',
            fontName=font_name,
            fontSize=10,
            leading=16,
            leftIndent=10,
            spaceAfter=4
        ),
        'description': ParagraphStyle(
            'Description',
            fontName=font_name,
            fontSize=10,
            leading=15,
            alignment=TA_LEFT
        ),
        'normal': ParagraphStyle(
            'Normal',
            fontName=font_name,
            fontSize=10,
            leading=14
        ),
        'bold': ParagraphStyle(
            'Bold',
            fontName=font_name,
            fontSize=10,
            leading=14
        ),
        'small': ParagraphStyle(
            'Small',
            fontName=font_name,
            fontSize=9,
            textColor=colors.HexColor('#666666'),
            leading=13
        ),
        'warning': ParagraphStyle(
            'Warning',
            fontName=font_name,
            fontSize=9,
            textColor=colors.HexColor('#dc3545'),
            leading=13,
            leftIndent=10
        ),
        'link': ParagraphStyle(
            'Link',
            fontName=font_name,
            fontSize=9,
            textColor=colors.HexColor('#0066cc'),
            leading=12
        ),
        'table_header': ParagraphStyle(
            'TableHeader',
            fontName=font_name,
            fontSize=9,
            textColor=colors.white,
            alignment=TA_CENTER
        ),
        'table_header_small': ParagraphStyle(
            'TableHeaderSmall',
            fontName=font_name,
            fontSize=10,
            textColor=colors.white,
            alignment=TA_LEFT
        ),
        'table_cell': ParagraphStyle(
            'TableCell',
            fontName=font_name,
            fontSize=8,
            alignment=TA_LEFT
        ),
        'table_cell_center': ParagraphStyle(
            'TableCellCenter',
            fontName=font_name,
            fontSize=8,
            alignment=TA_CENTER
        ),
    }

    story = []

    # === STRONA 1: TYTUŁ I STATYSTYKI ===
    story.append(Spacer(1, 2*cm))
    story.append(Paragraph("Raport wyszukiwania aut z USA", styles['title']))
    story.append(Paragraph(f"Wygenerowano: {datetime.now().strftime('%d.%m.%Y %H:%M')}", styles['subtitle']))
    story.append(Spacer(1, 1*cm))

    from reportlab.platypus import Table, TableStyle
    stats_data = [
        [
            Paragraph('<b>POLECAM</b>', styles['table_header']),
            Paragraph('<b>RYZYKO</b>', styles['table_header']),
            Paragraph('<b>ODRZUĆ</b>', styles['table_header'])
        ],
        [
            Paragraph(f'<b>{len(polecam)}</b>', ParagraphStyle('StatValue', parent=styles['table_cell_center'], fontSize=20)),
            Paragraph(f'<b>{len(ryzyko)}</b>', ParagraphStyle('StatValue', parent=styles['table_cell_center'], fontSize=20)),
            Paragraph(f'<b>{len(odrzuc)}</b>', ParagraphStyle('StatValue', parent=styles['table_cell_center'], fontSize=20))
        ]
    ]
    stats_table = Table(stats_data, colWidths=[5.5*cm, 5.5*cm, 5.5*cm])
    stats_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a3a5c')),
        ('BACKGROUND', (0, 1), (0, 1), colors.HexColor('#d4edda')),
        ('BACKGROUND', (1, 1), (1, 1), colors.HexColor('#fff3cd')),
        ('BACKGROUND', (2, 1), (2, 1), colors.HexColor('#f8d7da')),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 15),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 15),
        ('GRID', (0, 0), (-1, -1), 1, colors.grey),
    ]))
    story.append(stats_table)

    # === STRONA 2: TABELA PORÓWNAWCZA (LANDSCAPE) ===
    story.append(PageBreak())
    from reportlab.platypus import NextPageTemplate
    story.append(NextPageTemplate('landscape'))

    story.append(Paragraph("<b>Tabela porównawcza wszystkich aut</b>", styles['section_header']))
    story.append(Spacer(1, 0.3*cm))
    comparison_table = generate_comparison_table(analyzed_lots, styles)
    story.append(comparison_table)

    # === STRONY 3+: KAŻDE AUTO NA JEDNEJ STRONIE A4 ===
    story.append(PageBreak())
    story.append(NextPageTemplate('portrait'))

    for idx, item in enumerate(analyzed_lots):
        if idx > 0:
            story.append(PageBreak())

        car_elements = generate_car_detail_page(item, styles)
        story.extend(car_elements)

    doc.build(story)
    print(f"[Report] Raport zapisany: {output_path}")
    return output_path
