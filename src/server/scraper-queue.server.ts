import { z } from "zod";
import { criteriaSchema } from "@/lib/criteria-schema";

export const DEFAULT_SCRAPER_QUEUE_TIMEOUT_MS = 10_000;
export const MAX_SCRAPER_QUEUE_RESPONSE_BYTES = 256 * 1024;

const queueCriteriaSchema = criteriaSchema.strict();

export const createQueueWatchInputSchema = z
  .object({
    search: z
      .object({
        criteria: queueCriteriaSchema,
        disable_auction_filter: z.boolean().optional(),
      })
      .strict(),
    interval_hours: z.number().int().min(1).max(168),
    label: z.string().trim().min(1).max(200).optional(),
  })
  .strict();

export const deleteQueueWatchInputSchema = z
  .object({ id: z.string().trim().min(1).max(200) })
  .strict();

const watchEntrySchema = z.object({
  id: z.string().min(1).max(200),
  label: z.string().max(200).nullable().optional(),
  interval_hours: z.number().int().min(1).max(168),
  next_run_at: z.string().datetime({ offset: true }),
  runs_count: z.number().int().min(0).optional(),
  last_result_count: z.number().int().min(0).nullable().optional(),
  status: z.string().max(40).optional(),
});

const watchListSchema = z.object({
  watches: z.array(watchEntrySchema).max(1_000),
  count: z.number().int().min(0).max(1_000_000),
});

export type CreateQueueWatchInput = z.infer<typeof createQueueWatchInputSchema>;
export type WatchEntry = z.infer<typeof watchEntrySchema>;
export type WatchQueueList = z.infer<typeof watchListSchema>;

type QueueConfig = {
  baseUrl: string;
  headers: Record<string, string>;
  timeoutMs: number;
};

class QueueBoundaryError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "QueueBoundaryError";
  }
}

function parseTimeoutMs(): number {
  const raw = process.env.SCRAPER_QUEUE_TIMEOUT_MS?.trim();
  if (!raw) return DEFAULT_SCRAPER_QUEUE_TIMEOUT_MS;

  const timeoutMs = Number(raw);
  if (!Number.isInteger(timeoutMs) || timeoutMs < 1_000 || timeoutMs > 60_000) {
    throw new Error("SCRAPER_QUEUE_TIMEOUT_MS musi być liczbą całkowitą od 1000 do 60000.");
  }
  return timeoutMs;
}

function scraperQueueConfig(): QueueConfig {
  const configuredUrl = process.env.SCRAPER_BASE_URL?.trim();
  if (!configuredUrl) throw new Error("SCRAPER_BASE_URL nie jest ustawiony.");

  let url: URL;
  try {
    url = new URL(configuredUrl);
  } catch {
    throw new Error("SCRAPER_BASE_URL musi być poprawnym adresem HTTP(S).");
  }

  if (
    !["http:", "https:"].includes(url.protocol) ||
    url.username ||
    url.password ||
    (url.pathname !== "/" && url.pathname !== "") ||
    url.search ||
    url.hash
  ) {
    throw new Error(
      "SCRAPER_BASE_URL musi być dokładnym originem HTTP(S) bez ścieżki i danych logowania.",
    );
  }

  const headers: Record<string, string> = {
    Accept: "application/json",
    "Content-Type": "application/json",
  };
  const token = process.env.SCRAPER_API_TOKEN?.trim();
  if (token) headers.Authorization = `Bearer ${token}`;

  return {
    baseUrl: url.origin,
    headers,
    timeoutMs: parseTimeoutMs(),
  };
}

async function discardBody(response: Response): Promise<void> {
  await response.body?.cancel().catch(() => undefined);
}

