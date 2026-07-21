# Ubuntu FastAPI Contract Fixes Bugfix Design

## Overview

The production backend in `/home/dawid/usacar/usa-car-finder` has two contract defects at `ebf176d7f0d76636b3ae9fd163ff5ad283b8e365`: OpenAPI generation fails because `logs_viewer` declares no response class, and `/api/capabilities` is absent. The smallest safe fix declares `HTMLResponse` at route registration, removes all browser delivery of `SCRAPER_API_TOKEN`, and adds a read-only, authenticated capability endpoint whose claims come only from known implementation/configuration state. Development and release must occur in an isolated worktree; this design does not authorize implementation, deployment, merge, or push.

## Glossary

- **Bug_Condition (C)**: An OpenAPI request reaches the invalid viewer route declaration, a protected viewer response would expose the server bearer, or a capability request reaches the missing route.
- **Property (P)**: OpenAPI and capability requests return valid contracts while no server bearer reaches browser content.
- **Preservation**: Existing API, authorization, scraping, data, listener, frontend fallback, and production branch behavior that must remain unchanged.
- **F / F'**: The unfixed backend behavior at the pinned commit / behavior after the isolated fix.
- **Server-only bearer**: `SCRAPER_API_TOKEN`, used by trusted server-to-server callers and never suitable for HTML, JavaScript, URLs, browser storage, or browser request headers.
- **Capability**: Static backend implementation/configuration readiness; it is not a live probe or uptime guarantee for an external auction provider.
- **Explicit Manheim configuration**: `MANHEIM_BACKEND_ENABLED=true` plus all required official-adapter configuration validated by a dedicated readiness helper; a flag alone cannot override missing requirements.
- **Consumer schema**: `auctionSourceCapabilitiesPayloadSchema` in `car-auction-buddy/src/lib/auction-sources.ts`.

## Bug Details

### Bug Condition

The combined input domain distinguishes schema generation, viewer rendering, and capability discovery. The defect holds when any corresponding contract is violated.

**Formal Specification:**

```
FUNCTION isBugCondition(input)
  INPUT: input of type ContractRequest
  OUTPUT: boolean

  IF input.kind = OPENAPI THEN
    RETURN route("/api/logs/viewer").responseClass IS None
           AND openapiGenerationRaisesResponseClassAssertion()
  ELSE IF input.kind = LOG_VIEWER THEN
    RETURN input.scraperApiToken IS configured
           AND browserResponseContains(input.scraperApiToken)
  ELSE IF input.kind = CAPABILITIES THEN
    RETURN route("/api/capabilities") IS absent
  END IF
  RETURN false
END FUNCTION

FUNCTION expectedBehavior(input, result)
  INPUT: input of type ContractRequest, result of type HTTPResult
  OUTPUT: boolean

  IF input.kind = OPENAPI THEN
    RETURN result.status = 200 AND isValidOpenApiJson(result.body)
  ELSE IF input.kind = LOG_VIEWER THEN
    RETURN NOT containsServerBearer(result) AND NOT browserConstructsServerBearer(result)
           AND (NOT input.protectedMode OR browserStreamFailsClosed(result))
  ELSE IF input.kind = CAPABILITIES THEN
    RETURN result.status = 200 AND matchesConsumerSchema(result.body)
           AND claimsFollowConfigurationOnly(result.body, input.configuration)
  END IF
  RETURN false
END FUNCTION
```

### Examples

- `GET /openapi.json` currently returns 500; after the fix it returns 200 JSON and documents `/api/logs/viewer` as HTML.
- With `SCRAPER_API_TOKEN=sentinel-secret`, the current viewer includes `sentinel-secret` in `const TOKEN`; after the fix no response byte or header contains it, and protected browser streaming is disabled unless separately secured.
- `GET /api/capabilities` currently returns 404; after the fix it returns all three required source keys in a schema-valid payload.
- With no Manheim opt-in or incomplete adapter settings, Manheim returns `available=false, mode="unavailable"`; it never inherits availability from Copart or IAAI.
- With a validated explicit Manheim official-adapter configuration, Manheim may return `available=true, mode="official_api"`; this does not assert upstream reachability.

## Expected Behavior

### Preservation Requirements

**Unchanged Behaviors:**

- `/api/logs/stream` retains `_require_bearer`; the fix must not weaken its authentication.
- Existing search, job, report, health, static UI, and scraper routes keep their current contracts.
- Copart and IAAI orchestration remains unchanged; capability calculation invokes no scraper and makes no external request.
- The consumer's 30-second cache and 404 legacy fallback remain unchanged because no frontend code is modified.
- SQLite files and schemas are untouched; tests use isolated process state and temporary files only if unavoidable.
- Uvicorn remains bound to `127.0.0.1:8000`.
- The active production checkout remains on `audit/kiro-20260719-0742`; work occurs in a new worktree from the pinned commit.

**Scope:**
All inputs outside OpenAPI generation, viewer HTML generation, and `GET /api/capabilities` are unaffected, including searches, job state, reports, database operations, external provider traffic, and frontend fallback against older deployments.

