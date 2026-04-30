# Przykłady maili HTML

Przykłady zostały wygenerowane na podstawie helperów z:

- `backend/services/email_templates.py`
- `backend/services/gmail.py`

## Gotowe pliki do podglądu

- `przyklad_mail_potwierdzenie_formularza.html` - mail potwierdzający przyjęcie formularza z linkiem statusu.
- `przyklad_mail_oferta_toyota_camry.html` - mail ofertowy dla klienta szukającego Toyota Camry, z trzema rekomendowanymi autami.
- `przyklad_mail_oferta_bmw_x5.html` - drugi wariant maila ofertowego dla BMW X5, pokazujący uniwersalność szablonu.
- `przyklad_mail_brak_rekomendacji.html` - przypadek, gdy nie ma jeszcze rankingowanych ofert.
- `mail_do_klienta_oferta_template.html` - statyczny szablon z placeholderami typu `{{ client_first_name }}`.

## Przykład użycia w kodzie

```python
from backend.services.email_templates import (
    build_client_offer_email_html,
    build_client_offer_subject,
    build_tracking_email_html,
)
from backend.services.gmail import send_email


track_url = f"{PUBLIC_FORM_BASE_URL}/track/{inquiry.id}/{inquiry.tracking_token}"

# 1. Mail po formularzu
tracking_html = build_tracking_email_html(inquiry.client_name, track_url)
send_email(
    inquiry.client_email,
    f"Potwierdzenie zapytania #{inquiry.id} - AutoScout US",
    tracking_html,
)

# 2. Mail z ofertą
subject = build_client_offer_subject(inquiry, listings)
offer_html = build_client_offer_email_html(inquiry, listings, tracking_url=track_url)
send_email(inquiry.client_email, subject, offer_html)
```

## Dane wymagane przez mail ofertowy

Mail bierze dane z `Inquiry`:

- `client_name`
- `client_email`
- `make`
- `model`
- `year_from`
- `year_to`
- `budget_pln`
- `mileage_max`
- `damage_tolerance`

Oraz z rankingowanych `Listing`:

- `recommended_rank`
- `excluded`
- `source_url`
- `source`
- `year`
- `make`
- `model`
- `mileage`
- `damage_primary`
- `damage_secondary`
- `location`
- `current_bid_usd`
- `buy_now_usd`
- `ai_damage_score`
- `ai_repair_estimate_usd_low`
- `ai_repair_estimate_usd_high`
- `ai_notes`
- `total_cost_pln`

Do maila trafiają tylko listingi, które nie są `excluded` i mają ustawiony `recommended_rank`.
