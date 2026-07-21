# Task 3.1 Isolated Implementation Workspace Evidence

- Active checkout: /home/dawid/usacar, branch audit/kiro-20260719-0742, HEAD ebf176d7f0d76636b3ae9fd163ff5ad283b8e365.
- Active status preservation fingerprint: 25 pre-existing untracked entries, SHA-256 45cb699ddb4203b03622291213643e71f44db377857b644cf46d287afe0fab53; no tracked changes.
- Isolated worktree: /home/dawid/usacar-task1-exploration-ebf176d, branch fix/ubuntu-fastapi-contract-fixes, HEAD ebf176d7f0d76636b3ae9fd163ff5ad283b8e365. Existing task-1/task-2 tests and evidence were preserved.
- Isolated backend root: /home/dawid/usacar-task1-exploration-ebf176d/usa-car-finder.
- Isolated venv: .venv-task1 (CPython 3.12.13, include-system-site-packages = false).
- Isolated test state: .test-state-contract-fixes; no SQLite file exists in the isolated worktree.
- Test-only dependency layer: .test-deps, pinned by tests/requirements-contract-tests.lock; no runtime dependency file was modified and no dependency was installed for task 3.1.

## Production process and release mechanism

- Actual manager: system-level systemd unit usacar-api.service (/etc/systemd/system/usacar-api.service), active/running and enabled; cgroup /system.slice/usacar-api.service.
- Effective working directory: /home/dawid/usacar/usa-car-finder.
- Effective ExecStart: /home/dawid/usacar/usa-car-finder/venv/bin/uvicorn api.main:app --host 127.0.0.1 --port 8000.
- Current release selection is direct paths to the active checkout and its venv; no release symlink or alternate release path is used by the effective unit. The existing system unit, not an assumed user unit, is the restart/cutover mechanism if a later explicitly approved task changes production.
- Listener baseline: only 127.0.0.1:8000; /health returned HTTP 200.

No service restart, deployment, production database access, provider request, browser/scraper call, merge, push, commit, or active-checkout switch was performed.