## Hypothesized Root Cause

1. **Invalid FastAPI route metadata**: `@app.get("/api/logs/viewer", response_class=None)` violates FastAPI's OpenAPI requirement even though the handler returns `HTMLResponse` at runtime.
   - Route registration metadata, not the handler return object, drives schema generation.
   - Import `HTMLResponse` with the other response classes and declare it in the decorator.

2. **Unsafe conflation of server and browser trust boundaries**: `logs_viewer` copies `SCRAPER_API_TOKEN` into JavaScript because browser `EventSource` cannot set custom headers.
   - Any browser receiving the page can inspect, log, cache, or exfiltrate the reusable server credential.
   - Replacing `EventSource` with `fetch` does not make disclosure safe.
   - Minimal safe behavior is fail-closed protected mode. A future browser viewer would require separate short-lived, scoped, HttpOnly authentication and is out of scope.

3. **Missing backend capability contract**: No `/api/capabilities` route or response model exists.
   - The frontend schema requires exactly `copart`, `iaai`, and `manheim` capability objects.
   - Its 404 fallback is intentionally legacy behavior, not the desired contract for this backend.

4. **Risk of optimistic capability claims**: A static payload could falsely advertise Manheim or external provider health.
   - The endpoint must use a pure configuration/readiness mapping and never probe providers.
   - Copart/IAAI `live` denotes implemented/configured backend support, not a real-time health assertion.
   - Manheim requires explicit opt-in and complete official-adapter readiness; otherwise it is unavailable.

## Correctness Properties

Property 1: Bug Condition - OpenAPI, Viewer Secret, and Capability Contracts

_For any_ contract request where `isBugCondition` returns true, the fixed backend SHALL satisfy `expectedBehavior`: OpenAPI returns a valid document, viewer output never transfers or constructs the server bearer and fails closed in protected mode, and capabilities returns a schema-valid, configuration-derived, non-secret payload with Manheim unavailable unless explicitly ready.

**Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8**

Property 2: Preservation - Production API and Safety Boundary

_For any_ request or operational state where `isBugCondition` returns false, the fixed backend SHALL produce the same externally observable behavior as the original backend while preserving bearer protection, search/scraper behavior, frontend fallback, database contents, loopback binding, active branch, and rollback capability.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8**

## Fix Implementation

### Changes Required

Assuming the root-cause analysis is confirmed by exploration tests:

**File**: `/home/dawid/usacar/usa-car-finder/api/main.py` in a new isolated worktree, never the active checkout.

**Functions/routes**: `logs_viewer`, new pure capability builder/readiness helper, and new `GET /api/capabilities` handler.

**Specific Changes**:

1. **Correct route metadata**: import `HTMLResponse` at module scope and set `response_class=HTMLResponse`; do not use `None`.
2. **Remove credential disclosure**: remove token interpolation, `const TOKEN`, and browser `Authorization: Bearer ...` construction.
3. **Fail closed in protected mode**: when the server bearer is configured, return a non-secret disabled/forbidden viewer response; retain an uncredentialed viewer only for explicit local unprotected mode. Do not add secrets to cookies, query strings, local/session storage, inline data, or redirects.
4. **Model the capability response**: add small Pydantic models or equivalently strict typed construction for `checkedAt`, source availability, allowed mode, and optional reason. Reasons must be stable, non-secret strings of at most 200 characters.
5. **Build claims conservatively**: use pure helpers based on implemented source registration and explicit configuration. Never contact Copart, IAAI, Manheim, SQLite, or scraper/session code from this endpoint.
6. **Gate Manheim**: use `MANHEIM_BACKEND_ENABLED=true` as explicit opt-in and require validated official-adapter settings before `official_api`; all other cases return `unavailable`. Do not invent credential names—first identify existing adapter requirements in the isolated worktree; if no official adapter exists, Manheim must remain unavailable regardless of the flag.
7. **Reuse authorization**: protect `/api/capabilities` with `Depends(_require_bearer)` consistent with other server APIs.
8. **Keep changes narrow**: add targeted tests under a new backend test module; do not alter frontend code, SQLite, source orchestration, bind settings, production checkout, or unrelated formatting.

## Testing Strategy

### Validation Approach

Use an isolated worktree and isolated virtual environment. First encode and run the expected contracts against the unfixed pinned commit, where Property 1 must fail with the known counterexamples. Then capture preservation behavior on the unfixed code, implement the narrow fix, and rerun the same tests. Tests must not start production Uvicorn, touch production SQLite, invoke lifespan workers, or contact external providers. If a property-testing library is needed, install a reviewed exact version only in the isolated test environment; do not add an unpinned production dependency.

### Exploratory Bug Condition Checking

**Goal**: Prove both defects and the secret exposure before implementation, then use the counterexamples to confirm or revise the hypotheses.

**Test Plan**: Import the pinned app without running lifespan workers, use direct `app.openapi()`/an in-process ASGI client, inject sentinel configuration, and validate the consumer-shaped JSON contract. Run on unfixed code and record exact failures.

