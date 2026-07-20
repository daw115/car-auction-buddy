import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  decodeVinExternal,
  fetchRecallsExternal,
  FX_FRESH_TTL_MS,
  FX_RESPONSE_MAX_BYTES,
  FX_RETRY_BACKOFF_MS,
  FX_STALE_TTL_MS,
  getFxRatesExternal,
  RECALLS_RESPONSE_MAX_BYTES,
  resetExternalApiCachesForTests,
  VIN_RESPONSE_MAX_BYTES,
} from "./external-apis.server";

const fetchMock = vi.fn<typeof fetch>();

const VIN_RECORD = {
  Make: "HONDA",
  Model: "Accord",
  ModelYear: "2003",
  Trim: "EX",
  BodyClass: "Sedan/Saloon",
  FuelTypePrimary: "Gasoline",
  DriveType: "FWD/Front-Wheel Drive",
  TransmissionStyle: "Automatic",
  DisplacementL: "2.4",
  DisplacementCC: "",
  EngineCylinders: "4",
  EngineHP: "160.4",
  Manufacturer: "AMERICAN HONDA MOTOR CO., INC.",
  PlantCountry: "UNITED STATES (USA)",
  VehicleType: "PASSENGER CAR",
  ErrorText: "0 - VIN decoded clean. Check Digit (9th position) is correct",
};

const RECALL_RECORD = {
  NHTSACampaignNumber: "24V001000",
  Component: "AIR BAGS",
  Summary: "Inflator may rupture",
  Consequence: "Fragments can injure occupants",
  Remedy: "Dealers will replace the inflator",
  ReportReceivedDate: "01/02/2024",
};

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
  resetExternalApiCachesForTests();
});

