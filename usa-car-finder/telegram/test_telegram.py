"""
Test Telegram Bot - wysyłanie wiadomości i dokumentów.
"""
import sys
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from telegram import TelegramBot


async def test_send_message():
    """Test wysyłania wiadomości."""
    print("=== Test wysyłania wiadomości na Telegram ===\n")

    try:
        bot = TelegramBot()
        print(f"Bot skonfigurowany dla chat_id: {bot.chat_id}")

        # Wyślij testową wiadomość
        await bot.send_message("🚗 Test USA Car Finder - Telegram Bot działa!")

        print("✅ Wiadomość wysłana pomyślnie!")

    except Exception as e:
        print(f"❌ Błąd: {e}")


async def test_send_report():
    """Test wysyłania raportu z inline keyboard."""
    print("\n=== Test wysyłania raportu z przyciskami ===\n")

    try:
        bot = TelegramBot()

        # Symuluj raport (użyj istniejącego pliku PDF)
        report_path = "/Users/dawidslabicki/Documents/Claude/carsmillionaire/usa-car-finder/data/reports"
        pdf_files = list(Path(report_path).glob("*.pdf"))

        if not pdf_files:
            print("❌ Brak plików PDF do testu. Wygeneruj raport najpierw.")
            return

        test_pdf = str(pdf_files[0])
        print(f"Używam pliku testowego: {test_pdf}")

        # Wyślij raport z przyciskami
        await bot.send_report_link(test_pdf, lot_count=8, top_count=5)

        print("✅ Raport wysłany z inline keyboard!")
        print("\nKliknij przyciski w Telegram aby przetestować callback queries.")

    except Exception as e:
        print(f"❌ Błąd: {e}")


if __name__ == "__main__":
    print("UWAGA: Przed uruchomieniem ustaw w .env:")
    print("- TELEGRAM_BOT_TOKEN=twoj_token_bota")
    print("- TELEGRAM_CHAT_ID=twoj_chat_id")
    print("\nAby utworzyć bota:")
    print("1. Napisz do @BotFather na Telegram")
    print("2. Użyj /newbot i postępuj zgodnie z instrukcjami")
    print("3. Skopiuj token")
    print("4. Aby znaleźć chat_id, napisz do @userinfobot")
    print("\n" + "="*50 + "\n")

    # Test wysyłania wiadomości
    asyncio.run(test_send_message())

    # Test wysyłania raportu (odkomentuj aby przetestować)
    # asyncio.run(test_send_report())
