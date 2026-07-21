# Bugfix Requirements Document

## Introduction

This bugfix restores two production contracts in the Ubuntu FastAPI backend at commit `ebf176d7f0d76636b3ae9fd163ff5ad283b8e365`: OpenAPI generation and auction-source capability discovery. It also closes the credential disclosure in the HTML log viewer without changing scraping behavior, databases, the active production branch, or the loopback-only network boundary.

## Bug Analysis

### Current Behavior (Defect)

The defects are reproducible through `wsl2-cf-kiro` against `127.0.0.1:8000`.

1.1 WHEN `GET /openapi.json` generates the application schema with `/api/logs/viewer` declared as `response_class=None` THEN the system returns HTTP 500 with `AssertionError: A response class is needed to generate OpenAPI`
1.2 WHEN the authenticated log viewer is rendered while `SCRAPER_API_TOKEN` is configured THEN the system embeds the server-only bearer in returned HTML/JavaScript and instructs the browser to send it to `/api/logs/stream`
1.3 WHEN car-auction-buddy requests `GET /api/capabilities` THEN the system returns HTTP 404 because the route is absent
1.4 WHEN the capabilities request returns 404 THEN the system forces car-auction-buddy to use its legacy environment-based fallback instead of an authoritative backend payload

### Expected Behavior (Correct)

The fix must be conservative: a capability means backend support/configuration, not proof that an external auction site is currently healthy.

2.1 WHEN `GET /openapi.json` is requested THEN the system SHALL return HTTP 200 with a valid OpenAPI JSON document that declares `/api/logs/viewer` with an HTML response class
2.2 WHEN `SCRAPER_API_TOKEN` is configured THEN the system SHALL keep that bearer server-only, omit it and browser-side bearer construction from every viewer response, and fail closed for browser streaming unless a separate browser-safe scoped authentication mechanism exists
2.3 WHEN `SCRAPER_API_TOKEN` is not configured for explicitly unprotected local development THEN the system SHALL allow the viewer to fetch the log stream without embedding or constructing a bearer credential
2.4 WHEN an authorized client requests `GET /api/capabilities` THEN the system SHALL return HTTP 200 with `checkedAt` and exactly the `copart`, `iaai`, and `manheim` entries accepted by `auctionSourceCapabilitiesPayloadSchema`
2.5 WHEN Copart or IAAI backend support is configured and implemented THEN the system SHALL report that source as `{available: true, mode: "live"}` as a configuration capability only; otherwise it SHALL report `{available: false, mode: "unavailable"}` with a non-secret reason
2.6 WHEN Manheim is not explicitly enabled or its official adapter requirements are incomplete THEN the system SHALL report Manheim as `{available: false, mode: "unavailable"}` and SHALL NOT infer availability from Copart/IAAI support
2.7 WHEN Manheim is explicitly enabled and its official adapter requirements are configured THEN the system SHALL report Manheim as `{available: true, mode: "official_api"}` without claiming live upstream health
2.8 WHEN bearer protection is configured THEN the system SHALL protect `/api/capabilities` with the existing bearer authorization behavior and SHALL return no secrets in its payload or reasons

### Unchanged Behavior (Regression Prevention)

The fix is contract-only and must preserve the production boundary.

3.1 WHEN the release is prepared or deployed THEN the system SHALL CONTINUE TO run Uvicorn on `127.0.0.1:8000`, never `0.0.0.0`
3.2 WHEN existing API routes other than the two corrected contracts are called THEN the system SHALL CONTINUE TO preserve their status codes, payloads, authentication, and side effects
3.3 WHEN `/api/logs/stream` is accessed while bearer protection is configured THEN the system SHALL CONTINUE TO reject missing or invalid credentials and accept valid server-side authorization
3.4 WHEN car-auction-buddy encounters an older backend that returns 404 for capabilities THEN the system SHALL CONTINUE TO use its existing legacy fallback; this backend fix SHALL NOT modify frontend fallback code
3.5 WHEN capability status is computed or tested THEN the system SHALL CONTINUE TO avoid external auction requests, scraper execution, and direct SQLite reads or writes
3.6 WHEN searches run after the fix THEN the system SHALL CONTINUE TO use the existing Copart/IAAI source selection and scraping implementations unchanged
3.7 WHEN implementation and release work occurs THEN the system SHALL CONTINUE TO leave `/home/dawid/usacar` on `audit/kiro-20260719-0742`, use an isolated worktree/release, and avoid merge or push unless explicitly requested
3.8 WHEN production is changed THEN the system SHALL CONTINUE TO require recorded pre/post health checks and a rollback to the recorded prior release if OpenAPI, health, authorization, binding, or capability checks fail
