import { z } from "zod";

const NHTSA_TIMEOUT_MS = 8_000;
const FRANKFURTER_TIMEOUT_MS = 5_000;
export const VIN_RESPONSE_MAX_BYTES = 256 * 1024;
export const RECALLS_RESPONSE_MAX_BYTES = 1024 * 1024;
export const FX_RESPONSE_MAX_BYTES = 32 * 1024;
export const FX_FRESH_TTL_MS = 6 * 60 * 60 * 1000;
export const FX_STALE_TTL_MS = 7 * 24 * 60 * 60 * 1000;
export const FX_RETRY_BACKOFF_MS = 5 * 60 * 1000;

const vinSchema = z
  .string()
  .trim()
  .transform((value) => value.toUpperCase().replace(/[\s-]/g, ""))
  .pipe(z.string().regex(/^[A-HJ-NPR-Z0-9]{11,17}$/, "VIN ma nieprawidłowy format."));

export const decodeVinInputSchema = z.object({ vin: vinSchema }).strict();

export const recallsInputSchema = z
  .object({
    make: z.string().trim().min(1).max(80),
    model: z.string().trim().min(1).max(80),
    year: z.number().int().min(1900).max(2100),
  })
  .strict();

export const vinDecodedSchema = z.object({
  vin: z.string().min(11).max(17),
  make: z.string().nullable(),
  model: z.string().nullable(),
  year: z.number().int().min(1900).max(2100).nullable(),
  trim: z.string().nullable(),
  body_class: z.string().nullable(),
  fuel_type: z.string().nullable(),
  drive_type: z.string().nullable(),
  transmission: z.string().nullable(),
  engine_cc: z.number().int().nonnegative().nullable(),
  engine_cylinders: z.number().int().nonnegative().nullable(),
  engine_power_hp: z.number().int().nonnegative().nullable(),
  manufacturer: z.string().nullable(),
  plant_country: z.string().nullable(),
  vehicle_type: z.string().nullable(),
  errors: z.array(z.string()).max(5),
});

export const recallItemSchema = z.object({
  campaign_number: z.string(),
  component: z.string(),
  summary: z.string(),
  consequence: z.string(),
  remedy: z.string(),
  report_received_date: z.string().nullable(),
});

export const fxRatesSchema = z.object({
  usd_pln: z.number().finite().positive(),
  usd_eur: z.number().finite().positive(),
  fetched_at: z.string().regex(/^\d{4}-\d{2}-\d{2}$/),
  source: z.enum(["frankfurter.app", "stale-cache", "fallback"]),
});

export type DecodeVinInput = z.infer<typeof decodeVinInputSchema>;
export type RecallsInput = z.infer<typeof recallsInputSchema>;
export type VinDecoded = z.infer<typeof vinDecodedSchema>;
export type RecallItem = z.infer<typeof recallItemSchema>;
export type FxRates = z.infer<typeof fxRatesSchema>;

const nullableText = (max: number) => z.string().max(max).nullable().optional();

const vinProviderRecordSchema = z.object({
  Make: nullableText(200),
  Model: nullableText(200),
  ModelYear: nullableText(20),
  Trim: nullableText(200),
  BodyClass: nullableText(200),
  FuelTypePrimary: nullableText(200),
  DriveType: nullableText(200),
  TransmissionStyle: nullableText(200),
  DisplacementL: nullableText(50),
  DisplacementCC: nullableText(50),
  EngineCylinders: nullableText(50),
  EngineHP: nullableText(50),
  Manufacturer: nullableText(500),
  PlantCountry: nullableText(200),
  VehicleType: nullableText(200),
  ErrorText: nullableText(5_000),
});

const vinProviderEnvelopeSchema = z.object({
  Results: z.array(vinProviderRecordSchema).min(1).max(25),
});

const recallProviderRecordSchema = z.object({
  NHTSACampaignNumber: nullableText(50),
  Component: nullableText(500),
  Summary: nullableText(50_000),
  Consequence: nullableText(50_000),
  Remedy: nullableText(50_000),
  ReportReceivedDate: nullableText(100),
});

const recallsProviderEnvelopeSchema = z.object({
  results: z.array(recallProviderRecordSchema).max(500),
});

const fxProviderEnvelopeSchema = z.object({
  rates: z.object({
    PLN: z.number().finite().positive().max(100),
    EUR: z.number().finite().positive().max(100),
  }),
  date: z.string().regex(/^\d{4}-\d{2}-\d{2}$/),
});

class ExternalApiBoundaryError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ExternalApiBoundaryError";
  }
}

type RequestPolicy = {
  provider: "NHTSA" | "Frankfurter";
  timeoutMs: number;
  maxBytes: number;
};

function discardBody(response: Response): void {
  void response.body?.cancel().catch(() => undefined);
}

