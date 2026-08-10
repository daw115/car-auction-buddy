"""
Claude Code w trybie headless jako dostawca modelu — jedno wejście dla całej aplikacji.

Uwierzytelnienie idzie z sesji zalogowanego użytkownika (OAuth subskrypcji), nie z klucza
API. To świadomy wybór: klucz w .env należy do proxy `api.oneprovider.dev` i jest nieważny
od miesięcy (AUDYT_SESJA_2026-07-19.md, punkt 6), więc każda ścieżka oparta o ANTHROPIC_API_KEY
jest dziś martwa. Subskrypcja działa i nie wymaga niczego dokładać.

Wcześniej to samo wywołanie było skopiowane w trzech modułach (ai/analyzer.py,
report/hybrid_reports.py, report/offer_agent.py), za każdym razem z innym zestawem flag
i innym parsowaniem. Tutaj jest raz, z flagami dobranymi na pomiarach.

DLACZEGO TAKIE FLAGI (pomiary na claude 2.1.217, model haiku, pusty katalog roboczy):

  --system-prompt      Prompt systemowy jako osobny argument, NIE sklejony z wiadomością
                       użytkownika. To jest najważniejsza optymalizacja: stały prefiks
                       (nasz prompt + definicje narzędzi, ~21 000 tokenów) wpada do cache'u
                       promptów. Pomiar: pierwsze wywołanie 21 119 tokenów jako
                       cache_creation i 0,043 USD, kolejne z inną wiadomością — 18-21 tys.
                       jako cache_read i 0,003 USD. Trzynastokrotnie taniej i szybciej.
                       Warunek: prompt systemowy musi być IDENTYCZNY co do bajtu między
                       wywołaniami. Żadnych dat, liczników ani nazw klienta w systemie.
  --output-format json Odpowiedź w kopercie JSON razem z czasem, tokenami i kosztem.
                       Wcześniej kod zdrapywał sekwencje ANSI ze stdout i zgadywał, czy
                       odpowiedź jest błędem — teraz błąd niesie flagę is_error.
  --strict-mcp-config  Bez ładowania serwerów MCP z konfiguracji maszyny. Na serwerze
                       z podpiętymi MCP to sekundy startu i tokeny na definicje narzędzi,
                       których to zadanie nie użyje.
  --no-session-persistence  Bez zapisu sesji na dysk — nie wracamy do nich, a przy pętli
                       po lotach śmieciłyby katalog projektów.
  --allowedTools ""    Zadanie jest czysto tekstowe. Każde uruchomienie narzędzia to
                       dodatkowa tura i ryzyko, że odpowiedź przestanie być JSON-em.
  --effort             Niski poziom dla zadań mechanicznych (fragmenty raportu, parsowanie
                       wiadomości), domyślny dla oferty, którą czyta klient.

Czego NIE używamy:
  --bare               wyłącza odczyt OAuth i keychaina, czyli dokładnie to uwierzytelnienie,
                       z którego tu korzystamy.
  --exclude-dynamic-system-prompt-sections
                       działa tylko z domyślnym promptem systemowym, a my podajemy własny.

Katalog roboczy jest pusty i osobny, bo bez --bare Claude Code doczytuje CLAUDE.md z drzewa
projektu — w katalogu tej aplikacji dokleiłby do promptu instrukcje dla programisty.
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import time
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger("ai.claude_code")

# Te zmienne przestawiłyby podproces na uwierzytelnienie kluczem API albo na innego
# dostawcę — a klucz w .env jest martwy, więc wywołanie po prostu by padło.
_STRIPPED_ENV = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_MODEL",
    "CLAUDE_CODE_USE_BEDROCK",
    "CLAUDE_CODE_USE_VERTEX",
)

_ANSI = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]")
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)

_NOT_LOGGED_IN = ("Not logged in", "Please run /login", "Invalid API key")

DEFAULT_TIMEOUT_S = 300
DEFAULT_RETRIES = 3


class NotLoggedIn(RuntimeError):
    """Sesja subskrypcji wygasła — jedyny błąd, którego nie naprawi ponowienie."""


@dataclass(frozen=True)
class Usage:
    """Rachunek za jedno wywołanie — do logu, nie do treści."""

    duration_ms: int = 0
    cost_usd: float = 0.0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0

    @property
    def cache_hit(self) -> bool:
        """Czy stały prefiks poszedł z cache'u. Brak trafienia przy serii wywołań
        oznacza, że prompt systemowy nie jest stały — i płacimy 13× więcej."""
        return self.cache_read_tokens > self.cache_creation_tokens


# Instalator Claude Code kładzie binarkę tutaj, a systemd NIE ma tego katalogu
# w domyślnym PATH (/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin).
# Samo "claude" wystarcza w powłoce logowania i nie działa spod usługi — dlatego
# szukamy też pod pełną ścieżką, zanim uznamy, że CLI nie ma.
_NATIVE_INSTALL = "~/.local/bin/claude"


def cli_path() -> str:
    """Ścieżka do CLI: zmienna środowiskowa → PATH → katalog instalatora."""
    explicit = os.getenv("CLAUDE_CLI_PATH")
    if explicit:
        return explicit

    from shutil import which

    found = which("claude")
    if found:
        return found

    native = os.path.expanduser(_NATIVE_INSTALL)
    if os.access(native, os.X_OK):
        return native
    return "claude"  # zostaje nazwa — komunikat błędu ma pokazać, czego szukaliśmy


def is_available() -> bool:
    """Czy CLI w ogóle jest na tej maszynie. Bez odpytywania modelu."""
    from shutil import which

    path = cli_path()
    return bool(which(path) or (os.path.isfile(path) and os.access(path, os.X_OK)))


def _workdir() -> str:
    # Pusta zmienna w .env znaczy "domyślnie", nie "katalog o pustej nazwie".
    path = os.getenv("CLAUDE_CODE_WORKDIR") or os.path.expanduser("~/.usacar-claude-cwd")
    try:
        os.makedirs(path, exist_ok=True)
    except OSError as exc:
        raise RuntimeError(f"Nie mogę utworzyć katalogu roboczego Claude Code ({path}): {exc}") from exc
    return path


def build_command(
    system: str,
    *,
    model: str,
    effort: Optional[str] = None,
    allowed_tools: str = "",
    add_dirs: Optional[list[str]] = None,
) -> list[str]:
    """Argumenty wywołania. Wydzielone, żeby dało się je sprawdzić testem bez uruchamiania CLI.

    Domyślnie bez narzędzi: zadania tekstowe ich nie potrzebują, a każde
    uruchomienie narzędzia to nieprzewidywalny czas i koszt. Wyjątkiem jest
    analiza zdjęć — model musi móc je odczytać z dysku, bo `claude -p` nie
    przyjmuje obrazów inaczej niż przez narzędzie Read (zmierzone na CLI 2.1.220).
    """
    cmd = [
        cli_path(), "-p",
        "--model", model,
        "--system-prompt", system,
        "--output-format", "json",
        "--strict-mcp-config",
        "--no-session-persistence",
        "--allowedTools", allowed_tools,
    ]
    for directory in add_dirs or []:
        cmd += ["--add-dir", directory]
    if effort:
        cmd += ["--effort", effort]
    return cmd


def _env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k not in _STRIPPED_ENV}


def _model(explicit: Optional[str], env_var: Optional[str]) -> str:
    """Model: argument → zmienna zadania → globalny CLAUDE_CODE_MODEL → 'sonnet'.

    Przyjmuje aliasy CLI ('sonnet', 'opus', 'haiku') i pełne identyfikatory.
    """
    if explicit:
        return explicit
    if env_var and os.getenv(env_var):
        return os.environ[env_var]
    return os.getenv("CLAUDE_CODE_MODEL", "sonnet")


def _unwrap(stdout: str) -> tuple[str, Usage]:
    """Treść i rachunek z koperty JSON. Gdy koperty nie ma — zwracamy surowy tekst."""
    text = _ANSI.sub("", stdout).strip()
    if any(marker in text for marker in _NOT_LOGGED_IN):
        raise NotLoggedIn(
            "Claude Code niezalogowany — uruchom `claude /login` na serwerze "
            "jako użytkownik usługi (sesja subskrypcji wygasła)"
        )
    if not text:
        raise RuntimeError("Claude Code: pusta odpowiedź")

    try:
        envelope = json.loads(text)
    except json.JSONDecodeError:
        return text, Usage()  # starsze CLI albo --output-format text

    if not isinstance(envelope, dict) or "result" not in envelope:
        return text, Usage()

    usage = envelope.get("usage") or {}
    stats = Usage(
        duration_ms=int(envelope.get("duration_ms") or 0),
        cost_usd=float(envelope.get("total_cost_usd") or 0.0),
        output_tokens=int(usage.get("output_tokens") or 0),
        cache_read_tokens=int(usage.get("cache_read_input_tokens") or 0),
        cache_creation_tokens=int(usage.get("cache_creation_input_tokens") or 0),
    )
    result = envelope.get("result") or ""
    if envelope.get("is_error"):
        raise RuntimeError(f"Claude Code: {str(result)[:300] or envelope.get('subtype')}")
    return str(result).strip(), stats


def call(
    system: str,
    user: str,
    *,
    model: Optional[str] = None,
    model_env: Optional[str] = None,
    effort: Optional[str] = None,
    timeout: Optional[int] = None,
    retries: Optional[int] = None,
    label: str = "call",
    allowed_tools: str = "",
    add_dirs: Optional[list[str]] = None,
) -> str:
    """Tekst odpowiedzi. Prompt idzie przez stdin, bo bywa większy niż limit argv.

    Ponawiamy timeouty i błędy procesu; wygasłej sesji nie ponawiamy, bo powtórka
    da dokładnie ten sam komunikat.
    """
    chosen = _model(model, model_env)
    timeout_s = timeout or int(os.getenv("CLAUDE_CODE_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_S)))
    attempts = retries or int(os.getenv("CLAUDE_CODE_MAX_RETRIES", str(DEFAULT_RETRIES)))
    cmd = build_command(
        system,
        model=chosen,
        effort=effort or os.getenv("CLAUDE_CODE_EFFORT") or None,
        allowed_tools=allowed_tools,
        add_dirs=add_dirs,
    )
    env, workdir = _env(), _workdir()

    last: Exception = RuntimeError("Claude Code: brak odpowiedzi")
    for attempt in range(attempts):
        try:
            proc = subprocess.run(
                cmd, input=user, capture_output=True, text=True,
                timeout=timeout_s, cwd=workdir, env=env,
            )
        except FileNotFoundError as exc:
            raise RuntimeError(f"claude nie znaleziony ({cli_path()}): {exc}") from exc
        except subprocess.TimeoutExpired as exc:
            last = RuntimeError(f"Claude Code timeout po {timeout_s}s")
            if attempt < attempts - 1:
                time.sleep(min(2 ** attempt * 2, 30))
                continue
            raise last from exc

        try:
            text, usage = _unwrap(proc.stdout)
        except NotLoggedIn:
            raise
        except RuntimeError as exc:
            last = exc
            if proc.returncode != 0:
                last = RuntimeError(
                    f"Claude Code exit {proc.returncode}: {(proc.stderr or str(exc))[:300]}"
                )
            if attempt < attempts - 1:
                time.sleep(min(2 ** attempt * 2, 30))
                continue
            raise last

        logger.info(
            "[claude-code] %s: %s, %.1fs, %d tok out, cache %s (%.4f USD)",
            label, chosen, usage.duration_ms / 1000, usage.output_tokens,
            "HIT" if usage.cache_hit else "MISS", usage.cost_usd,
        )
        return text

    raise last


def call_json(system: str, user: str, **kwargs: Any) -> Any:
    """To samo, ale z odpowiedzi wyjmujemy JSON.

    Model potrafi owinąć wynik w ```json albo poprzedzić go zdaniem — bierzemy
    pierwszy obiekt lub tablicę i to on jest odpowiedzią.
    """
    text = call(system, user, **kwargs)
    return parse_json(text)


def parse_json(text: str) -> Any:
    cleaned = _FENCE.sub("", text.strip()).strip()
    starts = [i for i in (cleaned.find("{"), cleaned.find("[")) if i >= 0]
    if not starts:
        raise ValueError(f"Brak JSON-a w odpowiedzi: {cleaned[:200]}")
    start = min(starts)
    closing = "}" if cleaned[start] == "{" else "]"
    end = cleaned.rfind(closing)
    if end <= start:
        raise ValueError(f"Niedomknięty JSON w odpowiedzi: {cleaned[:200]}")
    return json.loads(cleaned[start:end + 1])
