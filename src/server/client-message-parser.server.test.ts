import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  DEFAULT_CLIENT_MESSAGE_PARSER_TIMEOUT_MS,
  MAX_CLIENT_MESSAGE_PARSER_RESPONSE_BYTES,
  parseClientMessageServer,
} from "./client-message-parser.server";

const originalEnv = { ...process.env };
const fetchMock = vi.fn<typeof fetch>();

const VALID_RESPONSE = {
  criteria: {
    make: "Toyota",
    model: "Camry",
    year_from: 2020,
    year_to: 2023,
    budget_usd: 25_000,
    max_odometer_mi: 80_000,
    fuel_type: "Hybrid",
    excluded_damage_types: ["Flood"],
    allowed_damage_types: ["Hail"],
    sources: ["copart"],
    max_results: 25,
  },
  criteria_list: [
    {
      make: "Toyota",
      model: "Camry",
      year_from: 2020,
      budget_usd: 25_000,
    },
  ],
  summary: "Toyota Camry 2020-2023 do 25 000 USD",
  warnings: ["Zweryfikuj historię pojazdu."],
};

beforeEach(() => {
  process.env = {
    ...originalEnv,
    SCRAPER_BASE_URL: "http://127.0.0.1:8000/",
    SCRAPER_API_TOKEN: "test-scraper-token",
    SCRAPER_PARSER_TIMEOUT_MS: "10000",
  };
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  process.env = { ...originalEnv };
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

async function rejectionMessage(promise: Promise<unknown>): Promise<string> {
  try {
    await promise;
    throw new Error("expected promise to reject");
  } catch (error) {
    return error instanceof Error ? error.message : String(error);
  }
}

describe("parseClientMessageServer", () => {
  it("validates input and maps an authenticated parser response", async () => {
    fetchMock.mockResolvedValue(Response.json(VALID_RESPONSE));

    const result = await parseClientMessageServer({ message: "  Toyota Camry od 2020  " });

    expect(result).toEqual(VALID_RESPONSE);
    expect(fetchMock).toHaveBeenCalledOnce();
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toBe("http://127.0.0.1:8000/api/parse-client-message");
    expect(init?.method).toBe("POST");
    const headers = new Headers(init?.headers);
    expect(headers.get("accept")).toBe("application/json");
    expect(headers.get("authorization")).toBe("Bearer test-scraper-token");
    expect(headers.get("content-type")).toBe("application/json");
    expect(JSON.parse(String(init?.body))).toEqual({ message: "Toyota Camry od 2020" });
  });

  it.each([
    { message: "" },
    { message: "x".repeat(5_001) },
    { message: "Toyota", unexpected: true },
  ])("rejects invalid or non-strict input before fetch", async (input) => {
    await expect(parseClientMessageServer(input)).rejects.toThrow();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("redacts the reported INVALID_API_KEY diagnostics from HTTP errors", async () => {
    const privateBody = JSON.stringify({
      detail:
        "LLM niedostępny: Wszyscy providers failed: Error code: 401 - INVALID_API_KEY Invalid API key",
    });
    fetchMock.mockResolvedValue(new Response(privateBody, { status: 503 }));

    const message = await rejectionMessage(parseClientMessageServer({ message: "Toyota Camry" }));

    expect(message).toBe("Parser wiadomości: backend zwrócił HTTP 503.");
    expect(message).not.toContain("INVALID_API_KEY");
    expect(message).not.toContain("providers failed");
    expect(message).not.toContain("Invalid API key");
    expect(message).not.toContain("test-scraper-token");
  });

  it("does not wait for cancellation of a rejected HTTP body", async () => {
    let cancelCalled = false;
    const body = new ReadableStream<Uint8Array>({
      cancel() {
        cancelCalled = true;
        return new Promise<void>(() => undefined);
      },
    });
    fetchMock.mockResolvedValue(new Response(body, { status: 503 }));

    await expect(parseClientMessageServer({ message: "Toyota" })).rejects.toThrow(
      "Parser wiadomości: backend zwrócił HTTP 503.",
    );
    expect(cancelCalled).toBe(true);
  });

  it("rejects malformed JSON without exposing response contents", async () => {
    fetchMock.mockResolvedValue(new Response("private malformed response"));

    const message = await rejectionMessage(parseClientMessageServer({ message: "Toyota" }));

    expect(message).toBe("Parser wiadomości: backend zwrócił niepoprawny JSON.");
    expect(message).not.toContain("private malformed response");
  });

  it.each([
    { ...VALID_RESPONSE, criteria: { make: "" } },
    { ...VALID_RESPONSE, warnings: ["x".repeat(1_001)] },
    { ...VALID_RESPONSE, internal_provider_details: "private" },
  ])("rejects an invalid or non-strict response contract", async (response) => {
    fetchMock.mockResolvedValue(Response.json(response));

    await expect(parseClientMessageServer({ message: "Toyota" })).rejects.toThrow(
      "Parser wiadomości: backend zwrócił dane w nieprawidłowym formacie.",
    );
  });

  it("rejects a response declared above the byte limit", async () => {
    fetchMock.mockResolvedValue(
      new Response("{}", {
        headers: {
          "content-length": String(MAX_CLIENT_MESSAGE_PARSER_RESPONSE_BYTES + 1),
        },
      }),
    );

    await expect(parseClientMessageServer({ message: "Toyota" })).rejects.toThrow(
      "Parser wiadomości: odpowiedź backendu przekracza dozwolony limit.",
    );
  });

  it("rejects a streamed response that crosses the byte limit", async () => {
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(new Uint8Array(MAX_CLIENT_MESSAGE_PARSER_RESPONSE_BYTES + 1));
        controller.close();
      },
    });
    fetchMock.mockResolvedValue(new Response(body));

    await expect(parseClientMessageServer({ message: "Toyota" })).rejects.toThrow(
      "Parser wiadomości: odpowiedź backendu przekracza dozwolony limit.",
    );
  });

  it("does not wait for cancellation of an oversized stream", async () => {
    let cancelCalled = false;
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(new Uint8Array(MAX_CLIENT_MESSAGE_PARSER_RESPONSE_BYTES + 1));
      },
      cancel() {
        cancelCalled = true;
        return new Promise<void>(() => undefined);
      },
    });
    fetchMock.mockResolvedValue(new Response(body));

    await expect(parseClientMessageServer({ message: "Toyota" })).rejects.toThrow(
      "Parser wiadomości: odpowiedź backendu przekracza dozwolony limit.",
    );
    expect(cancelCalled).toBe(true);
  });

  it("aborts a request before headers at the configured deadline", async () => {
    vi.useFakeTimers();
    process.env.SCRAPER_PARSER_TIMEOUT_MS = "1000";
    fetchMock.mockImplementation(
      (_input, init) =>
        new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () => {
            reject(new DOMException("private abort details", "AbortError"));
          });
        }),
    );

    const request = parseClientMessageServer({ message: "Toyota" });
    const rejection = expect(request).rejects.toThrow(
      "Parser wiadomości: przekroczono czas oczekiwania 1000 ms.",
    );

    await vi.advanceTimersByTimeAsync(1_000);
    await rejection;
  });

  it("aborts a hanging response body at the configured deadline", async () => {
    vi.useFakeTimers();
    process.env.SCRAPER_PARSER_TIMEOUT_MS = "1000";
    let cancelReason: unknown;
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(new TextEncoder().encode('{"criteria":'));
      },
      cancel(reason) {
        cancelReason = reason;
        return new Promise<void>(() => undefined);
      },
    });
    fetchMock.mockResolvedValue(new Response(body));

    const request = parseClientMessageServer({ message: "Toyota" });
    const rejection = expect(request).rejects.toThrow(
      "Parser wiadomości: przekroczono czas oczekiwania 1000 ms.",
    );

    await vi.advanceTimersByTimeAsync(1_000);
    await rejection;
    expect(cancelReason).toBe("client message parser deadline exceeded");
  });

  it("maps network failures to a stable redacted error", async () => {
    fetchMock.mockRejectedValue(new Error("connect failed at private.internal"));

    const message = await rejectionMessage(parseClientMessageServer({ message: "Toyota" }));

    expect(message).toBe("Parser wiadomości: backend jest niedostępny.");
    expect(message).not.toContain("private.internal");
  });

  it("uses the ten-second default timeout", async () => {
    vi.useFakeTimers();
    delete process.env.SCRAPER_PARSER_TIMEOUT_MS;
    fetchMock.mockImplementation(
      (_input, init) =>
        new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () => {
            reject(new DOMException("Aborted", "AbortError"));
          });
        }),
    );

    const request = parseClientMessageServer({ message: "Toyota" });
    const rejection = expect(request).rejects.toThrow(
      `Parser wiadomości: przekroczono czas oczekiwania ${DEFAULT_CLIENT_MESSAGE_PARSER_TIMEOUT_MS} ms.`,
    );

    await vi.advanceTimersByTimeAsync(DEFAULT_CLIENT_MESSAGE_PARSER_TIMEOUT_MS);
    await rejection;
  });
});

describe("client message parser configuration", () => {
  it.each([
    "ftp://example.com",
    "https://user:password@example.com",
    "https://example.com/private-path",
    "https://example.com?token=private",
  ])("rejects an unsafe SCRAPER_BASE_URL before fetch", async (baseUrl) => {
    process.env.SCRAPER_BASE_URL = baseUrl;

    await expect(parseClientMessageServer({ message: "Toyota" })).rejects.toThrow(
      "SCRAPER_BASE_URL musi być dokładnym originem HTTP(S)",
    );
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("requires a scraper API token before fetch", async () => {
    delete process.env.SCRAPER_API_TOKEN;

    await expect(parseClientMessageServer({ message: "Toyota" })).rejects.toThrow(
      "SCRAPER_API_TOKEN nie jest ustawiony.",
    );
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("rejects an invalid parser timeout before fetch", async () => {
    process.env.SCRAPER_PARSER_TIMEOUT_MS = "999";

    await expect(parseClientMessageServer({ message: "Toyota" })).rejects.toThrow(
      "SCRAPER_PARSER_TIMEOUT_MS musi być liczbą całkowitą od 1000 do 60000.",
    );
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