async function readBodyWithLimit(
  response: Response,
  signal: AbortSignal,
  policy: RequestPolicy,
): Promise<string> {
  const contentLength = Number.parseInt(response.headers.get("content-length") ?? "", 10);
  if (Number.isFinite(contentLength) && contentLength > policy.maxBytes) {
    discardBody(response);
    throw new ExternalApiBoundaryError(`${policy.provider}: odpowiedź przekracza dozwolony limit.`);
  }
  if (!response.body) return "";

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let totalBytes = 0;
  let text = "";
  const abortBodyRead = () => {
    void reader.cancel("external API deadline exceeded").catch(() => undefined);
  };
  if (signal.aborted) abortBodyRead();
  else signal.addEventListener("abort", abortBodyRead, { once: true });

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      totalBytes += value.byteLength;
      if (totalBytes > policy.maxBytes) {
        void reader.cancel("external API response exceeds byte limit").catch(() => undefined);
        throw new ExternalApiBoundaryError(
          `${policy.provider}: odpowiedź przekracza dozwolony limit.`,
        );
      }
      text += decoder.decode(value, { stream: true });
    }
    return text + decoder.decode();
  } finally {
    signal.removeEventListener("abort", abortBodyRead);
    reader.releaseLock();
  }
}

function parseJson<T>(text: string, schema: z.ZodType<T>, provider: RequestPolicy["provider"]): T {
  let value: unknown;
  try {
    value = JSON.parse(text);
  } catch {
    throw new ExternalApiBoundaryError(`${provider}: usługa zwróciła niepoprawny JSON.`);
  }

  const parsed = schema.safeParse(value);
  if (!parsed.success) {
    throw new ExternalApiBoundaryError(
      `${provider}: usługa zwróciła dane w nieprawidłowym formacie.`,
    );
  }
  return parsed.data;
}

async function requestJson<T>(
  url: string,
  policy: RequestPolicy,
  schema: z.ZodType<T>,
): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), policy.timeoutMs);

  try {
    const response = await fetch(url, {
      headers: { accept: "application/json" },
      signal: controller.signal,
    });
    if (!response.ok) {
      discardBody(response);
      throw new ExternalApiBoundaryError(
        `${policy.provider}: usługa zwróciła HTTP ${response.status}.`,
      );
    }

    const text = await readBodyWithLimit(response, controller.signal, policy);
    return parseJson(text, schema, policy.provider);
  } catch (error) {
    if (controller.signal.aborted || (error as { name?: string })?.name === "AbortError") {
      throw new ExternalApiBoundaryError(
        `${policy.provider}: przekroczono czas oczekiwania ${policy.timeoutMs} ms.`,
      );
    }
    if (error instanceof ExternalApiBoundaryError) throw error;
    throw new ExternalApiBoundaryError(`${policy.provider}: usługa jest niedostępna.`);
  } finally {
    clearTimeout(timer);
  }
}

function textOrNull(value: string | null | undefined): string | null {
  const normalized = value?.trim();
  return normalized ? normalized : null;
}

function parseProviderNumber(value: string | null | undefined): number | null {
  if (!value) return null;
  const number = Number.parseFloat(value.replace(",", "."));
  return Number.isFinite(number) && number >= 0 ? number : null;
}

function roundedInRange(
  value: string | null | undefined,
  minimum: number,
  maximum: number,
): number | null {
  const number = parseProviderNumber(value);
  if (number === null) return null;
  const rounded = Math.round(number);
  return rounded >= minimum && rounded <= maximum ? rounded : null;
}

export async function decodeVinExternal(input: unknown): Promise<VinDecoded> {
  const { vin } = decodeVinInputSchema.parse(input);
  const url =
    `https://vpic.nhtsa.dot.gov/api/vehicles/decodevinvalues/${encodeURIComponent(vin)}` +
    "?format=json";
  const envelope = await requestJson(
    url,
    { provider: "NHTSA", timeoutMs: NHTSA_TIMEOUT_MS, maxBytes: VIN_RESPONSE_MAX_BYTES },
    vinProviderEnvelopeSchema,
  );
  const record = envelope.Results[0];
  const displacementLiters = parseProviderNumber(record.DisplacementL);
  const displacementCc = parseProviderNumber(record.DisplacementCC);
  const errors = (record.ErrorText ?? "")
    .split(";")
    .map((value) => value.trim())
    .filter(
      (value) => value && value !== "0 - VIN decoded clean. Check Digit (9th position) is correct",
    )
    .slice(0, 5);

  return vinDecodedSchema.parse({
    vin,
    make: textOrNull(record.Make),
    model: textOrNull(record.Model),
    year: roundedInRange(record.ModelYear, 1900, 2100),
    trim: textOrNull(record.Trim),
    body_class: textOrNull(record.BodyClass),
    fuel_type: textOrNull(record.FuelTypePrimary),
    drive_type: textOrNull(record.DriveType),
    transmission: textOrNull(record.TransmissionStyle),
    engine_cc:
      displacementCc === null
        ? displacementLiters === null
          ? null
          : Math.round(displacementLiters * 1_000)
        : Math.round(displacementCc),
    engine_cylinders: roundedInRange(record.EngineCylinders, 0, 100),
    engine_power_hp: roundedInRange(record.EngineHP, 0, 10_000),
    manufacturer: textOrNull(record.Manufacturer),
    plant_country: textOrNull(record.PlantCountry),
    vehicle_type: textOrNull(record.VehicleType),
    errors,
  });
}

