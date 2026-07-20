// Server-only HTTP client for the Ubuntu FastAPI backend behind Cloudflare Access.
//
// Boundary rules enforced here:
// - MUST NOT be imported from client code (filename ends in `.server.ts`, which
//   scripts/check-server-imports.mjs and the Vite bundler block).
// - Env is validated at call time, never at module import — importing this file
//   in an isomorphic path must not throw.
// - Secrets (bearer token, CF Access client id/secret) are never returned to
//   callers, logged, or embedded in error messages.
// - The client does NOT ping Ubuntu at import time. Callers decide when to fetch.
//
// This module is additive: nothing in the runtime currently depends on it. It
// is the foundation for the Browser → Lovable BFF → Cloudflare Access → FastAPI
// migration (see docs/lovable-ubuntu-deployment.md and
// docs/ubuntu-api-contract.md). The legacy API_BASE_URL / SCRAPER_BASE_URL
// paths remain untouched until each screen is migrated.

const DEFAULT_TIMEOUT_MS = 15_000;
const DEFAULT_MAX_RESPONSE_BYTES = 10 * 1024 * 1024; // 10 MiB
const RETRYABLE_STATUS = new Set([502, 503, 504]);
const RETRYABLE_METHODS = new Set(["GET", "HEAD"]);
const RETRY_BACKOFF_MS = 250;

export type UbuntuApiErrorKind =
  | "unconfigured"
  | "timeout"
  | "network_error"
  | "access_denied"
  | "unauthorized"
  | "not_found"
  | "conflict"
  | "rate_limited"
  | "upstream_error"
  | "invalid_response";

export class UbuntuApiError extends Error {
  readonly kind: UbuntuApiErrorKind;
  readonly status: number | null;
  readonly requestId: string;

  constructor(
    kind: UbuntuApiErrorKind,
    message: string,
    requestId: string,
    status: number | null = null,
  ) {
    super(message);
    this.name = "UbuntuApiError";
    this.kind = kind;
    this.status = status;
    this.requestId = requestId;
  }
}

export type UbuntuApiConfig = {
  baseUrl: string;
  bearerToken: string;
  cfAccessClientId: string;
  cfAccessClientSecret: string;
};

export type UbuntuApiRequest<TBody = unknown> = {
  method?: "GET" | "HEAD" | "POST" | "PUT" | "PATCH" | "DELETE";
  path: string;
  query?: Record<string, string | number | boolean | undefined | null>;
  body?: TBody;
  headers?: Record<string, string>;
  responseType?: "json" | "text";
  timeoutMs?: number;
  maxResponseBytes?: number;
  /** Runtime validator applied to the parsed JSON body. Throw to mark invalid. */
  validate?: (raw: unknown) => void;
  /** Passed to fetch. Only used in tests to inject a mock. */
  fetchImpl?: typeof fetch;
};

export type UbuntuApiResponse<T> = {
  data: T;
  status: number;
  requestId: string;
  latencyMs: number;
};

type ProbeStatus = "ok" | "down" | "unconfigured";

export type UbuntuApiProbeResult = {
  status: ProbeStatus;
  latencyMs: number | null;
  requestId: string;
};

/**
 * Read config from env at CALL time. Returns null when any required env is
 * missing or malformed — never throws for a missing configuration, so callers
 * can degrade gracefully to "unconfigured".
 */
export function readUbuntuApiConfig(): UbuntuApiConfig | null {
  const rawBase = process.env.UBUNTU_API_BASE_URL;
  const bearer = process.env.UBUNTU_API_BEARER_TOKEN;
  const cfId = process.env.CF_ACCESS_CLIENT_ID;
  const cfSecret = process.env.CF_ACCESS_CLIENT_SECRET;
  if (!rawBase || !bearer || !cfId || !cfSecret) return null;

  const canonicalBase = canonicalizeBaseUrl(rawBase);
  if (!canonicalBase) return null;

  return {
    baseUrl: canonicalBase,
    bearerToken: bearer,
    cfAccessClientId: cfId,
    cfAccessClientSecret: cfSecret,
  };
}

export function isUbuntuApiConfigured(): boolean {
  return readUbuntuApiConfig() !== null;
}

/**
 * Enforce HTTPS, strip any embedded credentials, drop trailing slash.
 * Returns null when the input cannot be safely normalized.
 */
