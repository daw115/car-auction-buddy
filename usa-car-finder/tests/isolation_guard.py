from __future__ import annotations

from pathlib import Path
from typing import TypeAlias

PathLike: TypeAlias = str | Path

_PROTECTED_CHECKOUT_ROOTS = (
    Path("/home/dawid/usacar"),
    Path("/opt/usacar"),
)
_PRODUCTION_DATABASES = (
    Path("/home/dawid/usacar/usa-car-finder/data/watch_queue.db"),
    Path("/home/dawid/usacar/usa-car-finder/data/app.db"),
)
_DATABASE_SUFFIXES = {".db", ".sqlite", ".sqlite3"}


class IsolationViolation(RuntimeError):
    """Raised before a test can touch an active checkout or production DB."""


def _resolved(path: PathLike) -> Path:
    return Path(path).expanduser().resolve(strict=False)


def _is_within(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def assert_safe_test_checkout(repo_root: PathLike) -> Path:
    candidate = _resolved(repo_root)
    for protected in _PROTECTED_CHECKOUT_ROOTS:
        if _is_within(candidate, protected):
            raise IsolationViolation(f"active/production checkout is forbidden: {candidate}")
    if not (candidate / ".git").exists():
        raise IsolationViolation(f"test checkout has no Git worktree marker: {candidate}")
    return candidate


def assert_safe_test_database_path(database_path: PathLike, *, sandbox_root: PathLike) -> Path:
    candidate = _resolved(database_path)
    sandbox = _resolved(sandbox_root)
    if candidate in _PRODUCTION_DATABASES:
        raise IsolationViolation(f"production SQLite path is forbidden: {candidate}")
    for protected in _PROTECTED_CHECKOUT_ROOTS:
        if _is_within(candidate, protected):
            raise IsolationViolation(f"SQLite under active/production checkout is forbidden: {candidate}")
    if not _is_within(candidate, sandbox):
        raise IsolationViolation(f"SQLite path must stay inside test sandbox {sandbox}: {candidate}")
    if candidate.suffix.lower() not in _DATABASE_SUFFIXES:
        raise IsolationViolation(f"test database must be SQLite: {candidate}")
    return candidate
