"""
Warunki wstępne sesji Manheima — bez importu Playwrighta i przeglądarki.

Wydzielone z scraper/manheim.py, bo /api/capabilities musi umieć odpowiedzieć
"czy Manheim jest dostępny" nie dotykając Playwrighta ani stałego kontekstu
przeglądarki (kontrakt pilnowany przez tests/test_contract_preservation.py).
Tu są wyłącznie odczyty env + sprawdzenie katalogów.
"""
import json
import os
import time
from pathlib import Path
from typing import Optional

DEFAULT_EXTENSION_DIR = "./extensions/bidwise"


def extension_dir() -> Path:
    return Path(os.getenv("MANHEIM_EXTENSION_DIR", DEFAULT_EXTENSION_DIR))


def chrome_profile_dir() -> Path:
    """Własny profil, nie ten od AuctionGate/AutoHelperBota — patrz
    browser_context.launch_manheim_context()."""
    return Path(os.getenv("MANHEIM_CHROME_PROFILE_DIR", "./data/chrome_profile_manheim"))


def result_limit(requested_max_results: Optional[int] = None) -> int:
    """Ile lotów Manheim ma w ogóle oddać.

    Manheim to źródło uzupełniające (rynek dealerski, w większości auta
    nieuszkodzone), więc domyślnie oddaje TOP 3 — tyle ile broker realnie
    wstawia do oferty obok Copart/IAAI. Podniesienie: MANHEIM_MAX_RESULTS.
    """
    configured = max(1, int(os.getenv("MANHEIM_MAX_RESULTS", "3")))
    if requested_max_results:
        return max(1, min(configured, int(requested_max_results)))
    return configured


def _is_unpacked_extension(path: Path) -> bool:
    manifest = path / "manifest.json"
    if not path.is_dir() or not manifest.is_file():
        return False
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return bool(data.get("manifest_version") and data.get("name"))


def _profile_has_been_used(path: Path) -> bool:
    """Pusty katalog to nie profil — Chrome zapisuje te pliki dopiero po starcie."""
    return any(
        (path / marker).exists()
        for marker in ("Default/Preferences", "Preferences", "Local State")
    )


def cdp_url() -> str:
    return os.getenv("MANHEIM_CHROME_CDP_URL", "").strip()


def source_mode() -> str:
    return os.getenv("MANHEIM_SOURCE_MODE", "collector").strip().lower()


def collector_seen_recently() -> bool:
    """Czy rozszerzenie-kolektor odzywało się na tyle niedawno, by na nim polegać.

    W trybie kolektora to jedyny sensowny sygnał gotowości: nie ma znaczenia
    ani profil Chrome, ani CDP — liczy się to, czy po drugiej stronie stoi
    zalogowana przeglądarka, która przyjmie zlecenie.
    """
    try:
        from api.manheim_ingest import last_contact_at
    except Exception:
        return False

    last = last_contact_at()
    if not last:
        return False
    window = max(60.0, float(os.getenv("MANHEIM_COLLECTOR_ALIVE_SECONDS", "300")))
    return (time.time() - float(last)) <= window


def unavailable_reason() -> str:
    """Dlaczego Manheim jest niedostępny — w słowach, które kierują do naprawy.

    "manheim_session_not_configured" było prawdziwe, ale bezużyteczne: tak samo
    brzmiało przy braku przeglądarki, jak przy zalogowanej przeglądarce odbijanej
    na bramce autoryzacji, gdzie wystarczyło poprawić jedno pole w opcjach.
    """
    if source_mode() != "collector":
        return "manheim_session_not_configured"
    try:
        from api.manheim_ingest import last_contact_at, last_rejection
    except Exception:
        return "manheim_session_not_configured"

    rejection = last_rejection()
    if not rejection:
        return "collector_not_seen_recently"

    # Odrzucenie liczy się tylko wtedy, gdy jest ŚWIEŻSZE niż ostatni udany
    # kontakt. Inaczej poprawiony token nadal wyglądałby na niezgodny — przez
    # godzinę od ostatniego 403.
    contact = last_contact_at()
    if contact and float(contact) >= float(rejection["at"]):
        return "collector_not_seen_recently"
    if (time.time() - float(rejection["at"])) > 3600:
        return "collector_not_seen_recently"
    return "collector_token_mismatch" if rejection["status"] == 403 else "collector_unauthorized"


def config_ready() -> bool:
    """Czy konfiguracja pozwala w ogóle wejść na Manheima.

    W trybie `collector` (domyślnym) wystarczy sam tryb — pracę wykonuje
    rozszerzenie w przeglądarce operatora, backend niczego nie uruchamia.

    Dwie drogi, w tej kolejności:
      1. MANHEIM_CHROME_CDP_URL — Chrome operatora z BidWise ze Web Store
         (scripts/manheim_chrome_debug.sh). Droga zalecana i jedyna sprawdzona:
         wczytana unpacked BidWise wyłącza sama siebie po kilku sekundach.
      2. rozpakowana wtyczka w MANHEIM_EXTENSION_DIR — zostawiona jako
         fallback, gdyby wtyczka przestała się bronić przed automatyzacją.

    Manheim nie zależy od globalnych USE_EXTENSIONS/HEADLESS: ma albo cudze
    Chrome po CDP, albo własny headed kontekst. Copart/IAAI zostają headless.

    Nie wymaga istniejącego profilu — to jest brama dla pierwszego uruchomienia
    (scripts/manheim_probe.py).
    """
    if source_mode() == "collector":
        return True
    return bool(cdp_url()) or _is_unpacked_extension(extension_dir())


def session_ready() -> bool:
    """Czy backend ma czym wejść na Manheima (nie: czy Manheim odpowiada).

    `config_ready()` plus stały profil Chrome, który już raz wystartował —
    czyli jest gdzie trzymać zalogowaną sesję BidWise. Świadomie statyczne,
    jak reszta /api/capabilities.

    Czego to NIE sprawdza: czy BidWise jest w tym profilu faktycznie zalogowany.
    Weryfikacja loginu wymaga otwarcia przeglądarki, a discovery zdolności musi
    zostać bez efektów ubocznych — brak sesji wychodzi dopiero przy scrape,
    który wtedy zwraca 0 lotów z jawnym ostrzeżeniem w logach.
    """
    if source_mode() == "collector":
        return collector_seen_recently()
    if cdp_url():
        # Świadoma decyzja operatora; czy Chrome pod tym adresem faktycznie
        # stoi, sprawdzić da się dopiero łącząc — a to już efekt uboczny.
        return True
    if not config_ready():
        return False
    profile = chrome_profile_dir()
    return profile.is_dir() and _profile_has_been_used(profile)
