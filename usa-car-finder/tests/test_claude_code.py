"""Claude Code jako dostawca modelu — budowa wywołania i obsługa odpowiedzi.

Testy nie uruchamiają CLI. Sprawdzają to, co da się zepsuć po cichu: flagi decydujące
o cache'u promptów, czyszczenie środowiska i rozpoznanie wygasłej sesji.
"""
import json
import subprocess

import pytest

from ai import claude_code
from ai.claude_code import NotLoggedIn, build_command, parse_json


def envelope(result: str, **over) -> str:
    payload = {
        "type": "result", "subtype": "success", "is_error": False,
        "duration_ms": 3000, "result": result, "total_cost_usd": 0.003,
        "usage": {"output_tokens": 50, "cache_read_input_tokens": 21000,
                  "cache_creation_input_tokens": 0},
    }
    payload.update(over)
    return json.dumps(payload)


def fake_run(stdout="", stderr="", returncode=0, record=None):
    def run(cmd, **kwargs):
        if record is not None:
            record.append({"cmd": cmd, **kwargs})
        return subprocess.CompletedProcess(cmd, returncode, stdout, stderr)
    return run


# ─────────────────────────────────────────────────────────── budowa wywołania


def test_system_prompt_goes_as_its_own_flag_not_glued_to_the_message():
    """Na tym stoi cache promptów: stały prefiks to 13× tańsze kolejne wywołanie."""
    cmd = build_command("PROMPT SYSTEMOWY", model="sonnet")
    assert "--system-prompt" in cmd
    assert cmd[cmd.index("--system-prompt") + 1] == "PROMPT SYSTEMOWY"


def test_tools_mcp_and_session_are_all_switched_off():
    cmd = build_command("s", model="haiku")
    assert cmd[cmd.index("--allowedTools") + 1] == ""
    assert "--strict-mcp-config" in cmd
    assert "--no-session-persistence" in cmd
    assert "--output-format" in cmd and cmd[cmd.index("--output-format") + 1] == "json"


def test_bare_is_never_used():
    """--bare wyłącza odczyt OAuth, czyli dokładnie to uwierzytelnienie, z którego żyjemy."""
    assert "--bare" not in build_command("s", model="sonnet")


def test_effort_is_optional():
    assert "--effort" not in build_command("s", model="sonnet")
    assert "--effort" in build_command("s", model="sonnet", effort="low")


def test_prompt_goes_through_stdin_not_argv(monkeypatch):
    """Prompt analizy potrafi mieć dziesiątki kilobajtów — jako argument przekroczyłby ARG_MAX."""
    calls = []
    monkeypatch.setattr(subprocess, "run", fake_run(envelope("ok"), record=calls))
    claude_code.call("system", "bardzo długi prompt")

    assert calls[0]["input"] == "bardzo długi prompt"
    assert "bardzo długi prompt" not in calls[0]["cmd"]


def test_api_key_is_stripped_from_the_subprocess(monkeypatch):
    """Z kluczem w środowisku Claude Code uzna go za nadrzędny wobec subskrypcji i padnie."""
    calls = []
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-martwy")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://api.oneprovider.dev")
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setattr(subprocess, "run", fake_run(envelope("ok"), record=calls))
    claude_code.call("system", "user")

    env = calls[0]["env"]
    assert "ANTHROPIC_API_KEY" not in env and "ANTHROPIC_BASE_URL" not in env
    assert env["PATH"] == "/usr/bin"  # reszta środowiska zostaje


# ──────────────────────────────────────────────────────────────── wybór modelu


