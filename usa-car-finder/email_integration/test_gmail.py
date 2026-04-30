"""
Test Gmail client - pobieranie i wysyłanie emaili.
"""
import sys
from pathlib import Path

# Dodaj katalog główny do PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent.parent))

from email_integration.gmail_client import GmailClient


def test_fetch_emails():
    """Test pobierania nieprzeczytanych emaili."""
    print("=== Test pobierania emaili ===")

    try:
        client = GmailClient()
        print(f"Połączono z kontem: {client.email_address}")

        # Pobierz nieprzeczytane emaile
        emails = client.fetch_unread_emails(limit=5)

        print(f"\nZnaleziono {len(emails)} nieprzeczytanych emaili:")

        for email in emails:
            print(f"\n--- Email ID: {email.id} ---")
            print(f"Od: {email.sender}")
            print(f"Temat: {email.subject}")
            print(f"Data: {email.date}")
            print(f"Treść (pierwsze 200 znaków):\n{email.body[:200]}...")

    except Exception as e:
        print(f"Błąd: {e}")


def test_send_email():
    """Test wysyłania emaila."""
    print("\n=== Test wysyłania emaila ===")

    try:
        client = GmailClient()

        # Wyślij testowy email do siebie
        client.send_email(
            to=client.email_address,
            subject="Test USA Car Finder - Email Integration",
            body="To jest testowy email z systemu automatyzacji USA Car Finder.\n\nJeśli widzisz tę wiadomość, integracja Gmail działa poprawnie!",
            html=False
        )

        print("Email wysłany pomyślnie!")

    except Exception as e:
        print(f"Błąd: {e}")


if __name__ == "__main__":
    print("UWAGA: Przed uruchomieniem ustaw w .env:")
    print("- GMAIL_ADDRESS=twoj_email@gmail.com")
    print("- GMAIL_APP_PASSWORD=twoje_haslo_aplikacji")
    print("\nAby wygenerować hasło aplikacji:")
    print("1. Przejdź do https://myaccount.google.com/security")
    print("2. Włącz weryfikację dwuetapową (2FA)")
    print("3. Wygeneruj hasło aplikacji dla 'Poczta'")
    print("\n" + "="*50 + "\n")

    # Test pobierania
    test_fetch_emails()

    # Test wysyłania
    # test_send_email()  # Odkomentuj aby przetestować wysyłanie
