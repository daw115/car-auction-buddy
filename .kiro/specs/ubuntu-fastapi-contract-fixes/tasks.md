# Implementation Plan

## Overview

Execute the bugfix with the required explore → preserve → implement → validate sequence, entirely in an isolated worktree. Production cutover is a separately approved, reversible step; no task authorizes a branch switch, database mutation, merge, or push.

## Tasks

- [x] 1. Write bug condition exploration property test
  - **Property 1: Bug Condition** - OpenAPI, Viewer Secret, and Capability Contracts
  - **CRITICAL**: Write and run this test in an isolated worktree at `ebf176d7f0d76636b3ae9fd163ff5ad283b8e365` BEFORE implementing the fix; it MUST FAIL on unfixed code.
  - **DO NOT** fix the test or application when it fails; record exact counterexamples first.
  - Create an isolated test environment that does not run FastAPI lifespan workers, open production SQLite, launch browsers/scrapers, or make external requests.
  - Add a backend test module that generates the OpenAPI schema, renders the viewer with arbitrary sentinel bearer values, and requests `/api/capabilities` in-process.
  - **Scoped PBT Approach**: include the deterministic failing cases `app.openapi()`, a protected viewer with `SCRAPER_API_TOKEN=server-only-sentinel`, and authorized `GET /api/capabilities`; also generate token strings and configuration combinations.
  - Assert expected behavior from `expectedBehavior`: valid OpenAPI, no bearer in browser-visible output, protected viewer fail-closed, and a schema-valid conservative capability payload.
  - Run on UNFIXED code and expect: OpenAPI assertion/500, sentinel present in HTML, and capabilities 404.
  - Save only sanitized failure details; never print a real production bearer.
  - Mark complete only after the test is written, run, and its failing counterexamples are documented.
  - _Bug_Condition: `isBugCondition(input)` from design_
  - _Requirements: 1.1, 1.2, 1.3, 1.4_

- [x] 2. Write preservation property tests before implementing the fix
  - **Property 2: Preservation** - Production API and Safety Boundary
  - **IMPORTANT**: Follow observation-first methodology on the unfixed isolated checkout.
  - Observe and record normalized behavior for `/health`, missing/invalid/valid bearer handling, `/api/logs/stream` authorization setup, representative route metadata, and Copart/IAAI defaults.
  - Record through SSH, without mutation, the active checkout branch/HEAD/status, process/release identity, `127.0.0.1:8000` listener, and pre-change health status; do not expose environment values.
  - Generate non-bug request/configuration cases and compare normalized outputs; normalize only timestamps and streaming boundaries.
  - Instrument network, scraper/browser, and database entry points as fail-on-call sentinels so capability computation is required to be side-effect-free.
  - Run existing frontend `auction-sources` schema/fallback tests without changing frontend code.
  - Verify preservation tests PASS on UNFIXED code before implementation.
  - Do not modify, copy over, migrate, or directly query/write production SQLite as part of these tests.
  - Mark complete only when baseline observations are documented and tests pass on unfixed code.
  - _Preservation: Preservation Requirements from design_
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8_

- [x] 3. Fix the Ubuntu FastAPI contracts in an isolated worktree
  - [x] 3.1 Create and verify the isolated implementation workspace
    - Re-check via `wsl2-cf-kiro` that `/home/dawid/usacar` remains on `audit/kiro-20260719-0742` at the expected commit; stop and ask if it moved.
    - Preserve all current untracked production files and create a separate worktree/release from the pinned commit on a new fix branch; never switch the active checkout.
    - Discover and record the actual process manager/release mechanism before changing anything; the absent user unit named `usa-car-finder.service` must not be guessed around.
    - Use isolated test state and an isolated virtual environment. Any new test dependency must use a reviewed exact version and must not become an unpinned runtime dependency.
    - _Preservation: active checkout, data, process, and listener requirements from design_
    - _Requirements: 3.1, 3.5, 3.7, 3.8_
  - [x] 3.2 Correct OpenAPI metadata and remove browser credential disclosure
    - In isolated `usa-car-finder/api/main.py`, import `HTMLResponse` with the existing FastAPI responses and declare `response_class=HTMLResponse` on `/api/logs/viewer`.
    - Remove `SCRAPER_API_TOKEN` interpolation, `const TOKEN`, and browser construction/sending/storage of the server bearer.
    - In protected mode, make browser streaming fail closed with a non-secret response unless a separate browser-safe scoped mechanism already exists and is independently validated; do not invent one in this fix.
    - Preserve uncredentialed local-development viewer behavior only when bearer protection is explicitly not configured.
    - Add defense-in-depth response controls appropriate for secret-free HTML (for example no-store and a restrictive policy) without changing unrelated routes.
    - _Bug_Condition: OpenAPI and LOG_VIEWER branches of `isBugCondition(input)`_
    - _Expected_Behavior: OPENAPI and LOG_VIEWER branches of `expectedBehavior(input, result)`_
    - _Preservation: `/api/logs/stream` retains `_require_bearer` and unrelated route behavior_
    - _Requirements: 2.1, 2.2, 2.3, 3.2, 3.3_

  - [x] 3.3 Add the conservative authenticated capability contract
    - Add strict response types and a pure capability builder for `checkedAt` plus exactly `copart`, `iaai`, and `manheim`.
    - Derive Copart/IAAI values only from known implementation and configuration readiness; document that `live` means backend capability, not upstream health.
    - First locate any existing official Manheim adapter and its required configuration. If none exists or readiness is incomplete, always return `{available:false, mode:"unavailable", reason:"credentials_or_adapter_missing"}` (or an equally stable non-secret reason).
    - Permit Manheim `{available:true, mode:"official_api"}` only when `MANHEIM_BACKEND_ENABLED=true` and the existing official adapter's complete readiness check passes; a flag alone is insufficient.
    - Never call auction providers, scraper/browser/session code, or SQLite while building the response.
    - Add `GET /api/capabilities` with `Depends(_require_bearer)` and a declared response model; reasons are non-secret and at most 200 characters.
    - Validate a sample response against the exact frontend `auctionSourceCapabilitiesPayloadSchema` contract.
    - _Bug_Condition: CAPABILITIES branch of `isBugCondition(input)`_
    - _Expected_Behavior: CAPABILITIES branch of `expectedBehavior(input, result)`_
    - _Preservation: source orchestration, frontend fallback, database, and external traffic requirements from design_
    - _Requirements: 2.4, 2.5, 2.6, 2.7, 2.8, 3.2, 3.4, 3.5, 3.6_

  - [x] 3.4 Verify the bug condition exploration test now passes
    - **Property 1: Expected Behavior** - OpenAPI, Viewer Secret, and Capability Contracts
    - **IMPORTANT**: Re-run the SAME test from task 1; do not replace it with a weaker or new test.
    - Confirm `/openapi.json` is 200 valid JSON and includes the viewer HTML response and capabilities route.
    - Confirm generated sentinel bearers never appear in viewer bodies, headers, scripts, URLs, redirects, or storage expressions, and protected browser streaming fails closed.
    - Confirm capabilities payloads satisfy the consumer schema and all mode/availability invariants, including Manheim default-deny.
    - **EXPECTED OUTCOME**: Test PASSES, confirming both defects and the credential disclosure are fixed.
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8_

  - [x] 3.5 Verify preservation property tests still pass
    - **Property 2: Preservation** - Production API and Safety Boundary
    - **IMPORTANT**: Re-run the SAME tests from task 2; do not write replacement tests after seeing failures.
    - Confirm bearer rejection/acceptance, representative APIs, health behavior, source defaults, frontend legacy fallback, and side-effect sentinels remain unchanged.
    - Confirm test execution did not access production SQLite, external auction providers, browsers, or production Uvicorn.
    - **EXPECTED OUTCOME**: Tests PASS with no regressions.
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8_

  - [x] 3.6 Run targeted candidate validation
    - Run backend unit/property/integration tests in one-shot mode, Python compile/import checks, and the existing targeted frontend schema/fallback tests.
    - Validate both protected and explicitly unprotected local configurations without using a real production secret in test output.
    - Review the diff for only intended backend/test files and verify no environment, database, generated data, logs, or credentials are included.
    - Verify the active production checkout branch, HEAD, status, listener, and health are unchanged after candidate testing.
    - Do not merge, push, deploy, or restart production in this task.
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7_

