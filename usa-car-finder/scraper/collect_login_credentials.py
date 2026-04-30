"""
Lokalny helper do zapisania danych logowania Copart/IAAI w .env.

Nie wypisuje haseł na ekran. Wartości są zapisywane lokalnie jako tekst jawny,
więc plik .env dostaje uprawnienia 600.
"""

from getpass import getpass
from pathlib import Path
import os
import sys


ENV_PATH = Path(".env")
FIELDS = (
    ("Copart", "COPART"),
    ("IAAI", "IAAI"),
)


def read_values() -> dict[str, str]:
    print("Dane zostana zapisane lokalnie w .env jako tekst jawny.")
    print("Nie wpisuj ich w czacie. Puste pole oznacza: zostaw bez zmian.\n")

    values: dict[str, str] = {}
    for site, prefix in FIELDS:
        login = input(f"{site} email/login: ").strip()
        password = getpass(f"{site} password (ukryte): ").strip()
        if login:
            values[f"{prefix}_EMAIL"] = login
        if password:
            values[f"{prefix}_PASSWORD"] = password
        print()
    return values


def update_env(values: dict[str, str]) -> None:
    lines = ENV_PATH.read_text(encoding="utf-8").splitlines() if ENV_PATH.exists() else []
    updated: set[str] = set()
    output: list[str] = []

    for line in lines:
        if not line or line.lstrip().startswith("#") or "=" not in line:
            output.append(line)
            continue

        key = line.split("=", 1)[0].strip()
        if key in values:
            output.append(f"{key}={values[key]}")
            updated.add(key)
        else:
            output.append(line)

    if output and output[-1] != "":
        output.append("")

    for key, value in values.items():
        if key not in updated:
            output.append(f"{key}={value}")

    ENV_PATH.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")
    os.chmod(ENV_PATH, 0o600)


def main() -> None:
    if "--stdin" in sys.argv:
        raw_values = [line.rstrip("\n") for line in sys.stdin.readlines()]
        while len(raw_values) < 4:
            raw_values.append("")
        copart_login, copart_password, iaai_login, iaai_password = raw_values[:4]
        values = {
            key: value.strip()
            for key, value in {
                "COPART_EMAIL": copart_login,
                "COPART_PASSWORD": copart_password,
                "IAAI_EMAIL": iaai_login,
                "IAAI_PASSWORD": iaai_password,
            }.items()
            if value.strip()
        }
    else:
        values = read_values()

    if not values:
        print("Nie podano zadnych wartosci, .env bez zmian.")
        return

    update_env(values)
    print("Zapisano zmienne:", ", ".join(values.keys()))
    print("Uprawnienia .env ustawione na 600.")


if __name__ == "__main__":
    main()
