import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  createQueueWatch,
  deleteQueueWatch,
  listQueueWatches,
  MAX_SCRAPER_QUEUE_RESPONSE_BYTES,
} from "./scraper-queue.server";

const originalEnv = { ...process.env };
const fetchMock = vi.fn<typeof fetch>();

const VALID_INPUT = {
  search: {
    criteria: {
      make: "Toyota",
      model: "Camry",
      year_from: 2020,
      budget_usd: 25_000,
      sources: ["copart"],
    },
    disable_auction_filter: false,
  },
  interval_hours: 12,
  label: "Toyota Camry",
};

const VALID_WATCH = {
  id: "watch-123",
  label: "Toyota Camry",
  interval_hours: 12,
  next_run_at: "2026-07-17T12:00:00Z",
  runs_count: 0,
  last_result_count: null,
  status: "active",
};

beforeEach(() => {
  process.env = {
    ...originalEnv,
    SCRAPER_BASE_URL: "http://127.0.0.1:8000/",
    SCRAPER_API_TOKEN: "test-scraper-token",
    SCRAPER_QUEUE_TIMEOUT_MS: "10000",
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

describe("createQueueWatch", () => {
  it("validates the input and maps an authenticated POST response", async () => {
    fetchMock.mockResolvedValue(
      Response.json({ ...VALID_WATCH, ignored_upstream_field: "not forwarded" }),
    );

    const result = await createQueueWatch(VALID_INPUT);

    expect(result).toEqual(VALID_WATCH);
    expect(result).not.toHaveProperty("ignored_upstream_field");
    expect(fetchMock).toHaveBeenCalledOnce();

    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toBe("http://127.0.0.1:8000/api/queue");
    expect(init?.method).toBe("POST");
    expect(new Headers(init?.headers).get("authorization")).toBe("Bearer test-scraper-token");
    expect(JSON.parse(String(init?.body))).toEqual(VALID_INPUT);
  });

  it("rejects unknown criteria before making an outbound request", async () => {
    const input = {
      ...VALID_INPUT,
      search: {
        ...VALID_INPUT.search,
        criteria: { ...VALID_INPUT.search.criteria, unexpected: "value" },
      },
    };

    await expect(createQueueWatch(input)).rejects.toThrow(/unrecognized key/i);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("rejects an invalid watch contract", async () => {
    fetchMock.mockResolvedValue(Response.json({ ...VALID_WATCH, interval_hours: 0 }));

    await expect(createQueueWatch(VALID_INPUT)).rejects.toThrow(
      "Queue: scraper zwrócił dane w nieprawidłowym formacie.",
    );
  });
});

describe("listQueueWatches", () => {
  it("validates the list response", async () => {
    fetchMock.mockResolvedValue(
      Response.json({ watches: [VALID_WATCH], count: 1, internal: "ignored" }),
    );

    await expect(listQueueWatches()).resolves.toEqual({
      watches: [VALID_WATCH],
      count: 1,
    });
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toBe("http://127.0.0.1:8000/api/queue");
    expect(init?.method).toBe("GET");
  });

  it("rejects malformed JSON without returning its contents", async () => {
    fetchMock.mockResolvedValue(new Response("private malformed body"));

    const message = await rejectionMessage(listQueueWatches());

    expect(message).toBe("Queue: scraper zwrócił niepoprawny JSON.");
    expect(message).not.toContain("private malformed body");
  });

  it("rejects a response declared above the byte limit", async () => {
    fetchMock.mockResolvedValue(
      new Response("{}", {
        headers: {
          "content-length": String(MAX_SCRAPER_QUEUE_RESPONSE_BYTES + 1),
        },
      }),
    );

    await expect(listQueueWatches()).rejects.toThrow(
      "Queue: odpowiedź scrapera przekracza dozwolony limit.",
    );
  });

  it("rejects a streamed response that crosses the byte limit", async () => {
    const oversizedChunk = new Uint8Array(MAX_SCRAPER_QUEUE_RESPONSE_BYTES + 1);
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(oversizedChunk);
        controller.close();
      },
    });
    fetchMock.mockResolvedValue(new Response(body));

    await expect(listQueueWatches()).rejects.toThrow(
      "Queue: odpowiedź scrapera przekracza dozwolony limit.",
    );
  });

  it("keeps the byte-limit error stable when stream cancellation fails", async () => {
    let cancelCalled = false;
    const oversizedChunk = new Uint8Array(MAX_SCRAPER_QUEUE_RESPONSE_BYTES + 1);
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(oversizedChunk);
      },
      cancel() {
        cancelCalled = true;
        return Promise.reject(new Error("cancel failed with private details"));
      },
    });
    fetchMock.mockResolvedValue(new Response(body));

    const message = await rejectionMessage(listQueueWatches());

    expect(message).toBe("Queue: odpowiedź scrapera przekracza dozwolony limit.");
    expect(message).not.toContain("private details");
    expect(cancelCalled).toBe(true);
  });

  it("redacts upstream error bodies and credentials", async () => {
    fetchMock.mockResolvedValue(
      new Response("database details test-scraper-token", { status: 500 }),
    );

    const message = await rejectionMessage(listQueueWatches());

    expect(message).toBe("Queue: scraper zwrócił HTTP 500.");
    expect(message).not.toContain("database details");
    expect(message).not.toContain("test-scraper-token");
  });

  it("aborts a request at the configured deadline", async () => {
    vi.useFakeTimers();
    process.env.SCRAPER_QUEUE_TIMEOUT_MS = "1000";
    fetchMock.mockImplementation(
      (_input, init) =>
        new Promise<Response>((_resolve, reject) => {
          const signal = init?.signal;
          signal?.addEventListener("abort", () => {
            reject(new DOMException("Aborted", "AbortError"));
          });
        }),
    );

    const request = listQueueWatches();
    const rejection = expect(request).rejects.toThrow(
      "Queue: scraper nie odpowiedział w ciągu 1000 ms.",
    );

    await vi.advanceTimersByTimeAsync(1000);
    await rejection;
    expect(fetchMock).toHaveBeenCalledOnce();
  });

  it("aborts a hanging response body at the configured deadline", async () => {
    vi.useFakeTimers();
    process.env.SCRAPER_QUEUE_TIMEOUT_MS = "1000";
    let cancelReason: unknown;
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(new TextEncoder().encode('{"watches":['));
      },
      cancel(reason) {
        cancelReason = reason;
      },
    });
    fetchMock.mockResolvedValue(new Response(body));

    const request = listQueueWatches();
    const rejection = expect(request).rejects.toThrow(
      "Queue: scraper nie odpowiedział w ciągu 1000 ms.",
    );

    await vi.advanceTimersByTimeAsync(1000);
    await rejection;
    expect(cancelReason).toBe("queue request deadline exceeded");
  });

  it("maps network failures to a stable error", async () => {
    fetchMock.mockRejectedValue(new Error("connect ECONNREFUSED secret-host"));

    const message = await rejectionMessage(listQueueWatches());

    expect(message).toBe("Queue: scraper jest niedostępny.");
    expect(message).not.toContain("secret-host");
  });
});

