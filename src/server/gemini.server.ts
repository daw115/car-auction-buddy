// Server-only Google Gemini (AI Studio) caller.
// Reads GEMINI_API_KEY from process.env at call time.
// Compatible return type with callAnthropic.
// Includes retry with exponential backoff for rate limits and timeouts.

import type { AnthropicResult, AnthropicUsage } from "./anthropic.server";
import { withRetry, checkRetryableResponse, AITimeoutError } from "./ai-retry.server";

export const GEMINI_MODELS = [
  "gemini-3.5-flash",
  "gemini-2.5-flash",
  "gemini-2.5-pro",
  "gemini-2.5-flash-lite",
] as const;

export type GeminiModel = (typeof GEMINI_MODELS)[number];

export const DEFAULT_GEMINI_MODEL: GeminiModel = "gemini-3.5-flash";

const GEMINI_PRODUCTION_TIMEOUT_MS = 120_000;
export const GEMINI_CONNECTION_TEST_TIMEOUT_MS = 30_000;

type GeminiCallOptions = {
  system: string;
  userPrompt: string;
  model?: string;
  maxTokens?: number;
};

function requireGeminiApiKey(): string {
  const apiKey = process.env.GEMINI_API_KEY;
  if (!apiKey) {
    throw new Error("Brak GEMINI_API_KEY w sekretach Lovable Cloud.");
  }
  return apiKey;
}

export function resolveGeminiModel(requestedModel?: string): GeminiModel {
  const model = requestedModel || process.env.GEMINI_MODEL || DEFAULT_GEMINI_MODEL;
  if (!GEMINI_MODELS.includes(model as GeminiModel)) {
    throw new Error(
      `Nieobsługiwany model Gemini: ${model}. Dozwolone modele: ${GEMINI_MODELS.join(", ")}.`,
    );
  }
  return model as GeminiModel;
}

export async function callGemini(opts: GeminiCallOptions): Promise<AnthropicResult> {
  const apiKey = requireGeminiApiKey();
  const model = resolveGeminiModel(opts.model);

  return withRetry(() => singleGeminiCall(apiKey, model, opts, GEMINI_PRODUCTION_TIMEOUT_MS), {
    provider: "Gemini",
    maxRetries: 3,
    initialDelayMs: 2_000,
  });
}

export function testGeminiConnection(model?: string): Promise<AnthropicResult> {
  const apiKey = requireGeminiApiKey();
  const resolvedModel = resolveGeminiModel(model);
  const opts: GeminiCallOptions = {
    system: "Jesteś testem połączenia API. Odpowiadaj zwięźle.",
    userPrompt: "Odpowiedz dokładnie: pong",
    model: resolvedModel,
    maxTokens: 512,
  };

  return withRetry(
    () => singleGeminiCall(apiKey, resolvedModel, opts, GEMINI_CONNECTION_TEST_TIMEOUT_MS),
    {
      provider: "Gemini",
      maxRetries: 1,
      initialDelayMs: 500,
    },
  );
}

async function singleGeminiCall(
  apiKey: string,
  model: string,
  opts: GeminiCallOptions,
  timeoutMs: number,
): Promise<AnthropicResult> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);

  const url = `https://generativelanguage.googleapis.com/v1beta/models/${encodeURIComponent(model)}:generateContent`;

  let res: Response;
  try {
    res = await fetch(url, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "x-goog-api-key": apiKey,
      },
      body: JSON.stringify({
        systemInstruction: { parts: [{ text: opts.system }] },
        contents: [{ role: "user", parts: [{ text: opts.userPrompt }] }],
        generationConfig: {
          maxOutputTokens: opts.maxTokens ?? 4096,
          temperature: 0.7,
        },
      }),
      signal: ctrl.signal,
    });
  } catch (err) {
    if ((err as { name?: string })?.name === "AbortError") {
      throw new AITimeoutError(
        `Gemini: Timeout po ${Math.round(timeoutMs / 1000)}s — model nie zdążył odpowiedzieć.`,
        "Gemini",
      );
    }
    throw err;
  } finally {
    clearTimeout(timer);
  }

  // Check for retryable HTTP status (429, 503, 529) before reading body
  checkRetryableResponse(res, "Gemini");

  if (!res.ok) {
    await res.body?.cancel().catch(() => undefined);
    const statusMessage: Record<number, string> = {
      400: "nieprawidłowe żądanie",
      401: "nieprawidłowy klucz API",
      403: "klucz API nie ma dostępu do modelu",
      404: "model jest niedostępny dla tego klucza API",
    };
    throw new Error(
      `HTTP ${res.status}: ${statusMessage[res.status] ?? "żądanie zostało odrzucone"}`,
    );
  }

  const data = (await res.json()) as {
    candidates?: Array<{
      content?: { parts?: Array<{ text?: string }> };
      finishReason?: string;
    }>;
    usageMetadata?: {
      promptTokenCount?: number;
      candidatesTokenCount?: number;
      totalTokenCount?: number;
    };
    modelVersion?: string;
  };

  const parts = data.candidates?.[0]?.content?.parts ?? [];
  const text = parts.map((p) => p.text ?? "").join("");
  if (!text) throw new Error("Gemini: Odpowiedź nie zawiera tekstu");

  const usage: AnthropicUsage = {
    input_tokens: data.usageMetadata?.promptTokenCount ?? 0,
    output_tokens: data.usageMetadata?.candidatesTokenCount ?? 0,
  };

  return {
    text,
    model: data.modelVersion ?? model,
    usage,
    stop_reason: data.candidates?.[0]?.finishReason,
  };
}