export async function fetchRecallsExternal(input: unknown): Promise<RecallItem[]> {
  const data = recallsInputSchema.parse(input);
  const url = new URL("https://api.nhtsa.gov/recalls/recallsByVehicle");
  url.searchParams.set("make", data.make);
  url.searchParams.set("model", data.model);
  url.searchParams.set("modelYear", String(data.year));
  const envelope = await requestJson(
    url.toString(),
    { provider: "NHTSA", timeoutMs: NHTSA_TIMEOUT_MS, maxBytes: RECALLS_RESPONSE_MAX_BYTES },
    recallsProviderEnvelopeSchema,
  );

  return envelope.results.slice(0, 20).map((record) =>
    recallItemSchema.parse({
      campaign_number: record.NHTSACampaignNumber?.trim() ?? "",
      component: record.Component?.trim() ?? "",
      summary: record.Summary?.trim() ?? "",
      consequence: record.Consequence?.trim() ?? "",
      remedy: record.Remedy?.trim() ?? "",
      report_received_date: textOrNull(record.ReportReceivedDate),
    }),
  );
}

const FALLBACK_USD_PLN = 4.0;
const FALLBACK_USD_EUR = 0.92;
let lastGoodFx: FxRates | null = null;
let lastGoodFxAt = 0;
let fxFreshUntil = 0;
let fxRetryAfter = 0;
let cachedFallback: FxRates | null = null;
let fxRefreshPromise: Promise<FxRates> | null = null;

function fallbackFx(now: number): FxRates {
  return fxRatesSchema.parse({
    usd_pln: FALLBACK_USD_PLN,
    usd_eur: FALLBACK_USD_EUR,
    fetched_at: new Date(now).toISOString().slice(0, 10),
    source: "fallback",
  });
}

function staleFx(value: FxRates): FxRates {
  return { ...value, source: "stale-cache" };
}

function hasUsableStaleFx(now: number): boolean {
  return lastGoodFx !== null && now - lastGoodFxAt < FX_STALE_TTL_MS;
}

async function refreshFx(now: number): Promise<FxRates> {
  try {
    const envelope = await requestJson(
      "https://api.frankfurter.app/latest?from=USD&to=PLN,EUR",
      {
        provider: "Frankfurter",
        timeoutMs: FRANKFURTER_TIMEOUT_MS,
        maxBytes: FX_RESPONSE_MAX_BYTES,
      },
      fxProviderEnvelopeSchema,
    );
    const value = fxRatesSchema.parse({
      usd_pln: envelope.rates.PLN,
      usd_eur: envelope.rates.EUR,
      fetched_at: envelope.date,
      source: "frankfurter.app",
    });
    lastGoodFx = value;
    lastGoodFxAt = now;
    fxFreshUntil = now + FX_FRESH_TTL_MS;
    fxRetryAfter = 0;
    cachedFallback = null;
    return value;
  } catch {
    fxRetryAfter = now + FX_RETRY_BACKOFF_MS;
    if (lastGoodFx && hasUsableStaleFx(now)) return staleFx(lastGoodFx);
    cachedFallback = cachedFallback ?? fallbackFx(now);
    return cachedFallback;
  }
}

export async function getFxRatesExternal(): Promise<FxRates> {
  const now = Date.now();
  if (lastGoodFx && fxFreshUntil > now) return lastGoodFx;
  if (fxRetryAfter > now) {
    if (lastGoodFx && hasUsableStaleFx(now)) return staleFx(lastGoodFx);
    return cachedFallback ?? fallbackFx(now);
  }
  if (fxRefreshPromise) return fxRefreshPromise;

  const refresh = refreshFx(now);
  fxRefreshPromise = refresh;
  try {
    return await refresh;
  } finally {
    if (fxRefreshPromise === refresh) fxRefreshPromise = null;
  }
}

export function resetExternalApiCachesForTests(): void {
  lastGoodFx = null;
  lastGoodFxAt = 0;
  fxFreshUntil = 0;
  fxRetryAfter = 0;
  cachedFallback = null;
  fxRefreshPromise = null;
}
