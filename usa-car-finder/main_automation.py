"""
Main Automation Orchestrator — pełny pipeline:
  1. Parsuj email klienta
  2. Scrapy Copart + IAAI z filtrem daty aukcji (12h do 5 dni)
  3. Analiza AI → TOP 5 + lista do 10
  4. Generuj profesjonalną ofertę HTML
  5. Wyślij na Telegram → czekaj na /approve
  6. Wyślij email HTML do klienta
"""
import os
import sys
import asyncio
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, str(Path(__file__).parent))

from email_integration.gmail_client import GmailClient
from email_integration.email_parser import EmailParser
from scraper.automated_scraper import AutomatedScraper
from parser.models import ClientCriteria
from ai.analyzer import analyze_lots
from report.offer_agent import generate_offers_with_agent
from telegram import TelegramBot

# ─── Konfiguracja ────────────────────────────────────────────────
CLIENT_EMAIL = os.getenv("CLIENT_EMAIL", os.getenv("GMAIL_ADDRESS", ""))
# Okno aukcji do filtrowania (godziny). None = brak filtru.
# Dostępne: 12, 24, 48, 120 (5 dni)
DEFAULT_AUCTION_WINDOW_HOURS: Optional[int] = int(os.getenv("MAX_AUCTION_WINDOW_HOURS", "120"))
DEFAULT_AUCTION_WINDOW_MIN_HOURS: int = 12
ORCHESTRATOR_MAX_RESULTS = int(os.getenv("ORCHESTRATOR_MAX_RESULTS", "10"))


