#!/usr/bin/env python3
"""
Kopiuje rozpakowaną wtyczkę BidWise (Eridan) z profilu Chrome do ./extensions/bidwise.

Po co: sesję Manheima trzyma wtyczka, nie ciasteczka profilu — bez niej
search.manheim.com odsyła na publiczne site.manheim.com. Playwright ładuje
rozszerzenia tylko z rozpakowanych katalogów (--load-extension), więc kopiujemy
wersję zainstalowaną ze Web Store.

Użycie:
    python scripts/sync_bidwise_extension.py                 # auto-wykrycie profilu
    python scripts/sync_bidwise_extension.py --profile ~/... # wskazany profil Chrome
    python scripts/sync_bidwise_extension.py --list          # pokaż znalezione wtyczki

Po skopiowaniu wciąż trzeba RAZ zalogować się do BidWise w profilu, którego używa
scraper (CHROME_PROFILE_DIR) — uruchom backend z USE_EXTENSIONS=true i HEADLESS=false.
"""
import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import List, Optional

EXTENSION_ID = "mapbnmkenejciggnkildgcohibbnhnmm"  # BidWise by Eridan (Chrome Web Store)
TARGET_DIR = Path(__file__).resolve().parent.parent / "extensions" / "bidwise"

DEFAULT_PROFILE_DIRS = [
    Path.home() / "Library/Application Support/Google/Chrome/Default",
    Path.home() / "Library/Application Support/Google/Chrome Beta/Default",
    Path.home() / ".config/google-chrome/Default",
    Path.home() / ".config/chromium/Default",
]


def extension_name(path: Path) -> str:
    try:
        manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    except Exception:
        return "?"

    name = manifest.get("name", "?")
    if not name.startswith("__MSG_"):
        return name
    # Zlokalizowana nazwa — manifest trzyma tylko placeholder, tekst siedzi w _locales.
    locale = manifest.get("default_locale", "en")
    messages = path / "_locales" / locale / "messages.json"
    try:
        key = name[len("__MSG_"):].rstrip("_")
        return json.loads(messages.read_text(encoding="utf-8"))[key]["message"]
    except Exception:
        return name


def newest_version_dir(extension_root: Path) -> Optional[Path]:
    versions = [item for item in extension_root.iterdir() if item.is_dir()]
    if not versions:
        return None
    # Katalogi nazywają się "<wersja>_<rewizja>" — sortowanie numeryczne po wersji.
    def key(item: Path):
        version = item.name.split("_", 1)[0]
        return tuple(int(part) if part.isdigit() else 0 for part in version.split("."))

    return sorted(versions, key=key)[-1]


def find_profiles(explicit: Optional[str]) -> List[Path]:
    if explicit:
        return [Path(explicit).expanduser()]
    return [path for path in DEFAULT_PROFILE_DIRS if (path / "Extensions").is_dir()]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", help="Katalog profilu Chrome (np. ~/Library/.../Chrome/Default)")
    parser.add_argument("--list", action="store_true", help="Wypisz wtyczki znalezione w profilu")
    args = parser.parse_args()

    profiles = find_profiles(args.profile)
    if not profiles:
        print("Nie znalazłem profilu Chrome. Podaj --profile <ścieżka>.", file=sys.stderr)
        return 1

    for profile in profiles:
        extensions_root = profile / "Extensions"
        if not extensions_root.is_dir():
            continue

        if args.list:
            print(f"[{profile}]")
            for item in sorted(extensions_root.iterdir()):
                version_dir = newest_version_dir(item) if item.is_dir() else None
                if version_dir:
                    print(f"  {item.name}  {extension_name(version_dir)}  ({version_dir.name})")
            continue

        source_root = extensions_root / EXTENSION_ID
        if not source_root.is_dir():
            continue

        source = newest_version_dir(source_root)
        if source is None:
            print(f"Brak katalogu wersji w {source_root}", file=sys.stderr)
            return 1

        if TARGET_DIR.exists():
            shutil.rmtree(TARGET_DIR)
        shutil.copytree(source, TARGET_DIR)
        # _metadata trzyma podpisy Web Store; przy --load-extension Chrome je odrzuca.
        shutil.rmtree(TARGET_DIR / "_metadata", ignore_errors=True)

        print(f"Skopiowano {extension_name(source)} {source.name} → {TARGET_DIR}")
        print("Dalej: USE_EXTENSIONS=true, HEADLESS=false, zaloguj BidWise raz w profilu scrapera.")
        return 0

    if args.list:
        return 0

    print(
        f"Nie znalazłem wtyczki {EXTENSION_ID} w profilach: "
        + ", ".join(str(path) for path in profiles),
        file=sys.stderr,
    )
    print("Uruchom z --list żeby zobaczyć co jest zainstalowane.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