export function canonicalizeBaseUrl(input: string): string | null {
  let parsed: URL;
  try {
    parsed = new URL(input);
  } catch {
    return null;
  }
  if (parsed.protocol !== "https:") return null;
  if (parsed.username || parsed.password) return null;
  if (parsed.search || parsed.hash) return null;
  const pathname = parsed.pathname === "/" ? "" : parsed.pathname.replace(/\/+$/, "");
  return `${parsed.protocol}//${parsed.host}${pathname}`;
}

function generateRequestId(): string {
  // crypto.randomUUID is available under Workers (nodejs_compat) and Node ≥19.
  return crypto.randomUUID();
}

function buildUrl(baseUrl: string, path: string, query?: UbuntuApiRequest["query"]): string {
  const safePath = path.startsWith("/") ? path : `/${path}`;
  const url = new URL(`${baseUrl}${safePath}`);
  if (query) {
    for (const [k, v] of Object.entries(query)) {
      if (v === undefined || v === null) continue;
      url.searchParams.append(k, String(v));
    }
  }
  return url.toString();
}

function statusToKind(status: number): UbuntuApiErrorKind {
  if (status === 401) return "unauthorized";
  if (status === 403) return "access_denied";
  if (status === 404) return "not_found";
  if (status === 409) return "conflict";
  if (status === 429) return "rate_limited";
  return "upstream_error";
}

function publicMessage(kind: UbuntuApiErrorKind, status: number | null): string {
  // Generic messages only — never include URL, headers, tokens, request body,
  // or upstream response body.
  switch (kind) {
    case "unconfigured":
      return "Ubuntu API is not configured.";
    case "timeout":
      return "Ubuntu API request timed out.";
    case "network_error":
      return "Network error while contacting Ubuntu API.";
    case "unauthorized":
      return "Ubuntu API rejected the request credentials.";
    case "access_denied":
      return "Ubuntu API denied access to the resource.";
    case "not_found":
      return "The requested Ubuntu API resource was not found.";
    case "conflict":
      return "Ubuntu API reported a conflict for this request.";
    case "rate_limited":
      return "Ubuntu API rate limit exceeded.";
    case "invalid_response":
      return "Ubuntu API returned an unexpected response.";
    case "upstream_error":
    default:
      return status
        ? `Ubuntu API returned an error (status ${status}).`
        : "Ubuntu API returned an error.";
  }
}

async function readBodyWithLimit(response: Response, maxBytes: number): Promise<string> {
  const declared = response.headers.get("content-length");
  if (declared) {
    const declaredNumber = Number.parseInt(declared, 10);
    if (Number.isFinite(declaredNumber) && declaredNumber > maxBytes) {
      throw new Error("response_too_large");
    }
  }
  const body = response.body;
  if (!body) return "";
  const reader = body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    if (!value) continue;
    total += value.byteLength;
    if (total > maxBytes) {
      try {
        await reader.cancel();
      } catch {
        // ignore
      }
      throw new Error("response_too_large");
    }
    chunks.push(value);
  }
  const merged = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    merged.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return new TextDecoder("utf-8").decode(merged);
}

