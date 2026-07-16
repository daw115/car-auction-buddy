import { z } from "zod";

export const DEFAULT_CLIENT_MESSAGE_PARSER_TIMEOUT_MS = 10_000;
export const MAX_CLIENT_MESSAGE_PARSER_RESPONSE_BYTES = 64 * 1024;

const parserCriterionSchema = z
  .object({
    make: z.string().trim().min(1).max(80),
    model: z.string().trim().max(80).nullable().optional(),
    year_from: z.number().int().min(1900).max(2100).nullable().optional(),
    year_to: z.number().int().min(1900).max(2100).nullable().optional(),
    budget_usd: z.number().finite().min(0).max(1_000_000).nullable().optional(),
    max_odometer_mi: z.number().int().min(0).max(1_000_000).nullable().optional(),
    fuel_type: z.enum(["Gas", "Hybrid", "Diesel", "Electric"]).nullable().optional(),
    excluded_damage_types: z.array(z.string().trim().min(1).max(80)).max(20).optional(),
    allowed_damage_types: z.array(z.string().trim().min(1).max(80)).max(20).optional(),
    sources: z.array(z.string().trim().min(1).max(20)).max(5).optional(),
    max_results: z.number().int().min(1).max(100).optional(),
  })
  .strict();

export const parseClientMessageInputSchema = z
  .object({
    message: z.string().trim().min(1).max(5_000),
  })
  .strict();

export const parsedClientMessageSchema = z
  .object({
    criteria: parserCriterionSchema,
    criteria_list: z.array(parserCriterionSchema).min(1).max(20).optional(),
    summary: z.string().trim().min(1).max(2_000),
    warnings: z.array(z.string().trim().min(1).max(1_000)).max(20),
  })
  .strict();

export type ParseClientMessageInput = z.infer<typeof parseClientMessageInputSchema>;
export type ParsedClientMessage = z.infer<typeof parsedClientMessageSchema>;

type ParserConfig = {
  baseUrl: string;
  token: string;
  timeoutMs: number;
};

class ClientMessageParserBoundaryError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ClientMessageParserBoundaryError";
  }
}

function parseTimeoutMs(): number {
  const raw = process.env.SCRAPER_PARSER_TIMEOUT_MS?.trim();
  if (!raw) return DEFAULT_CLIENT_MESSAGE_PARSER_TIMEOUT_MS;

  const timeoutMs = Number(raw);
  if (!Number.isInteger(timeoutMs) || timeoutMs < 1_000 || timeoutMs > 60_000) {
    throw new Error("SCRAPER_PARSER_TIMEOUT_MS musi być liczbą całkowitą od 1000 do 60000.");
  }
  return timeoutMs;
}

function parserConfig(): ParserConfig {
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

  const token = process.env.SCRAPER_API_TOKEN?.trim();
  if (!token) throw new Error("SCRAPER_API_TOKEN nie jest ustawiony.");

  return { baseUrl: url.origin, token, timeoutMs: parseTimeoutMs() };
}

function discardBody(response: Response): void {
  void response.body?.cancel().catch(() => undefined);
}

async function readBodyWithLimit(response: Response, signal: AbortSignal): Promise<string> {
  const contentLength = Number.parseInt(response.headers.get("content-length") ?? "", 10);
  if (Number.isFinite(contentLength) && contentLength > MAX_CLIENT_MESSAGE_PARSER_RESPONSE_BYTES) {
    discardBody(response);
    throw new ClientMessageParserBoundaryError(
      "Parser wiadomości: odpowiedź backendu przekracza dozwolony limit.",
    );
  }
  if (!response.body) return "";

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let totalBytes = 0;
  let text = "";
  const abortBodyRead = () => {
    void reader.cancel("client message parser deadline exceeded").catch(() => undefined);
  };
  if (signal.aborted) abortBodyRead();
  else signal.addEventListener("abort", abortBodyRead, { once: true });

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      totalBytes += value.byteLength;
      if (totalBytes > MAX_CLIENT_MESSAGE_PARSER_RESPONSE_BYTES) {
        void reader
          .cancel("client message parser response exceeds byte limit")
          .catch(() => undefined);
        throw new ClientMessageParserBoundaryError(
          "Parser wiadomości: odpowiedź backendu przekracza dozwolony limit.",
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

function parseResponse(text: string): ParsedClientMessage {
  let value: unknown;
  try {
    value = JSON.parse(text);
  } catch {
    throw new ClientMessageParserBoundaryError(
      "Parser wiadomości: backend zwrócił niepoprawny JSON.",
    );
  }

  const parsed = parsedClientMessageSchema.safeParse(value);
  if (!parsed.success) {
    throw new ClientMessageParserBoundaryError(
      "Parser wiadomości: backend zwrócił dane w nieprawidłowym formacie.",
    );
  }
  return parsed.data;
}

export async function parseClientMessageServer(input: unknown): Promise<ParsedClientMessage> {
  const data = parseClientMessageInputSchema.parse(input);
  const config = parserConfig();
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), config.timeoutMs);

  try {
    const response = await fetch(`${config.baseUrl}/api/parse-client-message`, {
      method: "POST",
      headers: {
        Accept: "application/json",
        Authorization: `Bearer ${config.token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(data),
      signal: controller.signal,
    });

    if (!response.ok) {
      discardBody(response);
      throw new ClientMessageParserBoundaryError(
        `Parser wiadomości: backend zwrócił HTTP ${response.status}.`,
      );
    }

    return parseResponse(await readBodyWithLimit(response, controller.signal));
  } catch (error) {
    if (controller.signal.aborted || (error as { name?: string })?.name === "AbortError") {
      throw new ClientMessageParserBoundaryError(
        `Parser wiadomości: przekroczono czas oczekiwania ${config.timeoutMs} ms.`,
      );
    }
    if (error instanceof ClientMessageParserBoundaryError) throw error;
    throw new ClientMessageParserBoundaryError("Parser wiadomości: backend jest niedostępny.");
  } finally {
    clearTimeout(timer);
  }
}
