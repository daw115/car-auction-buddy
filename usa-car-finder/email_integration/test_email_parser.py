"""
Test AI Email Parser - parsowanie parametrów z emaila.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from email_integration.email_parser import EmailParser


def test_parse_car_request():
    """Test parsowania zapytania o auto."""
    print("=== Test parsowania emaila z zapytaniem o auto ===\n")

    parser = EmailParser()

    # Przykładowy email od klienta
    email_body = """
    Dzień dobry,

    Szukam Toyoty Camry z lat 2018-2020, budżet do 12000 USD.
    Przebieg maksymalnie 100 000 mil.
    Nie interesują mnie auta po powodzi ani pożarze.

    Pozdrawiam,
    Jan Kowalski
    jan.kowalski@example.com
    """

    print("Treść emaila:")
    print(email_body)
    print("\n" + "="*50 + "\n")

    criteria = parser.parse_email(email_body, sender_email="jan.kowalski@example.com")

    if criteria:
        print("✅ Wyciągnięte parametry:")
        print(f"  Marka: {criteria.make}")
        print(f"  Model: {criteria.model}")
        print(f"  Rocznik: {criteria.year_from}-{criteria.year_to}")
        print(f"  Budżet: ${criteria.budget_usd}")
        print(f"  Max przebieg: {criteria.max_odometer_mi} mil")
        print(f"  Wykluczone uszkodzenia: {criteria.excluded_damage_types}")
        print(f"  Email klienta: {criteria.client_email}")
        print(f"  Imię klienta: {criteria.client_name}")
    else:
        print("❌ Nie udało się sparsować emaila")


def test_parse_non_car_email():
    """Test parsowania emaila niezwiązanego z autami."""
    print("\n\n=== Test parsowania emaila niezwiązanego z autami ===\n")

    parser = EmailParser()

    email_body = """
    Hi,
    Welcome to Google. Your new account comes with access to Google products.
    """

    print("Treść emaila:")
    print(email_body)
    print("\n" + "="*50 + "\n")

    criteria = parser.parse_email(email_body)

    if criteria is None:
        print("✅ Poprawnie rozpoznano, że email nie dotyczy wyszukiwania auta")
    else:
        print("❌ Błędnie sparsowano email jako zapytanie o auto")


if __name__ == "__main__":
    test_parse_car_request()
    test_parse_non_car_email()