- [x] 4. Checkpoint - Ensure all tests pass and stop before production
  - Confirm the original exploration counterexamples are documented and the same Property 1 test now passes.
  - Confirm Property 2 passed before and after the fix, plus compile/import and targeted frontend contract tests.
  - Confirm no real secret is present in test output, HTML fixtures, diffs, logs, or artifacts.
  - Confirm `/home/dawid/usacar` still has its original branch/HEAD/status, production SQLite was untouched, and Uvicorn still listens only on `127.0.0.1:8000`.
  - Present candidate diff/test evidence, the discovered release mechanism, preflight record, and rollback reference to the user.
  - **STOP and request explicit approval before any production cutover. Do not merge or push.**

- [x] 5. Perform a controlled production cutover only after explicit approval
  - Re-run and record pre-health through `wsl2-cf-kiro`: active checkout identity/status, current release, process health, loopback listener, `/health`, representative authorized/unauthorized behavior, and rollback target. Redact credentials.
  - Deploy only the validated isolated release using the discovered existing process manager; do not switch the active repo branch, bind to `0.0.0.0`, mutate SQLite, merge, or push.
  - Keep the prior release intact and immediately selectable.
  - Run post-health: process stable, `127.0.0.1:8000` only, `/health` healthy, `/openapi.json` 200, capabilities authorized response schema-valid, unauthorized response rejected, Manheim default-deny unless truly configured, viewer contains no bearer, and representative existing APIs unchanged.
  - If any check fails, select the recorded prior release and restart with the same mechanism, then repeat health and listener checks. Rollback code only; do not alter databases.
  - Record sanitized deployment/rollback evidence and verify the active checkout remains on `audit/kiro-20260719-0742`.
  - _Requirements: 3.1, 3.2, 3.3, 3.5, 3.7, 3.8_

- [x] 6. Final checkpoint - Confirm production stability
  - Confirm all approved post-health checks pass and no rollback trigger remains.
  - If rollback occurred, confirm the prior release is healthy and report the failed check; do not retry without new approval.
  - Ask the user about any discrepancy or follow-up; no merge or push is implied by completion.

## Task Dependency Graph

```json
{
  "waves": [
    { "wave": 1, "tasks": ["1", "2"] },
    { "wave": 2, "tasks": ["3.1"] },
    { "wave": 3, "tasks": ["3.2", "3.3"] },
    { "wave": 4, "tasks": ["3.4", "3.5"] },
    { "wave": 5, "tasks": ["3.6"] },
    { "wave": 6, "tasks": ["4"] },
    { "wave": 7, "tasks": ["5"] },
    { "wave": 8, "tasks": ["6"] }
  ]
}
```

Tasks 1 and 2 both precede implementation. Task 5 is blocked by task 4 and explicit user approval.

## Notes

- Exploration failure on unfixed code is success evidence for task 1; preservation tests must pass before the fix.
- Run tests as one-shot commands, not watchers or development servers.
- All SSH actions target only alias `wsl2-cf-kiro`; never print or persist server secrets.
- Production deployment, merge, and push remain out of scope until separately authorized.
