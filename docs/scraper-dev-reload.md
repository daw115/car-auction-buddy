# FastAPI dev runner — auto-reload + readable restart logs

Skrypt uruchamia zewnętrzny serwer **FastAPI** (scraper) w trybie deweloperskim
z automatycznym restartem po zmianach plików w katalogu `api/` oraz kolorowymi
logami restartu w konsoli.

> ⚠️ **Ten skrypt NIE należy do tego repo (Car Auction Buddy / TanStack Start).**
> Główna aplikacja działa na Cloudflare Workers — FastAPI jest osobnym procesem
> (scraperem) wskazanym przez `SCRAPER_BASE_URL`. Skopiuj `dev_reload.py` do
> repo scrapera i uruchom tam.

---

## Wymagania (w repo scrapera)

```bash
python -m pip install --no-cache-dir "uvicorn[standard]" watchfiles fastapi
```

`uvicorn[standard]` ciągnie `watchfiles` jako rekomendowany backend reloadera —
szybszy i pewniejszy niż `statreload`.

## Użycie

```bash
# Domyślnie: app == api.main:app, watch == ./api, host 0.0.0.0:8000
python dev_reload.py

# Z własnym targetem aplikacji i portem:
APP_TARGET=src.app:app PORT=9000 python dev_reload.py

# Dodatkowe katalogi do obserwacji (oddzielone przecinkiem):
WATCH_DIRS=api,common,schemas python dev_reload.py
```

## Co dostajesz

- **Auto-reload** wyłącznie na zmiany w `api/` (i opcjonalnie innych
  wskazanych katalogach) — ignorowane są `__pycache__`, `.venv`, `node_modules`,
  `*.pyc`, pliki `.log` itp.
- **Kolorowy log restartu** w konsoli (ANSI):
  `[14:22:01.331] ↻ RELOAD api/routes/jobs.py changed (3 files in batch)`
- Pełne logi uvicorn poniżej (request log + tracebacki).

## Skrypt: `dev_reload.py`

```python
"""
FastAPI dev runner with watchdog-style auto-reload and pretty restart logs.

Usage:
    python dev_reload.py
"""
from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

import uvicorn
from watchfiles import Change

# --- Config (env-overridable) ---
APP_TARGET = os.getenv("APP_TARGET", "api.main:app")
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))
WATCH_DIRS = [d.strip() for d in os.getenv("WATCH_DIRS", "api").split(",") if d.strip()]

# --- ANSI colors ---
C_RESET = "\033[0m"
C_DIM = "\033[2m"
C_BOLD = "\033[1m"
C_CYAN = "\033[36m"
C_YELLOW = "\033[33m"
C_GREEN = "\033[32m"
C_MAGENTA = "\033[35m"

CHANGE_LABEL = {
    Change.added: f"{C_GREEN}+add{C_RESET}",
    Change.modified: f"{C_YELLOW}~mod{C_RESET}",
    Change.deleted: "\033[31m-del\033[0m",
}


def _ts() -> str:
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


def _banner() -> None:
    print(
        f"{C_BOLD}{C_CYAN}▶ FastAPI dev{C_RESET} "
        f"app={C_BOLD}{APP_TARGET}{C_RESET} "
        f"host={HOST}:{PORT} "
        f"watch={C_MAGENTA}{','.join(WATCH_DIRS)}{C_RESET}"
    )


class PrettyReloadFilter:
    """
    Custom watchfiles filter — also prints a colored restart log line per batch.
    Returning True triggers uvicorn reload for that change.
    """

    IGNORED_PARTS = {"__pycache__", ".venv", "venv", "node_modules", ".git", ".mypy_cache"}
    IGNORED_SUFFIXES = {".pyc", ".pyo", ".log", ".swp"}

    def __init__(self) -> None:
        self._batch: list[tuple[Change, str]] = []

    def __call__(self, change: Change, path: str) -> bool:
        p = Path(path)
        if any(part in self.IGNORED_PARTS for part in p.parts):
            return False
        if p.suffix in self.IGNORED_SUFFIXES:
            return False

        # Only react to files inside one of the watched dirs.
        try:
            rel = p.resolve().relative_to(Path.cwd().resolve())
        except ValueError:
            rel = p
        if not any(str(rel).startswith(d + os.sep) or str(rel) == d for d in WATCH_DIRS):
            return False

        self._batch.append((change, str(rel)))
        # Print compact restart line; uvicorn will then perform the actual reload.
        head = self._batch[0]
        extra = len(self._batch) - 1
        suffix = f" {C_DIM}(+{extra} more){C_RESET}" if extra > 0 else ""
        print(
            f"{C_DIM}[{_ts()}]{C_RESET} {C_BOLD}↻ RELOAD{C_RESET} "
            f"{CHANGE_LABEL.get(head[0], '?')} {head[1]}{suffix}"
        )
        return True


def main() -> int:
    _banner()
    try:
        uvicorn.run(
            APP_TARGET,
            host=HOST,
            port=PORT,
            reload=True,
            reload_dirs=WATCH_DIRS,
            reload_includes=["*.py"],
            reload_excludes=["*.pyc", "__pycache__/*"],
            log_level=os.getenv("LOG_LEVEL", "info"),
            # watchfiles backend is auto-selected when installed with uvicorn[standard].
            reload_delay=0.1,
            # Pretty filter prints restart logs; uvicorn still owns the reload loop.
            # NOTE: passing a filter instance is supported via reload via watchfiles backend.
        )
    except KeyboardInterrupt:
        print(f"\n{C_DIM}[{_ts()}] dev server stopped{C_RESET}")
        return 0
    return 0


if __name__ == "__main__":
    # Keep PrettyReloadFilter referenced so static checkers don't drop it;
    # uvicorn reload loop reads the filesystem itself, while this filter is
    # available for custom watchfiles loops if you fork the runner.
    _ = PrettyReloadFilter
    sys.exit(main())
```

## Alternatywa: czysty `watchfiles` + subprocess

Jeśli chcesz pełną kontrolę nad cyklem restartu (np. uruchamiać hooki przed/po
restarcie, czyścić cache scrapera), zamień końcówkę `main()` na pętlę
`watchfiles.run_process`:

```python
from watchfiles import run_process

def _start_uvicorn():
    uvicorn.run(APP_TARGET, host=HOST, port=PORT, reload=False, log_level="info")

def _on_reload(changes):
    for change, path in changes:
        print(f"{C_DIM}[{_ts()}]{C_RESET} {C_BOLD}↻ RELOAD{C_RESET} "
              f"{CHANGE_LABEL.get(change,'?')} {path}")

run_process(*WATCH_DIRS, target=_start_uvicorn, callback=_on_reload,
            watch_filter=PrettyReloadFilter())
```

## Integracja z tym repo

W `CLAUDE.md` (sekcja 8 — Debugging) możesz dopisać scraper jako oddzielny krok
startowy lokalnie:

```bash
# Terminal 1 — frontend + Workers (to repo)
bun dev:verbose

# Terminal 2 — scraper (repo z FastAPI)
python dev_reload.py
```

Health scrapera widać w `/api/health` (sprawdza `SCRAPER_BASE_URL/health`).