afterEach(() => {
  resetExternalApiCachesForTests();
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

function jsonResponse(value: unknown, init?: ResponseInit): Response {
  return new Response(JSON.stringify(value), {
    ...init,
    headers: { "content-type": "application/json", ...init?.headers },
  });
}

describe("decodeVinExternal", () => {
  it("normalizes input and maps the bounded provider response", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ Results: [VIN_RECORD] }));

    const result = await decodeVinExternal({ vin: " 1hg-cm8263 3a004352 " });

    expect(result).toEqual({
      vin: "1HGCM82633A004352",
      make: "HONDA",
      model: "Accord",
      year: 2003,
      trim: "EX",
      body_class: "Sedan/Saloon",
      fuel_type: "Gasoline",
      drive_type: "FWD/Front-Wheel Drive",
      transmission: "Automatic",
      engine_cc: 2400,
      engine_cylinders: 4,
      engine_power_hp: 160,
      manufacturer: "AMERICAN HONDA MOTOR CO., INC.",
      plant_country: "UNITED STATES (USA)",
      vehicle_type: "PASSENGER CAR",
      errors: [],
    });
    expect(fetchMock).toHaveBeenCalledOnce();
    expect(String(fetchMock.mock.calls[0][0])).toContain(
      "/decodevinvalues/1HGCM82633A004352?format=json",
    );
  });

  it.each([
    { vin: "1HGCM82633A00435!" },
    { vin: "short" },
    { vin: "1HGCM82633A004352", unexpected: true },
  ])("rejects invalid or non-strict input before fetch", async (input) => {
    await expect(decodeVinExternal(input)).rejects.toThrow();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("limits provider errors to five entries", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({
        Results: [
          {
            ...VIN_RECORD,
            ErrorText: "one; two; three; four; five; six; seven",
          },
        ],
      }),
    );

    const result = await decodeVinExternal({ vin: "1HGCM82633A004352" });

    expect(result.errors).toEqual(["one", "two", "three", "four", "five"]);
  });

  it("rejects malformed JSON without exposing response contents", async () => {
    fetchMock.mockResolvedValue(new Response("private malformed payload"));

    const message = await rejectionMessage(decodeVinExternal({ vin: "1HGCM82633A004352" }));

    expect(message).toBe("NHTSA: usługa zwróciła niepoprawny JSON.");
    expect(message).not.toContain("private malformed payload");
  });

  it("rejects an invalid provider contract", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ Results: "not-an-array" }));

    await expect(decodeVinExternal({ vin: "1HGCM82633A004352" })).rejects.toThrow(
      "NHTSA: usługa zwróciła dane w nieprawidłowym formacie.",
    );
  });

  it("redacts HTTP response bodies", async () => {
    fetchMock.mockResolvedValue(
      new Response("upstream diagnostics with private details", { status: 503 }),
    );

    const message = await rejectionMessage(decodeVinExternal({ vin: "1HGCM82633A004352" }));

    expect(message).toBe("NHTSA: usługa zwróciła HTTP 503.");
    expect(message).not.toContain("private details");
  });

  it("maps network failures to a stable redacted error", async () => {
    fetchMock.mockRejectedValue(new Error("connect failed at private.internal"));

    const message = await rejectionMessage(decodeVinExternal({ vin: "1HGCM82633A004352" }));

    expect(message).toBe("NHTSA: usługa jest niedostępna.");
    expect(message).not.toContain("private.internal");
  });

  it("rejects a response declared above the byte limit", async () => {
    fetchMock.mockResolvedValue(
      new Response("{}", {
        headers: { "content-length": String(VIN_RESPONSE_MAX_BYTES + 1) },
      }),
    );

    await expect(decodeVinExternal({ vin: "1HGCM82633A004352" })).rejects.toThrow(
      "NHTSA: odpowiedź przekracza dozwolony limit.",
    );
  });

  it("rejects a streamed response that crosses the byte limit", async () => {
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(new Uint8Array(VIN_RESPONSE_MAX_BYTES + 1));
        controller.close();
      },
    });
    fetchMock.mockResolvedValue(new Response(body));

    await expect(decodeVinExternal({ vin: "1HGCM82633A004352" })).rejects.toThrow(
      "NHTSA: odpowiedź przekracza dozwolony limit.",
    );
  });

  it("does not wait for cancellation of an oversized stream", async () => {
    let cancelCalled = false;
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(new Uint8Array(VIN_RESPONSE_MAX_BYTES + 1));
      },
      cancel() {
        cancelCalled = true;
        return new Promise<void>(() => undefined);
      },
    });
    fetchMock.mockResolvedValue(new Response(body));

    await expect(decodeVinExternal({ vin: "1HGCM82633A004352" })).rejects.toThrow(
      "NHTSA: odpowiedź przekracza dozwolony limit.",
    );
    expect(cancelCalled).toBe(true);
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

    await expect(decodeVinExternal({ vin: "1HGCM82633A004352" })).rejects.toThrow(
      "NHTSA: usługa zwróciła HTTP 503.",
    );
    expect(cancelCalled).toBe(true);
  });

  it("aborts a request before headers at the provider deadline", async () => {
    vi.useFakeTimers();
    fetchMock.mockImplementation(
      (_input, init) =>
        new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () => {
            reject(new DOMException("private abort details", "AbortError"));
          });
        }),
    );

    const request = decodeVinExternal({ vin: "1HGCM82633A004352" });
    const rejection = expect(request).rejects.toThrow(
      "NHTSA: przekroczono czas oczekiwania 8000 ms.",
    );

    await vi.advanceTimersByTimeAsync(8_000);
    await rejection;
  });

  it("aborts a hanging response body at the provider deadline", async () => {
    vi.useFakeTimers();
    let cancelReason: unknown;
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(new TextEncoder().encode('{"Results":['));
      },
      cancel(reason) {
        cancelReason = reason;
      },
    });
    fetchMock.mockResolvedValue(new Response(body));

    const request = decodeVinExternal({ vin: "1HGCM82633A004352" });
    const rejection = expect(request).rejects.toThrow(
      "NHTSA: przekroczono czas oczekiwania 8000 ms.",
    );

    await vi.advanceTimersByTimeAsync(8_000);
    await rejection;
    expect(cancelReason).toBe("external API deadline exceeded");
  });
});

