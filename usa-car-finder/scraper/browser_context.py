import asyncio
import json
import logging
import os
import stat
import subprocess
import time
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from playwright.async_api import BrowserContext, Playwright, async_playwright

load_dotenv(override=True)

logger = logging.getLogger("scraper.browser_context")

EXTENSION_DIRS = [
    Path("./extensions/auctiongate"),
    Path("./extensions/autohelperbot"),
]
CHROME_PROFILE_DIR = Path(os.getenv("CHROME_PROFILE_DIR", "./data/chrome_profile"))
BROWSER_CHANNEL = os.getenv("BROWSER_CHANNEL", "chrome").strip()
BROWSER_EXECUTABLE_PATH = os.getenv("BROWSER_EXECUTABLE_PATH", "").strip()
BROWSER_LAUNCH_TIMEOUT_MS = int(os.getenv("BROWSER_LAUNCH_TIMEOUT_MS", "45000"))
BROWSER_CONTEXT_TTL_S = float(os.getenv("BROWSER_CONTEXT_TTL_MIN", "30")) * 60.0

_playwright_manager = None
_playwright: Optional[Playwright] = None
_shared_context: Optional[BrowserContext] = None
_shared_context_last_used: float = 0.0
_lock: Optional[asyncio.Lock] = None


def valid_extension_path(path: Path) -> bool:
    disabled = {
        value.strip().lower()
        for value in os.getenv("DISABLED_EXTENSIONS", "").split(",")
        if value.strip()
    }
    if path.name.lower() in disabled:
        print(f"[Browser] Pomijam rozszerzenie {path.name}: DISABLED_EXTENSIONS")
        return False

    manifest_path = path / "manifest.json"
    if not path.is_dir() or not manifest_path.is_file():
        print(f"[Browser] Pomijam rozszerzenie {path}: brak manifest.json")
        return False

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[Browser] Pomijam rozszerzenie {path}: manifest.json nie jest poprawnym JSON ({exc})")
        return False

    if not manifest.get("manifest_version") or not manifest.get("name"):
        print(f"[Browser] Pomijam rozszerzenie {path}: manifest bez manifest_version/name")
        return False

    return True


def prepare_extension_path(path: Path) -> None:
    """Usuwa macOS quarantine i ustawia prawa czytelne dla Chrome/Chromium Helper."""
    for item in [path, *path.rglob("*")]:
        try:
            current_mode = item.stat().st_mode
            if item.is_dir():
                wanted = current_mode | stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH
            else:
                wanted = current_mode | stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH
            if wanted != current_mode:
                item.chmod(wanted)
        except Exception:
            pass

        if os.name == "posix":
            try:
                subprocess.run(
                    ["xattr", "-d", "com.apple.quarantine", str(item)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                    timeout=2,
                )
            except Exception:
                pass


def extension_paths() -> list[str]:
    paths: list[str] = []
    for path in EXTENSION_DIRS:
        if not valid_extension_path(path):
            continue
        prepare_extension_path(path)
        paths.append(str(path.resolve()))
    return paths


def extensions_arg() -> str:
    return ",".join(extension_paths())


def extensions_enabled() -> bool:
    return os.getenv("USE_EXTENSIONS", "false").lower() == "true" and bool(extension_paths())


def keep_browser_open() -> bool:
    default = "true" if os.getenv("USE_EXTENSIONS", "false").lower() == "true" else "false"
    return os.getenv("KEEP_BROWSER_OPEN", default).lower() == "true"


def extension_launch_args() -> list[str]:
    paths = extensions_arg()
    if not paths:
        return []
    return [
        f"--disable-extensions-except={paths}",
        f"--load-extension={paths}",
        "--no-sandbox",
    ]


async def launch_extension_context(playwright: Playwright) -> BrowserContext:
    CHROME_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    launch_kwargs = {
        "user_data_dir": str(CHROME_PROFILE_DIR),
        "headless": False,
        "ignore_default_args": ["--disable-extensions"],
        "slow_mo": int(os.getenv("SLOW_MO_MS", "1500")),
        "viewport": {"width": 1365, "height": 900},
        "locale": "en-US",
        "user_agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "args": extension_launch_args(),
        "timeout": BROWSER_LAUNCH_TIMEOUT_MS,
    }

    if BROWSER_EXECUTABLE_PATH:
        launch_kwargs["executable_path"] = BROWSER_EXECUTABLE_PATH
    elif BROWSER_CHANNEL and BROWSER_CHANNEL.lower() != "chromium":
        launch_kwargs["channel"] = BROWSER_CHANNEL

    return await playwright.chromium.launch_persistent_context(
        **launch_kwargs,
    )


def _get_lock() -> asyncio.Lock:
    global _lock
    if _lock is None:
        _lock = asyncio.Lock()
    return _lock


async def get_shared_extension_context() -> BrowserContext:
    global _playwright_manager, _playwright, _shared_context, _shared_context_last_used

    async with _get_lock():
        # TTL: zamknij stary context jeśli długo nieużywany — chroni przed zombie/zerwaniami sesji.
        if (
            _shared_context is not None
            and BROWSER_CONTEXT_TTL_S > 0
            and (time.monotonic() - _shared_context_last_used) > BROWSER_CONTEXT_TTL_S
        ):
            logger.info(
                "[Browser] Recykling kontekstu po %.0fs bezczynności",
                time.monotonic() - _shared_context_last_used,
            )
            await _close_locked()

        if _shared_context is not None:
            _shared_context_last_used = time.monotonic()
            return _shared_context

        _playwright_manager = async_playwright()
        _playwright = await _playwright_manager.start()
        _shared_context = await launch_extension_context(_playwright)
        browser_label = BROWSER_EXECUTABLE_PATH or BROWSER_CHANNEL or "chromium"
        logger.info(
            "[Browser] Stała przeglądarka z rozszerzeniami uruchomiona (%s): %s",
            browser_label,
            CHROME_PROFILE_DIR,
        )
        _shared_context_last_used = time.monotonic()
        await asyncio.sleep(3)
        return _shared_context


async def _close_locked() -> None:
    """Wewnętrzny close — wywołuj tylko trzymając _get_lock()."""
    global _playwright_manager, _playwright, _shared_context

    if _shared_context is not None:
        try:
            await _shared_context.close()
        except Exception:
            logger.debug("[Browser] close_shared: błąd zamykania kontekstu", exc_info=True)
        _shared_context = None

    if _playwright_manager is not None:
        try:
            await _playwright_manager.stop()
        except Exception:
            logger.debug("[Browser] close_shared: błąd zatrzymania playwright", exc_info=True)
        _playwright_manager = None
        _playwright = None


async def close_shared_extension_context() -> None:
    async with _get_lock():
        await _close_locked()
    logger.info("[Browser] Stała przeglądarka zamknięta")
