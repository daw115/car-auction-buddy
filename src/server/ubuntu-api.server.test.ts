// Unit tests for the Ubuntu API client. All tests mock fetch — no real
// network activity, and no real Cloudflare Access or Ubuntu backend is
// contacted.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  canonicalizeBaseUrl,
  probeUbuntuApi,
  readUbuntuApiConfig,
  ubuntuApiRequest,
  UbuntuApiError,
} from "./ubuntu-api.server";

const BEARER = "bearer-token-value-shhh";
const CF_ID = "cf-access-client-id-value";
const CF_SECRET = "cf-access-client-secret-value";

function setEnv() {
  process.env.UBUNTU_API_BASE_URL = "https://ubuntu.example.org/api";
  process.env.UBUNTU_API_BEARER_TOKEN = BEARER;
  process.env.CF_ACCESS_CLIENT_ID = CF_ID;
  process.env.CF_ACCESS_CLIENT_SECRET = CF_SECRET;
}

function clearEnv() {
  delete process.env.UBUNTU_API_BASE_URL;
  delete process.env.UBUNTU_API_BEARER_TOKEN;
  delete process.env.CF_ACCESS_CLIENT_ID;
  delete process.env.CF_ACCESS_CLIENT_SECRET;
}

function jsonResponse(body: unknown, init?: ResponseInit): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "content-type": "application/json" },
    ...init,
  });
}

beforeEach(() => {
  clearEnv();
});

afterEach(() => {
  clearEnv();
  vi.restoreAllMocks();
});

describe("canonicalizeBaseUrl", () => {
  it("normalizes https URLs and strips trailing slash", () => {
    expect(canonicalizeBaseUrl("https://ubuntu.example.org/api/")).toBe(
      "https://ubuntu.example.org/api",
    );
  });
  it("rejects http", () => {
    expect(canonicalizeBaseUrl("http://ubuntu.example.org")).toBeNull();
  });
  it("rejects embedded credentials", () => {
    expect(canonicalizeBaseUrl("https://user:pass@ubuntu.example.org")).toBeNull();
  });
  it("rejects search/hash", () => {
    expect(canonicalizeBaseUrl("https://ubuntu.example.org/api?x=1")).toBeNull();
    expect(canonicalizeBaseUrl("https://ubuntu.example.org/api#frag")).toBeNull();
  });
  it("rejects malformed input", () => {
    expect(canonicalizeBaseUrl("not-a-url")).toBeNull();
  });
});

describe("readUbuntuApiConfig", () => {
  it("returns null when unconfigured", () => {
    expect(readUbuntuApiConfig()).toBeNull();
  });
  it("returns config when all envs present and valid", () => {
    setEnv();
    const config = readUbuntuApiConfig();
    expect(config).not.toBeNull();
    expect(config!.baseUrl).toBe("https://ubuntu.example.org/api");
  });
  it("returns null when base url is not https", () => {
    setEnv();
    process.env.UBUNTU_API_BASE_URL = "http://ubuntu.example.org";
    expect(readUbuntuApiConfig()).toBeNull();
  });
});