describe("fetchRecallsExternal", () => {
  it("encodes query parameters and maps at most twenty recalls", async () => {
    const records = Array.from({ length: 21 }, (_, index) => ({
      ...RECALL_RECORD,
      NHTSACampaignNumber: `24V${String(index).padStart(6, "0")}`,
    }));
    fetchMock.mockResolvedValue(jsonResponse({ results: records }));

    const result = await fetchRecallsExternal({
      make: "Ford & Co",
      model: "F-150 / Lightning",
      year: 2024,
    });

    expect(result).toHaveLength(20);
    expect(result[0]).toEqual({
      campaign_number: "24V000000",
      component: "AIR BAGS",
      summary: "Inflator may rupture",
      consequence: "Fragments can injure occupants",
      remedy: "Dealers will replace the inflator",
      report_received_date: "01/02/2024",
    });
    const url = new URL(String(fetchMock.mock.calls[0][0]));
    expect(url.searchParams.get("make")).toBe("Ford & Co");
    expect(url.searchParams.get("model")).toBe("F-150 / Lightning");
    expect(url.searchParams.get("modelYear")).toBe("2024");
  });

  it("accepts decoded vehicle years before 1980", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ results: [] }));

    await expect(
      fetchRecallsExternal({ make: "Ford", model: "Mustang", year: 1965 }),
    ).resolves.toEqual([]);
    const url = new URL(String(fetchMock.mock.calls[0][0]));
    expect(url.searchParams.get("modelYear")).toBe("1965");
  });

  it("treats non-success HTTP responses as errors", async () => {
    fetchMock.mockResolvedValue(new Response("private unavailable details", { status: 429 }));

    const message = await rejectionMessage(
      fetchRecallsExternal({ make: "Honda", model: "Accord", year: 2020 }),
    );

    expect(message).toBe("NHTSA: usługa zwróciła HTTP 429.");
    expect(message).not.toContain("private unavailable details");
  });

  it("rejects an invalid recalls contract", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ count: 0 }));

    await expect(
      fetchRecallsExternal({ make: "Honda", model: "Accord", year: 2020 }),
    ).rejects.toThrow("NHTSA: usługa zwróciła dane w nieprawidłowym formacie.");
  });

  it("enforces the one MiB recalls response cap", async () => {
    fetchMock.mockResolvedValue(
      new Response("{}", {
        headers: { "content-length": String(RECALLS_RESPONSE_MAX_BYTES + 1) },
      }),
    );

    await expect(
      fetchRecallsExternal({ make: "Honda", model: "Accord", year: 2020 }),
    ).rejects.toThrow("NHTSA: odpowiedź przekracza dozwolony limit.");
  });
});

