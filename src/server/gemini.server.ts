// Server-only Google Gemini (AI Studio) caller.
// Reads GEMINI_API_KEY from process.env at call time.
// Compatible return type with callAnthropic.

import type { AnthropicResult, AnthropicUsage } from "./anthropic.server";

export const GEMINI_MODELS = [
  "gemini-2.5-flash",
  "gemini-2.5-pro",
  "gemini-2.0-flash",
] as const;

export const DEFAULT_GEMINI_MODEL = "gemini-2.5-flash";

export async function callGemini(opts: {
  system: string;
  userPrompt: string;
  model?: string;
  maxTokens?: number;
}): Promise<AnthropicResult> {
  const apiKey = process.env.GEMINI_API_KEY;
  if (!apiKey) {
    throw new Error("Brak GEMINI_API_KEY w sekretach Lovable Cloud.");
  }

  const model = opts.model || process.env.GEMINI_MODEL || DEFAULT_GEMINI_MODEL;

  const TIMEOUT_MS = 120_000;
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), TIMEOUT_MS);

  const url = `https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent?key=${apiKey}`;

  let res: Response;
  try {
    res = await fetch(url, {
      method: "POST",
      headers: { "content-type": "application/json" },
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
      throw new Error(
        `Gemini timeout po ${Math.round(TIMEOUT_MS / 1000)}s — model nie zdążył odpowiedzieć.`,
      );
    }
    throw err;
  } finally {
    clearTimeout(timer);
  }

  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`Gemini HTTP ${res.status}: ${body.slice(0, 500)}`);
  }

  const data = await res.json() as {
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
  if (!text) throw new Error("Gemini response has no text content");

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