async function readBodyWithLimit(response: Response, signal: AbortSignal): Promise<string> {
  const contentLength = Number.parseInt(response.headers.get("content-length") ?? "", 10);
  if (Number.isFinite(contentLength) && contentLength > MAX_SCRAPER_QUEUE_RESPONSE_BYTES) {
    await discardBody(response);
    throw new QueueBoundaryError("Queue: odpowiedź scrapera przekracza dozwolony limit.");
  }
  if (!response.body) return "";

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let totalBytes = 0;
  let text = "";
  const abortBodyRead = () => {
    void reader.cancel("queue request deadline exceeded").catch(() => undefined);
  };
  if (signal.aborted) abortBodyRead();
  else signal.addEventListener("abort", abortBodyRead, { once: true });

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      totalBytes += value.byteLength;
      if (totalBytes > MAX_SCRAPER_QUEUE_RESPONSE_BYTES) {
        await reader.cancel("queue response exceeds byte limit").catch(() => undefined);
        throw new QueueBoundaryError("Queue: odpowiedź scrapera przekracza dozwolony limit.");
      }
      text += decoder.decode(value, { stream: true });
    }
    return text + decoder.decode();
  } finally {
    signal.removeEventListener("abort", abortBodyRead);
    reader.releaseLock();
  }
}

function parseJsonResponse<T>(text: string, schema: z.ZodType<T>): T {
  let value: unknown;
  try {
    value = JSON.parse(text);
  } catch {
    throw new QueueBoundaryError("Queue: scraper zwrócił niepoprawny JSON.");
  }

  const parsed = schema.safeParse(value);
  if (!parsed.success) {
    throw new QueueBoundaryError("Queue: scraper zwrócił dane w nieprawidłowym formacie.");
  }
  return parsed.data;
}

async function queueRequest<T>(path: string, init: RequestInit, schema: z.ZodType<T>): Promise<T> {
  const config = scraperQueueConfig();
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), config.timeoutMs);

  try {
    const response = await fetch(`${config.baseUrl}${path}`, {
      ...init,
      headers: config.headers,
      signal: controller.signal,
    });

    if (!response.ok) {
      await discardBody(response);
      throw new QueueBoundaryError(`Queue: scraper zwrócił HTTP ${response.status}.`);
    }

    return parseJsonResponse(await readBodyWithLimit(response, controller.signal), schema);
  } catch (error) {
    if (controller.signal.aborted || (error as { name?: string })?.name === "AbortError") {
      throw new QueueBoundaryError(
        `Queue: scraper nie odpowiedział w ciągu ${config.timeoutMs} ms.`,
      );
    }
    if (error instanceof QueueBoundaryError) throw error;
    throw new QueueBoundaryError("Queue: scraper jest niedostępny.");
  } finally {
    clearTimeout(timer);
  }
}

export async function createQueueWatch(input: unknown): Promise<WatchEntry> {
  const data = createQueueWatchInputSchema.parse(input);
  return queueRequest(
    "/api/queue",
    { method: "POST", body: JSON.stringify(data) },
    watchEntrySchema,
  );
}

export function listQueueWatches(): Promise<WatchQueueList> {
  return queueRequest("/api/queue", { method: "GET" }, watchListSchema);
}

export async function deleteQueueWatch(id: string): Promise<{ ok: true }> {
  const parsedId = deleteQueueWatchInputSchema.parse({ id }).id;
  const config = scraperQueueConfig();
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), config.timeoutMs);

  try {
    const response = await fetch(`${config.baseUrl}/api/queue/${encodeURIComponent(parsedId)}`, {
      method: "DELETE",
      headers: config.headers,
      signal: controller.signal,
    });
    if (!response.ok && response.status !== 404) {
      await discardBody(response);
      throw new QueueBoundaryError(`Queue: scraper zwrócił HTTP ${response.status}.`);
    }
    await discardBody(response);
    return { ok: true };
  } catch (error) {
    if (controller.signal.aborted || (error as { name?: string })?.name === "AbortError") {
      throw new QueueBoundaryError(
        `Queue: scraper nie odpowiedział w ciągu ${config.timeoutMs} ms.`,
      );
    }
    if (error instanceof QueueBoundaryError) throw error;
    throw new QueueBoundaryError("Queue: scraper jest niedostępny.");
  } finally {
    clearTimeout(timer);
  }
}
