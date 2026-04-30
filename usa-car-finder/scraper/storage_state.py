"""
Storage state management - zapisane sesje logowania dla scraperów.
Zgodnie z PLAYWRIGHT_ARCHITECTURE.md
"""
import json
from pathlib import Path
from typing import Any


STORAGE_STATE_DIR = Path("playwright_profiles")


def storage_state_path(source: str) -> Path:
    """Zwraca ścieżkę do pliku storage_state dla danego źródła."""
    STORAGE_STATE_DIR.mkdir(exist_ok=True)
    return STORAGE_STATE_DIR / f"{source}.json"


def has_storage_state(source: str) -> bool:
    """Sprawdza czy istnieje zapisana sesja dla źródła."""
    return storage_state_path(source).exists()


def combined_storage_state(*sources: str) -> dict[str, list[dict[str, Any]]]:
    """Łączy kilka plików storage_state w jeden stan Playwright.

    Używane, gdy scraper giełdy musi jednocześnie mieć cookies Copart/IAAI
    oraz cookies AutoHelperBot w tym samym kontekście.
    """
    cookies: dict[tuple[str, str, str], dict[str, Any]] = {}
    origins: dict[str, dict[str, Any]] = {}

    for source in sources:
        path = storage_state_path(source)
        if not path.exists():
            continue
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue

        for cookie in state.get("cookies", []):
            key = (
                str(cookie.get("name", "")),
                str(cookie.get("domain", "")),
                str(cookie.get("path", "")),
            )
            cookies[key] = cookie

        for origin_state in state.get("origins", []):
            origin = origin_state.get("origin")
            if not origin:
                continue
            current = origins.setdefault(origin, {"origin": origin, "localStorage": []})
            local_storage = {
                item.get("name"): item
                for item in current.get("localStorage", [])
                if item.get("name")
            }
            for item in origin_state.get("localStorage", []):
                name = item.get("name")
                if name:
                    local_storage[name] = item
            current["localStorage"] = list(local_storage.values())

    return {"cookies": list(cookies.values()), "origins": list(origins.values())}