describe("ubuntuApiRequest", () => {
  it("throws unconfigured with no network activity when env is missing", async () => {
    const fetchImpl = vi.fn();
    await expect(
      ubuntuApiRequest({ path: "/health", fetchImpl: fetchImpl as unknown as typeof fetch }),
    ).rejects.toMatchObject({ kind: "unconfigured" });
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("sends server-only auth + CF Access headers, request id, accept json", async () => {
    setEnv();
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse({ ok: true }));
    await ubuntuApiRequest({ path: "/health", fetchImpl: fetchImpl as unknown as typeof fetch });
    expect(fetchImpl).toHaveBeenCalledTimes(1);
    const [url, init] = fetchImpl.mock.calls[0];
    expect(url).toBe("https://ubuntu.example.org/api/health");
    const headers = (init as RequestInit).headers as Record<string, string>;
    expect(headers.Authorization).toBe(`Bearer ${BEARER}`);
    expect(headers["CF-Access-Client-Id"]).toBe(CF_ID);
    expect(headers["CF-Access-Client-Secret"]).toBe(CF_SECRET);
    expect(headers.Accept).toBe("application/json");
    expect(headers["X-Request-Id"]).toMatch(/^[0-9a-f-]{36}$/);
  });

  it("retries GET once on 503 then succeeds", async () => {
    setEnv();
    const fetchImpl = vi
      .fn()
      .mockResolvedValueOnce(new Response("bad", { status: 503 }))
      .mockResolvedValueOnce(jsonResponse({ ok: true }));
    const result = await ubuntuApiRequest({
      path: "/health",
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });
    expect(fetchImpl).toHaveBeenCalledTimes(2);
    expect(result.data).toEqual({ ok: true });
  });

  it("does NOT retry POST on 503", async () => {
    setEnv();
    const fetchImpl = vi.fn().mockResolvedValue(new Response("bad", { status: 503 }));
    await expect(
      ubuntuApiRequest({
        method: "POST",
        path: "/jobs",
        body: { a: 1 },
        fetchImpl: fetchImpl as unknown as typeof fetch,
      }),
    ).rejects.toMatchObject({ kind: "upstream_error", status: 503 });
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  it("does NOT retry GET on 4xx", async () => {
    setEnv();
    const fetchImpl = vi.fn().mockResolvedValue(new Response("nope", { status: 404 }));
    await expect(
      ubuntuApiRequest({ path: "/missing", fetchImpl: fetchImpl as unknown as typeof fetch }),
    ).rejects.toMatchObject({ kind: "not_found", status: 404 });
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  it("times out and surfaces a sanitized error", async () => {
    setEnv();
    const fetchImpl = vi.fn().mockImplementation((_url, init: RequestInit) => {
      return new Promise((_resolve, reject) => {
        const signal = init.signal as AbortSignal;
        signal.addEventListener("abort", () => {
          const err = new Error("aborted");
          (err as { name?: string }).name = "AbortError";
          reject(err);
        });
      });
    });
    await expect(
      ubuntuApiRequest({
        path: "/health",
        timeoutMs: 20,
        fetchImpl: fetchImpl as unknown as typeof fetch,
      }),
    ).rejects.toMatchObject({ kind: "timeout" });
    // network_error + timeout both retry GET once, so 2 calls
    expect(fetchImpl).toHaveBeenCalledTimes(2);
  });

  it("rejects when Content-Length exceeds the max response size", async () => {
    setEnv();
    const fetchImpl = vi.fn().mockResolvedValue(
      new Response("x", {
        status: 200,
        headers: {
          "content-type": "application/json",
          "content-length": String(20 * 1024 * 1024),
        },
      }),
    );
    await expect(
      ubuntuApiRequest({
        path: "/big",
        fetchImpl: fetchImpl as unknown as typeof fetch,
      }),
    ).rejects.toMatchObject({ kind: "invalid_response" });
  });

  it("rejects when streamed bytes exceed the max response size", async () => {
    setEnv();
    const bigPayload = new Uint8Array(1024);
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        for (let i = 0; i < 20; i++) controller.enqueue(bigPayload);
        controller.close();
      },
    });
    const fetchImpl = vi
      .fn()
      .mockResolvedValue(
        new Response(stream, { status: 200, headers: { "content-type": "application/json" } }),
      );
    await expect(
      ubuntuApiRequest({
        path: "/streamed",
        maxResponseBytes: 4 * 1024,
        fetchImpl: fetchImpl as unknown as typeof fetch,
      }),
    ).rejects.toMatchObject({ kind: "invalid_response" });
  });

  it("sanitizes error messages — no bearer, no CF Access secret, no URL", async () => {
    setEnv();
    const fetchImpl = vi
      .fn()
      .mockResolvedValue(new Response("secret upstream body", { status: 401 }));
    await expect(
      ubuntuApiRequest({ path: "/secure", fetchImpl: fetchImpl as unknown as typeof fetch }),
    ).rejects.toSatisfy((err: unknown) => {
      if (!(err instanceof UbuntuApiError)) return false;
      return (
        !err.message.includes(BEARER) &&
        !err.message.includes(CF_ID) &&
        !err.message.includes(CF_SECRET) &&
        !err.message.includes("ubuntu.example.org") &&
        !err.message.includes("secret upstream body") &&
        err.kind === "unauthorized"
      );
    });
  });

  it("marks invalid_response when body is not JSON", async () => {
    setEnv();
    const fetchImpl = vi
      .fn()
      .mockResolvedValue(
        new Response("not json", { status: 200, headers: { "content-type": "application/json" } }),
      );
    await expect(
      ubuntuApiRequest({ path: "/bad", fetchImpl: fetchImpl as unknown as typeof fetch }),
    ).rejects.toMatchObject({ kind: "invalid_response" });
  });

  it("runs the validator and surfaces invalid_response when it throws", async () => {
    setEnv();
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse({ wrong: true }));
    await expect(
      ubuntuApiRequest({
        path: "/validated",
        validate: () => {
          throw new Error("shape mismatch");
        },
        fetchImpl: fetchImpl as unknown as typeof fetch,
      }),
    ).rejects.toMatchObject({ kind: "invalid_response" });
  });
});

describe("probeUbuntuApi", () => {
  it("returns unconfigured with no network activity", async () => {
    const fetchImpl = vi.fn();
    const result = await probeUbuntuApi({ fetchImpl: fetchImpl as unknown as typeof fetch });
    expect(result.status).toBe("unconfigured");
    expect(result.latencyMs).toBeNull();
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("returns ok on 200", async () => {
    setEnv();
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse({ ok: true }));
    const result = await probeUbuntuApi({ fetchImpl: fetchImpl as unknown as typeof fetch });
    expect(result.status).toBe("ok");
    expect(typeof result.latencyMs).toBe("number");
  });

  it("returns down on upstream error, without throwing", async () => {
    setEnv();
    const fetchImpl = vi.fn().mockResolvedValue(new Response("no", { status: 500 }));
    const result = await probeUbuntuApi({ fetchImpl: fetchImpl as unknown as typeof fetch });
    expect(result.status).toBe("down");
  });
});

describe("request hardening", () => {
  it("does not allow callers to override authentication or request-id headers", async () => {
    setEnv();
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse({ ok: true }));

    await ubuntuApiRequest({
      path: "/health",
      headers: {
        Authorization: "Bearer attacker-controlled",
        "CF-Access-Client-Id": "attacker-id",
        "CF-Access-Client-Secret": "attacker-secret",
        "X-Request-Id": "attacker-request-id",
        "X-Custom-Header": "allowed",
      },
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });

    const [, init] = fetchImpl.mock.calls[0];
    const headers = (init as RequestInit).headers as Record<string, string>;
    expect(headers.Authorization).toBe(`Bearer ${BEARER}`);
    expect(headers["CF-Access-Client-Id"]).toBe(CF_ID);
    expect(headers["CF-Access-Client-Secret"]).toBe(CF_SECRET);
    expect(headers["X-Request-Id"]).toMatch(/^[0-9a-f-]{36}$/);
    expect(headers["X-Custom-Header"]).toBe("allowed");
  });

  it("keeps the timeout active while streaming the response body", async () => {
    setEnv();
    const fetchImpl = vi.fn().mockImplementation((_url, init: RequestInit) => {
      let streamController: ReadableStreamDefaultController<Uint8Array>;
      const stream = new ReadableStream<Uint8Array>({
        start(controller) {
          streamController = controller;
        },
      });
      (init.signal as AbortSignal).addEventListener("abort", () => {
        streamController.error(Object.assign(new Error("aborted"), { name: "AbortError" }));
      });
      return Promise.resolve(
        new Response(stream, { status: 200, headers: { "content-type": "application/json" } }),
      );
    });

    await expect(
      ubuntuApiRequest({
        path: "/slow-body",
        timeoutMs: 20,
        fetchImpl: fetchImpl as unknown as typeof fetch,
      }),
    ).rejects.toMatchObject({ kind: "timeout" });
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });
});

describe("text responses", () => {
  it("returns text without JSON parsing while preserving server-only headers", async () => {
    setEnv();
    const fetchImpl = vi.fn().mockResolvedValue(
      new Response("<html>safe report</html>", {
        status: 200,
        headers: { "content-type": "text/html" },
      }),
    );

    const result = await ubuntuApiRequest<string>({
      path: "/report/client",
      responseType: "text",
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });

    expect(result.data).toBe("<html>safe report</html>");
    const [, init] = fetchImpl.mock.calls[0];
    const headers = (init as RequestInit).headers as Record<string, string>;
    expect(headers.Accept).toBe("text/html, */*");
    expect(headers.Authorization).toBe(`Bearer ${BEARER}`);
  });
});
