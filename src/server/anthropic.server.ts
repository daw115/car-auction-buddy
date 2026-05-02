// Server-only Anthropic Messages API caller.
// Reads ANTHROPIC_API_KEY / ANTHROPIC_BASE_URL / ANTHROPIC_MODEL from process.env at call time.
// Includes retry with exponential backoff for rate limits and timeouts.

import { withRetry, checkRetryableResponse, AITimeoutError } from "./ai-retry.server";

export const ANTHROPIC_MODELS = [
  "claude-opus-4-7",
  "claude-sonnet-4-6",
  "claude-haiku-4-5",
] as const;

export const DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-4-6";

export type AnthropicUsage = {
  input_tokens: number;
  output_tokens: number;
  cache_creation_input_tokens?: number;
  cache_read_input_tokens?: number;
};

export type AnthropicResult = {
  text: string;
  model: string;
  usage: AnthropicUsage;
  stop_reason?: string;
};

export async function callAnthropic(opts: {
  system: string;
  userPrompt: string;
  model?: string;
  maxTokens?: number;
}): Promise<AnthropicResult> {
  const apiKey = process.env.ANTHROPIC_API_KEY;
  if (!apiKey) {
    throw new Error("Brak ANTHROPIC_API_KEY w sekretach Lovable Cloud.");
  }
  const baseUrl = (process.env.ANTHROPIC_BASE_URL ?? "https://api.anthropic.com").replace(/\/+$/, "");
  const model = opts.model || process.env.ANTHROPIC_MODEL || DEFAULT_ANTHROPIC_MODEL;

  return withRetry(
    () => singleAnthropicCall(apiKey, baseUrl, model, opts),
    { provider: "Anthropic", maxRetries: 3, initialDelayMs: 2_000 },
  );
}

async function singleAnthropicCall(
  apiKey: string,
  baseUrl: string,
  model: string,
  opts: { system: string; userPrompt: string; maxTokens?: number },
): Promise<AnthropicResult> {
  // Cloudflare Workers / proxy obcina request po ~100s i zwraca 524.
  const TIMEOUT_MS = 110_000;
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), TIMEOUT_MS);

  let res: Response;
  try {
    res = await fetch(`${baseUrl}/v1/messages`, {
      method: "POST",
      headers: {
        "x-api-key": apiKey,
        "anthropic-version": "2023-06-01",
        "anthropic-beta": "prompt-caching-2024-07-31",
        "content-type": "application/json",
      },
      body: JSON.stringify({
        model,
        max_tokens: opts.maxTokens ?? 4096,
        system: [{ type: "text", text: opts.system, cache_control: { type: "ephemeral" } }],
        messages: [{ role: "user", content: opts.userPrompt }],
      }),
      signal: ctrl.signal,
    });
  } catch (err) {
    if ((err as { name?: string })?.name === "AbortError") {
      throw new AITimeoutError(
        `Anthropic: Timeout po ${Math.round(TIMEOUT_MS / 1000)}s — model nie zdążył odpowiedzieć. Spróbuj ponownie lub zmniejsz prompt/max_tokens.`,
        "Anthropic",
      );
    }
    throw err;
  } finally {
    clearTimeout(timer);
  }

  // Check for retryable HTTP status (429, 503, 529) before reading body
  checkRetryableResponse(res, "Anthropic");

  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`Anthropic HTTP ${res.status}: ${body.slice(0, 500)}`);
  }

  const data: {
    content?: Array<{ type: string; text?: string }>;
    model?: string;
    stop_reason?: string;
    usage?: AnthropicUsage;
  } = await res.json();
  const chunks = (data.content ?? [])
    .filter((c) => c.type === "text" && c.text)
    .map((c) => c.text as string);
  if (chunks.length === 0) throw new Error("Anthropic: Odpowiedź nie zawiera tekstu");
  return {
    text: chunks.join(""),
    model: data.model ?? model,
    usage: data.usage ?? { input_tokens: 0, output_tokens: 0 },
    stop_reason: data.stop_reason,
  };
}

export function parseAnalysisJson(raw: string): unknown {
  let s = raw.trim();

  // strip markdown code fences
  s = s.replace(/```json\s*/gi, "").replace(/```\s*$/g, "").replace(/```/g, "").trim();

  // find JSON boundaries
  const start = s.search(/[\[{]/);
  if (start === -1) throw new Error("Brak JSON-a w odpowiedzi AI");
  const opener = s[start];
  const closer = opener === "[" ? "]" : "}";
  const lastClose = s.lastIndexOf(closer);
  s = lastClose > start ? s.slice(start, lastClose + 1) : s.slice(start);

  const tryParse = (text: string): unknown => JSON.parse(text);

  // 1) raw
  try { return tryParse(s); } catch {}

  // 2) clean trailing commas + control chars
  let cleaned = s
    .replace(/,\s*}/g, "}")
    .replace(/,\s*\]/g, "]")
    .replace(/[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]/g, "");
  try { return tryParse(cleaned); } catch {}

  // 3) repair truncation: walk chars tracking string state + bracket stack,
  //    drop incomplete trailing element, then close all open brackets.
  const stack: string[] = [];
  let inStr = false;
  let escape = false;
  let lastSafeEnd = -1; // index AFTER a fully-closed top-level child element
  for (let i = 0; i < cleaned.length; i++) {
    const ch = cleaned[i];
    if (escape) { escape = false; continue; }
    if (ch === "\\") { escape = true; continue; }
    if (ch === '"') { inStr = !inStr; continue; }
    if (inStr) continue;
    if (ch === "{" || ch === "[") stack.push(ch);
    else if (ch === "}" || ch === "]") {
      stack.pop();
      // mark a safe cut point right after a balanced child of root array
      if (stack.length === 1 && cleaned[0] === "[") lastSafeEnd = i + 1;
    }
  }

  if (stack.length > 0) {
    let repaired: string;
    if (cleaned[0] === "[" && lastSafeEnd > 0) {
      // cut to last complete element and close root array
      repaired = cleaned.slice(0, lastSafeEnd).replace(/,\s*$/, "") + "]";
    } else {
      // close remaining brackets in reverse
      const closers = stack
        .slice()
        .reverse()
        .map((c) => (c === "{" ? "}" : "]"))
        .join("");
      repaired = cleaned.replace(/,\s*$/, "") + closers;
    }
    try { return tryParse(repaired); } catch {}
  }

  // last resort — surface original error
  return tryParse(cleaned);
}