**Test Cases**:

1. **OpenAPI declaration**: generate OpenAPI and expect valid JSON; unfixed code raises the known response-class assertion.
2. **Viewer sentinel secrecy**: configure a generated sentinel bearer and expect it absent from HTML and scripts; unfixed code exposes it.
3. **Capabilities presence**: request authorized `/api/capabilities` and expect 200/schema-valid JSON; unfixed code returns 404.
4. **Manheim default-deny**: generate false/missing/malformed opt-in combinations and expect unavailable; route absence is the initial counterexample.

**Expected Counterexamples**:

- `app.openapi()` raises `AssertionError: A response class is needed to generate OpenAPI`.
- A sentinel such as `server-only-sentinel` appears in viewer JavaScript and a browser Authorization header.
- `/api/capabilities` responds 404 instead of the required source map.

### Fix Checking

**Goal**: Verify all three variants of the combined bug condition.

**Pseudocode:**

```
FOR ALL input WHERE isBugCondition(input) DO
  result := fixedContractHandler(input)
  ASSERT expectedBehavior(input, result)
END FOR
```

Generate token strings containing quotes, markup, slashes, Unicode, and long random values; none may appear in any browser response. Generate all relevant source configuration combinations. Assert the exact mode constraints: Copart/IAAI can only be `live` when available; Manheim can only be `official_api` when available; every unavailable source uses `unavailable`.

### Preservation Checking

**Goal**: Compare unfixed and fixed behavior for non-bug-condition inputs and operational invariants.

**Pseudocode:**

```
FOR ALL input WHERE NOT isBugCondition(input) DO
  ASSERT normalize(F(input)) = normalize(F'(input))
END FOR
```

Normalize only nondeterministic timestamps/stream boundaries. Observe the unfixed baseline first for health, bearer rejection, representative existing route metadata, source defaults, and listener state. The capability builder must be proven side-effect-free by replacing network, scraper, and database entry points with fail-on-call sentinels.

**Test Cases**:

1. **Authorization preservation**: missing/invalid bearer remains rejected for protected routes; valid trusted authorization still passes.
2. **Route preservation**: representative health and existing API schema entries are unchanged aside from the new endpoint and corrected viewer response metadata.
3. **Side-effect preservation**: capability calls trigger no DB, scraper, browser, or network function.
4. **Frontend preservation**: existing car-auction-buddy schema/fallback tests pass without frontend changes.
5. **Operational preservation**: active checkout branch/commit and `127.0.0.1:8000` listener are recorded before and unchanged after isolated testing/release.

### Unit Tests

- Test `logs_viewer` response metadata and protected/unprotected rendering with sentinel secrets.
- Test a pure capability builder across Copart, IAAI, and Manheim configuration/readiness matrices.
- Test Pydantic/JSON output against the exact consumer fixture, allowed modes, bounded reasons, and UTC `checkedAt`.
- Test `_require_bearer` behavior for the new endpoint and preserved stream route.

### Property-Based Tests

- Generate arbitrary bearer values and prove no viewer response, header, redirect, script, URL, or storage expression contains them.
- Generate source support/enablement/readiness combinations and prove mode/availability invariants and Manheim default-deny.
- Generate non-bug API/configuration cases and compare normalized unfixed/fixed behavior.

### Integration Tests

- In-process request to `/openapi.json` returns 200 and includes both corrected routes without running lifespan workers.
- In-process authorized request to `/api/capabilities` matches a JSON fixture accepted by `auctionSourceCapabilitiesPayloadSchema`.
- Run the existing frontend `auction-sources` tests and a contract-fixture validation against the backend sample payload.
- On release candidate only, curl loopback health/OpenAPI/capabilities through the established trusted server-side authorization path; never print the bearer.

### Production Release and Rollback

1. **Preflight**: through `wsl2-cf-kiro`, record active branch, HEAD, dirty/untracked files, current release/process identity, loopback listener, `/health`, current 500/404 counterexamples, and a rollback reference. Do not clean or modify the listed untracked production files.
2. **Isolation**: create a separate worktree/release directory from the pinned commit on a new fix branch. Use separate test state; do not switch `/home/dawid/usacar` or modify SQLite.
3. **Candidate validation**: run exploration, preservation, unit, property, integration, import/compile, and frontend contract tests in isolation. Confirm no secret appears in logs or artifacts.
4. **Controlled cutover**: only after explicit deployment approval, use the existing process manager discovered during preflight. Preserve host `127.0.0.1`, port `8000`, environment ownership/permissions, and a readily selectable prior release. Do not merge or push.
5. **Postflight**: verify process stability, listener address, `/health`, `/openapi.json`, authorized/unauthorized capabilities behavior, Manheim default-deny, viewer non-disclosure, and representative existing APIs. Compare with preflight.
6. **Rollback trigger**: on any failed health, binding, auth, schema, secret, capability, or representative API check, immediately select the recorded prior release and restart via the same process manager; verify health and loopback binding again. Code rollback must not touch databases.