describe("getFxRatesExternal", () => {
  it("validates and returns current Frankfurter rates", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ rates: { PLN: 3.9876, EUR: 0.8765 }, date: "2026-07-15" }),
    );

    await expect(getFxRatesExternal()).resolves.toEqual({
      usd_pln: 3.9876,
      usd_eur: 0.8765,
      fetched_at: "2026-07-15",
      source: "frankfurter.app",
    });
    expect(String(fetchMock.mock.calls[0][0])).toBe(
      "https://api.frankfurter.app/latest?from=USD&to=PLN,EUR",
    );
  });

  it("serves a fresh value from the six-hour cache", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ rates: { PLN: 4.01, EUR: 0.91 }, date: "2026-07-15" }),
    );

    const first = await getFxRatesExternal();
    const second = await getFxRatesExternal();

    expect(second).toEqual(first);
    expect(fetchMock).toHaveBeenCalledOnce();
  });

  it("coalesces concurrent refreshes into one provider request", async () => {
    let resolveFetch!: (response: Response) => void;
    fetchMock.mockImplementation(
      () =>
        new Promise<Response>((resolve) => {
          resolveFetch = resolve;
        }),
    );

    const first = getFxRatesExternal();
    const second = getFxRatesExternal();

    expect(fetchMock).toHaveBeenCalledOnce();
    resolveFetch(jsonResponse({ rates: { PLN: 4.01, EUR: 0.91 }, date: "2026-07-15" }));
    const [firstResult, secondResult] = await Promise.all([first, second]);
    expect(secondResult).toEqual(firstResult);
    expect(secondResult.source).toBe("frankfurter.app");
  });

  it("refreshes the value after the fresh TTL", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-07-15T00:00:00Z"));
    fetchMock
      .mockResolvedValueOnce(jsonResponse({ rates: { PLN: 4.01, EUR: 0.91 }, date: "2026-07-15" }))
      .mockResolvedValueOnce(jsonResponse({ rates: { PLN: 4.02, EUR: 0.92 }, date: "2026-07-16" }));

    await getFxRatesExternal();
    await vi.advanceTimersByTimeAsync(FX_FRESH_TTL_MS);
    const refreshed = await getFxRatesExternal();

    expect(refreshed).toMatchObject({ usd_pln: 4.02, fetched_at: "2026-07-16" });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("returns the last good value as stale after a refresh failure", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-07-15T00:00:00Z"));
    fetchMock
      .mockResolvedValueOnce(jsonResponse({ rates: { PLN: 4.01, EUR: 0.91 }, date: "2026-07-15" }))
      .mockRejectedValueOnce(new Error("private provider failure"));

    await getFxRatesExternal();
    await vi.advanceTimersByTimeAsync(FX_FRESH_TTL_MS);
    const stale = await getFxRatesExternal();

    expect(stale).toEqual({
      usd_pln: 4.01,
      usd_eur: 0.91,
      fetched_at: "2026-07-15",
      source: "stale-cache",
    });
  });

  it("falls back when the last good value reaches its maximum stale age", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-07-15T00:00:00Z"));
    fetchMock
      .mockResolvedValueOnce(jsonResponse({ rates: { PLN: 4.01, EUR: 0.91 }, date: "2026-07-15" }))
      .mockRejectedValue(new Error("provider unavailable"));

    await getFxRatesExternal();
    await vi.advanceTimersByTimeAsync(FX_FRESH_TTL_MS);
    await expect(getFxRatesExternal()).resolves.toMatchObject({ source: "stale-cache" });

    await vi.advanceTimersByTimeAsync(FX_STALE_TTL_MS - FX_FRESH_TTL_MS);
    await expect(getFxRatesExternal()).resolves.toEqual({
      usd_pln: 4,
      usd_eur: 0.92,
      fetched_at: "2026-07-22",
      source: "fallback",
    });
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("coalesces concurrent failures and returns one fallback value", async () => {
    let rejectFetch!: (error: Error) => void;
    fetchMock.mockImplementation(
      () =>
        new Promise<Response>((_resolve, reject) => {
          rejectFetch = reject;
        }),
    );

    const first = getFxRatesExternal();
    const second = getFxRatesExternal();

    expect(fetchMock).toHaveBeenCalledOnce();
    rejectFetch(new Error("private provider failure"));
    const [firstResult, secondResult] = await Promise.all([first, second]);
    expect(firstResult.source).toBe("fallback");
    expect(secondResult).toEqual(firstResult);
  });

  it("uses a fallback without history and applies retry backoff", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-07-15T12:00:00Z"));
    fetchMock
      .mockRejectedValueOnce(new Error("provider unavailable"))
      .mockResolvedValueOnce(jsonResponse({ rates: { PLN: 4.05, EUR: 0.93 }, date: "2026-07-16" }));

    const fallback = await getFxRatesExternal();
    const backedOff = await getFxRatesExternal();

    expect(fallback).toEqual({
      usd_pln: 4,
      usd_eur: 0.92,
      fetched_at: "2026-07-15",
      source: "fallback",
    });
    expect(backedOff).toEqual(fallback);
    expect(fetchMock).toHaveBeenCalledOnce();

    await vi.advanceTimersByTimeAsync(FX_RETRY_BACKOFF_MS);
    const recovered = await getFxRatesExternal();

    expect(recovered).toMatchObject({
      usd_pln: 4.05,
      usd_eur: 0.93,
      source: "frankfurter.app",
    });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it.each([
    ["malformed JSON", new Response("not-json")],
    ["partial rates", jsonResponse({ rates: { PLN: 4.01 }, date: "2026-07-15" })],
    ["non-positive rate", jsonResponse({ rates: { PLN: 0, EUR: 0.91 }, date: "2026-07-15" })],
  ])("uses a fallback for %s", async (_name, response) => {
    fetchMock.mockResolvedValue(response);

    const result = await getFxRatesExternal();

    expect(result.source).toBe("fallback");
  });

  it("enforces the FX response byte cap", async () => {
    fetchMock.mockResolvedValue(
      new Response("{}", {
        headers: { "content-length": String(FX_RESPONSE_MAX_BYTES + 1) },
      }),
    );

    await expect(getFxRatesExternal()).resolves.toMatchObject({ source: "fallback" });
  });
});
