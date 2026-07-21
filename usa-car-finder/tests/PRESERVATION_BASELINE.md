# Task 2 Preservation Baseline (Unfixed Commit)

Observed read-only through SSH alias `wsl2-cf-kiro` before writing tests.

## Production boundary

- Active checkout: `/home/dawid/usacar`
- Branch: `audit/kiro-20260719-0742`
- HEAD: `ebf176d7f0d76636b3ae9fd163ff5ad283b8e365`
- Status: tracked files clean; pre-existing untracked audit scripts, test scripts, `usa-car-finder/data/`, and `usa-car-finder/logs/` remain untouched.
- Process/release identity: PID `193`, executable `/home/dawid/usacar/usa-car-finder/venv/bin/python`, command `uvicorn api.main:app --host 127.0.0.1 --port 8000`.
- Listener: `127.0.0.1:8000` only (not `0.0.0.0:8000`).
- Health: `GET http://127.0.0.1:8000/health` returned HTTP `200`; normalized payload is `{status: "ok"}`. Other configuration fields were observed but are intentionally omitted.

## Isolated unfixed checkout

- Worktree: `/home/dawid/usacar-task1-exploration-ebf176d`
- Backend: `/home/dawid/usacar-task1-exploration-ebf176d/usa-car-finder`
- HEAD: `ebf176d7f0d76636b3ae9fd163ff5ad283b8e365` (detached)
- Pre-task status: only task-1 `.test-deps/` and `tests/` were untracked.
- No production service was started, restarted, or contacted except the read-only loopback health request.

## Normalized application baseline

- `/health`: HTTP 200, `status="ok"`; `use_extensions` and `use_mock_data` are booleans.
- Bearer dependency: protected mode rejects missing credentials with 401, invalid credentials with 403, and accepts the exact valid bearer; empty local-development token is open.
- `/api/logs/stream`: GET route, `DefaultPlaceholder` response metadata, dependency exactly `_require_bearer`.
- Representative unchanged routes: `/health` GET (`health`), `/config` GET (`config`), `/api/search` POST (`dashboard_search`, bearer), `/api/logs/tail` GET (`logs_tail`, bearer), and `/api/logs/stream` GET (`logs_stream`, bearer).
- Auction source defaults: `ClientCriteria.sources == ["copart", "iaai"]`; each source and both together are accepted; `manheim` is rejected by the unfixed backend criteria model.
- Capability discovery side-effect baseline: absent route returns 404 without network, scraper/browser, subprocess, or SQLite calls. The same sentinel test permits the future route's 200 response but never those side effects.
- Normalization scope: only volatile timestamps and SSE chunk boundaries may be normalized. Neither is needed by the assertions above.

No production SQLite file was queried, copied, or modified; no provider, browser, scraper, production stream, merge, push, deployment, or checkout switch was performed.