describe("deleteQueueWatch", () => {
  it("encodes the identifier and treats 404 as an idempotent success", async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 404 }));

    await expect(deleteQueueWatch("watch/with space")).resolves.toEqual({ ok: true });
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toBe("http://127.0.0.1:8000/api/queue/watch%2Fwith%20space");
    expect(init?.method).toBe("DELETE");
  });

  it("rejects non-404 HTTP errors without reading their body", async () => {
    fetchMock.mockResolvedValue(new Response("private delete error", { status: 401 }));

    const message = await rejectionMessage(deleteQueueWatch("watch-123"));

    expect(message).toBe("Queue: scraper zwrócił HTTP 401.");
    expect(message).not.toContain("private delete error");
  });
});

describe("scraper queue configuration", () => {
  it("rejects unsafe base URLs before fetch", async () => {
    process.env.SCRAPER_BASE_URL = "https://user:password@example.com/path";

    await expect(listQueueWatches()).rejects.toThrow(
      "SCRAPER_BASE_URL musi być dokładnym originem HTTP(S)",
    );
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("rejects invalid timeout values before fetch", async () => {
    process.env.SCRAPER_QUEUE_TIMEOUT_MS = "999";

    await expect(listQueueWatches()).rejects.toThrow(
      "SCRAPER_QUEUE_TIMEOUT_MS musi być liczbą całkowitą od 1000 do 60000.",
    );
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
