import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  callGemini,
  DEFAULT_GEMINI_MODEL,
  GEMINI_CONNECTION_TEST_TIMEOUT_MS,
  GEMINI_MODELS,
  resolveGeminiModel,
  testGeminiConnection,
} from "./gemini.server";

const TEST_API_KEY = "test-gemini-api-key";
const originalEnv = { ...process.env };
const fetchMock = vi.fn<typeof fetch>();

beforeEach(() => {
  process.env = { ...originalEnv, GEMINI_API_KEY: TEST_API_KEY };
  delete process.env.GEMINI_MODEL;
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  process.env = { ...originalEnv };
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("resolveGeminiModel", () => {
  it("uses the stable default model", () => {
    expect(resolveGeminiModel()).toBe(DEFAULT_GEMINI_MODEL);
    expect(GEMINI_MODELS).toContain(DEFAULT_GEMINI_MODEL);
  });

  it("rejects models outside the server allowlist", () => {
    expect(() => resolveGeminiModel("gemini-untrusted/../model")).toThrow(
      "Nieobsługiwany model Gemini",
    );
  });
});

describe("callGemini", () => {
  it("requires a server-side API key", async () => {
    delete process.env.GEMINI_API_KEY;

    await expect(callGemini({ system: "system", userPrompt: "prompt" })).rejects.toThrow(
      "Brak GEMINI_API_KEY",
    );
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("sends the key only in x-goog-api-key and maps the response", async () => {
    fetchMock.mockResolvedValue(
      new Response(
        JSON.stringify({
          candidates: [
            {
              content: { parts: [{ text: "pierwsza" }, { text: " odpowiedź" }] },
              finishReason: "STOP",
            },
          ],
          usageMetadata: { promptTokenCount: 4, candidatesTokenCount: 2 },
          modelVersion: "gemini-2.5-flash-001",
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      ),
    );

    const result = await callGemini({
      system: "system",
      userPrompt: "prompt",
      maxTokens: 128,
    });

    expect(result).toEqual({
      text: "pierwsza odpowiedź",
      model: "gemini-2.5-flash-001",
      usage: { input_tokens: 4, output_tokens: 2 },
      stop_reason: "STOP",
    });
    expect(fetchMock).toHaveBeenCalledOnce();

    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toBe(
      `https://generativelanguage.googleapis.com/v1beta/models/${DEFAULT_GEMINI_MODEL}:generateContent`,
    );
    expect(String(url)).not.toContain(TEST_API_KEY);
    const headers = new Headers(init?.headers);
    expect(headers.get("x-goog-api-key")).toBe(TEST_API_KEY);
    expect(headers.get("content-type")).toBe("application/json");

    const body = JSON.parse(String(init?.body));
    expect(body.generationConfig.maxOutputTokens).toBe(128);
    expect(body.systemInstruction.parts[0].text).toBe("system");
  });

  it("does not expose response details or the API key in errors", async () => {
    fetchMock.mockResolvedValue(new Response("sensitive-provider-response", { status: 404 }));

    const request = callGemini({ system: "system", userPrompt: "prompt" });

    await expect(request).rejects.toThrow(
      "Gemini: HTTP 404: model jest niedostępny dla tego klucza API",
    );
    await expect(request).rejects.not.toThrow("sensitive-provider-response");
    await expect(request).rejects.not.toThrow(TEST_API_KEY);
  });
});

describe("testGeminiConnection", () => {
  it("uses the production transport with a minimal output budget", async () => {
    fetchMock.mockResolvedValue(
      new Response(
        JSON.stringify({
          candidates: [{ content: { parts: [{ text: "pong" }] } }],
          usageMetadata: { promptTokenCount: 3, candidatesTokenCount: 1 },
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      ),
    );

    const result = await testGeminiConnection("gemini-3.5-flash");

    expect(result.text).toBe("pong");
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/gemini-3.5-flash:generateContent");
    const body = JSON.parse(String(init?.body));
    expect(body.generationConfig.maxOutputTokens).toBe(512);
    expect(GEMINI_CONNECTION_TEST_TIMEOUT_MS).toBe(30_000);
  });

  it("limits an interactive connection test to one retry", async () => {
    vi.useFakeTimers();
    vi.spyOn(Math, "random").mockReturnValue(0);
    fetchMock.mockResolvedValue(new Response("", { status: 429 }));

    const request = testGeminiConnection();
    const rejection = expect(request).rejects.toThrow("po 1 ponowieniach");

    await vi.advanceTimersByTimeAsync(500);
    await rejection;
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