async function performRequest<T>(
  config: UbuntuApiConfig,
  request: UbuntuApiRequest<unknown>,
  requestId: string,
  attempt: number,
): Promise<UbuntuApiResponse<T>> {
  const method = (request.method ?? "GET").toUpperCase() as NonNullable<UbuntuApiRequest["method"]>;
  const responseType = request.responseType ?? "json";
  const timeoutMs = request.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  const maxBytes = request.maxResponseBytes ?? DEFAULT_MAX_RESPONSE_BYTES;
  const fetchImpl = request.fetchImpl ?? fetch;
  const url = buildUrl(config.baseUrl, request.path, request.query);
  const startedAt = Date.now();

  // Caller headers are applied first so authentication and correlation headers
  // cannot be replaced accidentally (or maliciously) by a higher-level adapter.
  const headers: Record<string, string> = {
    ...(request.headers ?? {}),
    Accept: responseType === "json" ? "application/json" : "text/html, */*",
    Authorization: `Bearer ${config.bearerToken}`,
    "CF-Access-Client-Id": config.cfAccessClientId,
    "CF-Access-Client-Secret": config.cfAccessClientSecret,
    "X-Request-Id": requestId,
  };

  let body: BodyInit | undefined;
  if (request.body !== undefined && method !== "GET" && method !== "HEAD") {
    body = JSON.stringify(request.body);
    headers["Content-Type"] = "application/json";
  }

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetchImpl(url, {
      method,
      headers,
      body,
      signal: controller.signal,
    });

    if (!response.ok) {
      const status = response.status;
      if (RETRYABLE_STATUS.has(status) && RETRYABLE_METHODS.has(method) && attempt === 0) {
        try {
          await response.body?.cancel();
        } catch {
          // Ignore cancellation failures; the retry remains bounded to one attempt.
        }
        await sleep(RETRY_BACKOFF_MS);
        return performRequest<T>(config, request, requestId, attempt + 1);
      }
      const kind = statusToKind(status);
      throw new UbuntuApiError(kind, publicMessage(kind, status), requestId, status);
    }

    let text: string;
    try {
      text = await readBodyWithLimit(response, maxBytes);
    } catch {
      if (controller.signal.aborted) {
        throw new UbuntuApiError("timeout", publicMessage("timeout", null), requestId);
      }
      throw new UbuntuApiError(
        "invalid_response",
        publicMessage("invalid_response", response.status),
        requestId,
        response.status,
      );
    }

    let parsed: unknown = responseType === "text" ? text : null;
    if (responseType === "json" && text.length > 0) {
      try {
        parsed = JSON.parse(text);
      } catch {
        throw new UbuntuApiError(
          "invalid_response",
          publicMessage("invalid_response", response.status),
          requestId,
          response.status,
        );
      }
    }

    if (request.validate) {
      try {
        request.validate(parsed);
      } catch {
        throw new UbuntuApiError(
          "invalid_response",
          publicMessage("invalid_response", response.status),
          requestId,
          response.status,
        );
      }
    }

    return {
      data: parsed as T,
      status: response.status,
      requestId,
      latencyMs: Date.now() - startedAt,
    };
  } catch (error) {
    if (error instanceof UbuntuApiError) throw error;

    const aborted =
      controller.signal.aborted || (error as { name?: string })?.name === "AbortError";
    const kind: UbuntuApiErrorKind = aborted ? "timeout" : "network_error";
    if (attempt === 0 && RETRYABLE_METHODS.has(method)) {
      await sleep(RETRY_BACKOFF_MS);
      return performRequest<T>(config, request, requestId, attempt + 1);
    }
    throw new UbuntuApiError(kind, publicMessage(kind, null), requestId);
  } finally {
    // Keep the deadline active through response streaming, not only until the
    // response headers arrive.
    clearTimeout(timer);
  }
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * Public entry point. Callers pass a typed request; the response body is
 * either validated by `validate` or returned as `unknown` (the T slot).
 * All failure modes surface as `UbuntuApiError` with sanitized messages.
 */
export async function ubuntuApiRequest<T = unknown>(
  request: UbuntuApiRequest,
): Promise<UbuntuApiResponse<T>> {
  const requestId = generateRequestId();
  const config = readUbuntuApiConfig();
  if (!config) {
    throw new UbuntuApiError("unconfigured", publicMessage("unconfigured", null), requestId);
  }
  return performRequest<T>(config, request, requestId, 0);
}

/**
 * Non-throwing probe for /api/health and diagnostics screens. Never leaks
 * URL, tokens, or upstream error bodies.
 */
export async function probeUbuntuApi(
  options: { path?: string; timeoutMs?: number; fetchImpl?: typeof fetch } = {},
): Promise<UbuntuApiProbeResult> {
  const requestId = generateRequestId();
  const config = readUbuntuApiConfig();
  if (!config) {
    return { status: "unconfigured", latencyMs: null, requestId };
  }
  const startedAt = Date.now();
  try {
    const result = await performRequest<unknown>(
      config,
      {
        method: "GET",
        path: options.path ?? "/health",
        timeoutMs: options.timeoutMs ?? 4_000,
        fetchImpl: options.fetchImpl,
      },
      requestId,
      0,
    );
    return { status: "ok", latencyMs: result.latencyMs, requestId };
  } catch {
    return { status: "down", latencyMs: Date.now() - startedAt, requestId };
  }
}