class AutomationOrchestrator:
    """Główny orkiestrator automatyzacji."""

    def __init__(self):
        self.gmail_client = GmailClient()
        self.email_parser = EmailParser()
        self.scraper = AutomatedScraper()
        self.telegram_bot = TelegramBot()

    # ──────────────────────────────────────────────────────────────
    # GŁÓWNA METODA
    # ──────────────────────────────────────────────────────────────

    async def process_email(self, email_msg, auction_window_hours: Optional[int] = DEFAULT_AUCTION_WINDOW_HOURS):
        """Przetwarza pojedynczy email i uruchamia pełny pipeline."""
        sep = "=" * 60
        print(f"\n{sep}")
        print(f"[Orchestrator] Email: {email_msg.subject}")
        print(f"[Orchestrator] Od: {email_msg.sender}")
        print(f"{sep}\n")

        try:
            # ── 1. PARSOWANIE EMAILA ──────────────────────────────
            print("[1/6] Parsowanie emaila przez AI...")
            criteria_data = self.email_parser.parse_email(
                email_msg.body,
                sender_email=email_msg.sender
            )
            if not criteria_data:
                print("  ❌ Email nie zawiera zapytania o auto — pomijam")
                return

            criteria = ClientCriteria(
                make=criteria_data.make,
                model=criteria_data.model,
                year_from=criteria_data.year_from,
                year_to=criteria_data.year_to,
                budget_usd=criteria_data.budget_usd or 15_000,
                max_odometer_mi=criteria_data.max_odometer_mi or 100_000,
                max_results=ORCHESTRATOR_MAX_RESULTS,
                sources=["copart", "iaai"],
                excluded_damage_types=criteria_data.excluded_damage_types or ["Flood", "Fire"],
            )

            client_name  = criteria_data.client_name or "Kliencie"
            client_email = criteria_data.client_email or CLIENT_EMAIL
            search_query = (
                f"{criteria.make} {criteria.model or ''} "
                f"{criteria.year_from or ''}–{criteria.year_to or ''}, "
                f"budżet ${criteria.budget_usd:,.0f}"
            ).strip()

            print(f"  ✅ Marka: {criteria.make} {criteria.model or ''} | Budżet: ${criteria.budget_usd:,.0f}")
            print(f"  ✅ Klient: {client_name} ({client_email})")

            # ── 2. SCRAPING Z FILTREM DATY ────────────────────────
            window_label = (
                f"{DEFAULT_AUCTION_WINDOW_MIN_HOURS}h–{auction_window_hours}h"
                if auction_window_hours
                else "bez limitu"
            )
            print(f"\n[2/6] Scrapuję Copart + IAAI (okno aukcji: {window_label})...")
            all_lots = await self.scraper.search_cars(
                criteria,
                auction_window_hours=auction_window_hours,
                min_auction_window_hours=DEFAULT_AUCTION_WINDOW_MIN_HOURS,
            )

            if not all_lots:
                msg = f"Nie znaleziono aut dla: {search_query} (okno: {window_label})"
                print(f"  ❌ {msg}")
                await self.telegram_bot.send_error_notification(msg)
                return

            print(f"  ✅ Znaleziono {len(all_lots)} lotów po filtrowaniu")

            # ── 3. ANALIZA AI → TOP 5 + LISTA DO 10 ──────────────
            print("\n[3/6] Analiza AI i wybór TOP 5...")
            top_5, all_results = analyze_lots(all_lots, criteria, top_n=5)

            # TOP 5 (is_top_recommendation=True)
            top_lots = [r for r in all_results if r.is_top_recommendation][:5]
            # Pozostałe (do 5 dodatkowych = łącznie max 10)
            remaining_lots = [r for r in all_results if not r.is_top_recommendation][:5]

            print(f"  ✅ TOP {len(top_lots)} wybranych | {len(remaining_lots)} dodatkowych")

            # ── 4. GENEROWANIE OFERTY HTML (AGENT) ────────────────────────
            print("\n[4/6] Generowanie oferty przez agenta (pełna + skrócona)...")
            full_html, short_html = generate_offers_with_agent(
                top_lots=top_lots,
                remaining_lots=remaining_lots,
                client_name=client_name,
                search_query=search_query,
            )

            # Zapisz obie wersje
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            reports_dir = Path(os.getenv("REPORTS_DIR", "./data/reports"))
            reports_dir.mkdir(parents=True, exist_ok=True)

            full_html_path = reports_dir / f"oferta_pelna_{timestamp}.html"
            short_html_path = reports_dir / f"oferta_krotka_{timestamp}.html"

            full_html_path.write_text(full_html, encoding="utf-8")
            short_html_path.write_text(short_html, encoding="utf-8")

            print(f"  ✅ Pełna oferta: {full_html_path}")
            print(f"  ✅ Skrócona oferta: {short_html_path}")

            # ── 5. TELEGRAM → CZEKAJ NA /approve ─────────────────
            print("\n[5/6] Wysyłam PEŁNĄ ofertę na Telegram i czekam na zatwierdzenie...")
            await self.telegram_bot.send_offer_for_approval(
                html_path=str(full_html_path),
                top_count=len(top_lots),
                total_count=len(top_lots) + len(remaining_lots),
                search_query=search_query,
                auction_window_hours=auction_window_hours,
            )
            print("  ✅ Oferta wysłana — czekam na /approve lub /reject (max 30 min)...")

            approval = await self.telegram_bot.wait_for_approval(timeout=1800)

            # ── 6. EMAIL DO KLIENTA (SKRÓCONA + PEŁNA OFERTA) ───────────────────────
            if approval == "approve":
                print("\n[6/6] ✅ Zatwierdzono — wysyłam klientowi krótki email + pełną ofertę marketingową...")

                subject = f"🚗 Oferta aut z USA — {criteria.make} {criteria.model or ''} | {datetime.now().strftime('%d.%m.%Y')}"

                self.gmail_client.send_email(
                    to=client_email,
                    subject=subject,
                    body=short_html,  # <-- SKRÓCONA wersja dla klienta
                    attachments=[str(full_html_path)],  # <-- pełna oferta marketingowa jako załącznik HTML
                    html=True,
                )

                await self.telegram_bot.send_success_notification(
                    f"Email wysłany do: {client_email}\nTemat: {subject}"
                )

                # Oznacz email jako przeczytany
                try:
                    self.gmail_client.mark_as_read(email_msg.id)
                    print("  ✅ Email źródłowy oznaczony jako przeczytany")
                except Exception:
                    pass

                print(f"\n{'='*60}")
                print("✅ PIPELINE ZAKOŃCZONY SUKCESEM")
                print(f"{'='*60}")

            elif approval == "reject":
                print("\n  ❌ Odrzucono — pipeline zakończony bez wysyłki")

            else:
                print("\n  ⏱ Timeout — brak odpowiedzi w ciągu 30 minut")
                await self.telegram_bot.send_message("⏱ Timeout — raport nie został zatwierdzony.")

        except Exception as e:
            import traceback
            print(f"\n❌ Błąd przetwarzania: {e}")
            traceback.print_exc()
            try:
                await self.telegram_bot.send_error_notification(
                    f"Błąd przetwarzania emaila od {email_msg.sender}:\n{str(e)}"
                )
            except Exception:
                pass

    # ──────────────────────────────────────────────────────────────

    async def run_once(self, auction_window_hours: Optional[int] = DEFAULT_AUCTION_WINDOW_HOURS):
        """Uruchamia jeden cykl sprawdzania emaili."""
        print("\n" + "=" * 60)
        print("🚗 USA Car Finder — Automation Orchestrator")
        print("=" * 60)

        print("\n[Orchestrator] Sprawdzam nowe emaile...")
        emails = self.gmail_client.fetch_unread_emails(limit=5)

        if not emails:
            print("  ✅ Brak nowych emaili")
            return

        print(f"  ✅ Znaleziono {len(emails)} nieprzeczytanych emaili")
        for email_msg in emails:
            await self.process_email(email_msg, auction_window_hours=auction_window_hours)

    async def run_loop(self, interval: int = 300, auction_window_hours: Optional[int] = DEFAULT_AUCTION_WINDOW_HOURS):
        """Uruchamia ciągłą pętlę sprawdzania emaili."""
        print(f"\n[Orchestrator] Pętla automatyzacji (co {interval}s, okno aukcji: {auction_window_hours}h)")

        while True:
            try:
                await self.run_once(auction_window_hours=auction_window_hours)
            except Exception as e:
                print(f"\n❌ Błąd w pętli: {e}")
                try:
                    await self.telegram_bot.send_error_notification(f"Błąd w pętli: {str(e)}")
                except Exception:
                    pass

            print(f"\n[Orchestrator] Następne sprawdzenie za {interval}s...")
            await asyncio.sleep(interval)


# ─── CLI ──────────────────────────────────────────────────────────

async def main():
    import argparse
    parser = argparse.ArgumentParser(description="USA Car Finder — Automation Pipeline")
    parser.add_argument(
        "--window", type=int, choices=[12, 24, 48, 120], default=DEFAULT_AUCTION_WINDOW_HOURS,
        help="Okno aukcji w godzinach: 12/24/48/120 (5 dni). Domyślnie: 120"
    )
    parser.add_argument(
        "--once", action="store_true",
        help="Uruchom raz i zakończ (bez pętli)"
    )
    parser.add_argument(
        "--interval", type=int, default=300,
        help="Interwał sprawdzania emaili w sekundach (domyślnie: 300)"
    )
    args = parser.parse_args()

    orchestrator = AutomationOrchestrator()

    if args.once:
        await orchestrator.run_once(auction_window_hours=args.window)
    else:
        await orchestrator.run_loop(interval=args.interval, auction_window_hours=args.window)


if __name__ == "__main__":
    asyncio.run(main())
