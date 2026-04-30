import asyncio
import json
import os
import stat
import subprocess
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from playwright.async_api import BrowserContext, Playwright, async_playwright

load_dotenv(override=True)

EXTENSION_DIRS = [
    Path("./extensions/auctiongate"),
    Path("./extensions/autohelperbot"),
]
CHROME_PROFILE_DIR = Path(os.getenv("CHROME_PROFILE_DIR", "./data/chrome_profile"))
BROWSER_CHANNEL = os.getenv("BROWSER_CHANNEL", "chrome").strip()
BROWSER_EXECUTABLE_PATH = os.getenv("BROWSER_EXECUTABLE_PATH", "").strip()
BROWSER_LAUNCH_TIMEOUT_MS = int(os.getenv("BROWSER_LAUNCH_TIMEOUT_MS", "45000"))

_playwright_manager = None
_playwright: Optional[Playwright] = None
_shared_context: Optional[BrowserContext] = None
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
    global _playwright_manager, _playwright, _shared_context

    async with _get_lock():
        if _shared_context is not None:
            return _shared_context

        _playwright_manager = async_playwright()
        _playwright = await _playwright_manager.start()
        _shared_context = await launch_extension_context(_playwright)
        browser_label = BROWSER_EXECUTABLE_PATH or BROWSER_CHANNEL or "chromium"
        print(f"[Browser] Stała przeglądarka z rozszerzeniami uruchomiona ({browser_label}): {CHROME_PROFILE_DIR}")
        await asyncio.sleep(3)
        return _shared_context


async def close_shared_extension_context() -> None:
    global _playwright_manager, _playwright, _shared_context

    async with _get_lock():
        if _shared_context is not None:
            try:
                await _shared_context.close()
            except Exception:
                pass
            _shared_context = None

        if _playwright_manager is not None:
            try:
                await _playwright_manager.stop()
            except Exception:
                pass
            _playwright_manager = None
            _playwright = None