def test_model_priority_is_argument_then_task_then_global(monkeypatch):
    monkeypatch.delenv("CLAUDE_CODE_MODEL", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_OFFER_MODEL", raising=False)
    assert claude_code._model(None, "CLAUDE_CODE_OFFER_MODEL") == "sonnet"

    monkeypatch.setenv("CLAUDE_CODE_MODEL", "haiku")
    assert claude_code._model(None, "CLAUDE_CODE_OFFER_MODEL") == "haiku"

    monkeypatch.setenv("CLAUDE_CODE_OFFER_MODEL", "opus")
    assert claude_code._model(None, "CLAUDE_CODE_OFFER_MODEL") == "opus"
    assert claude_code._model("haiku", "CLAUDE_CODE_OFFER_MODEL") == "haiku"


def test_empty_env_value_means_default_not_empty_string(monkeypatch):
    """Pusta zmienna w .env to "domyślnie", nie "model o pustej nazwie"."""
    monkeypatch.setenv("CLAUDE_CODE_OFFER_MODEL", "")
    monkeypatch.setenv("CLAUDE_CODE_MODEL", "sonnet")
    assert claude_code._model(None, "CLAUDE_CODE_OFFER_MODEL") == "sonnet"

    monkeypatch.setenv("CLAUDE_CODE_WORKDIR", "")
    assert claude_code._workdir().endswith(".usacar-claude-cwd")


# ──────────────────────────────────────────────────────── odczyt odpowiedzi


def test_result_is_taken_out_of_the_json_envelope(monkeypatch):
    monkeypatch.setattr(subprocess, "run", fake_run(envelope("  treść  ")))
    assert claude_code.call("s", "u") == "treść"


def test_error_envelope_is_raised_not_returned(monkeypatch):
    monkeypatch.setattr(
        subprocess, "run",
        fake_run(envelope("rate limit", is_error=True), returncode=0),
    )
    with pytest.raises(RuntimeError, match="rate limit"):
        claude_code.call("s", "u", retries=1)


def test_expired_session_says_what_to_do_and_is_not_retried(monkeypatch):
    """Powtórka da ten sam komunikat — trzeba zalogować się na serwerze."""
    calls = []
    monkeypatch.setattr(subprocess, "run", fake_run("Not logged in", record=calls))
    with pytest.raises(NotLoggedIn, match="claude /login"):
        claude_code.call("s", "u", retries=3)
    assert len(calls) == 1


def test_plain_text_output_still_works(monkeypatch):
    """Starsze CLI albo --output-format text — nie wywalamy się na braku koperty."""
    monkeypatch.setattr(subprocess, "run", fake_run("zwykły tekst"))
    assert claude_code.call("s", "u") == "zwykły tekst"


def test_timeout_is_retried_then_reported(monkeypatch):
    attempts = []

    def run(cmd, **kwargs):
        attempts.append(cmd)
        raise subprocess.TimeoutExpired(cmd, 1)

    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(claude_code.time, "sleep", lambda _s: None)
    with pytest.raises(RuntimeError, match="timeout"):
        claude_code.call("s", "u", retries=2)
    assert len(attempts) == 2


def test_missing_cli_is_reported_clearly(monkeypatch):
    def run(cmd, **kwargs):
        raise FileNotFoundError("no such file")

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(RuntimeError, match="nie znaleziony"):
        claude_code.call("s", "u")


# ───────────────────────────────────────────────────────────────────── JSON


@pytest.mark.parametrize(
    "raw",
    [
        '{"ok": true}',
        '```json\n{"ok": true}\n```',
        'Oczywiście, oto wynik:\n{"ok": true}',
        '```\n{"ok": true}\n```\n',
    ],
)
def test_json_is_dug_out_of_whatever_the_model_wrapped_it_in(raw):
    assert parse_json(raw) == {"ok": True}


def test_json_arrays_survive_too():
    assert parse_json('[{"a": 1}]') == [{"a": 1}]


def test_missing_json_is_an_error_not_none():
    with pytest.raises(ValueError, match="Brak JSON"):
        parse_json("przepraszam, nie mogę")


def test_cache_hit_is_reported_from_usage():
    hit = claude_code.Usage(cache_read_tokens=21_000, cache_creation_tokens=0)
    miss = claude_code.Usage(cache_read_tokens=0, cache_creation_tokens=21_000)
    assert hit.cache_hit and not miss.cache_hit


def test_cli_is_found_in_the_native_install_dir_when_not_on_path(monkeypatch, tmp_path):
    """systemd nie ma ~/.local/bin w PATH — bez tego usługa nie znajduje CLI,
    choć spod powłoki logowania wszystko działa (tak stoi serwer usacar)."""
    native = tmp_path / ".local" / "bin" / "claude"
    native.parent.mkdir(parents=True)
    native.write_text("#!/bin/sh\n")
    native.chmod(0o755)

    monkeypatch.delenv("CLAUDE_CLI_PATH", raising=False)
    monkeypatch.setattr(claude_code.os.path, "expanduser", lambda p: str(native) if "claude" in p else p)
    monkeypatch.setattr("shutil.which", lambda _name: None)

    assert claude_code.cli_path() == str(native)


def test_explicit_path_wins_over_everything(monkeypatch):
    monkeypatch.setenv("CLAUDE_CLI_PATH", "/opt/claude/bin/claude")
    assert claude_code.cli_path() == "/opt/claude/bin/claude"
