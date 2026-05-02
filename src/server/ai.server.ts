// Unified AI caller — tries primary provider, falls back to secondary.
// Provider priority: env AI_PROVIDER ("anthropic" | "gemini") or auto-detect by available keys.

import { callAnthropic, type AnthropicResult } from "./anthropic.server";
import { callGemini } from "./gemini.server";

export type AIProvider = "anthropic" | "gemini";

export function detectProvider(): AIProvider {
  const explicit = process.env.AI_PROVIDER?.toLowerCase();
  if (explicit === "gemini") return "gemini";
  if (explicit === "anthropic") return "anthropic";
  // auto: prefer anthropic if key exists, else gemini
  if (process.env.ANTHROPIC_API_KEY) return "anthropic";
  if (process.env.GEMINI_API_KEY) return "gemini";
  return "anthropic"; // default, will fail with descriptive error
}

function fallbackProvider(primary: AIProvider): AIProvider | null {
  if (primary === "anthropic" && process.env.GEMINI_API_KEY) return "gemini";
  if (primary === "gemini" && process.env.ANTHROPIC_API_KEY) return "anthropic";
  return null;
}

function callProvider(provider: AIProvider, opts: {
  system: string;
  userPrompt: string;
  model?: string;
  maxTokens?: number;
}): Promise<AnthropicResult> {
  if (provider === "gemini") return callGemini(opts);
  return callAnthropic(opts);
}

/**
 * callAI — calls the primary AI provider; on failure, tries fallback if available.
 * Returns result + which provider was actually used.
 */
export async function callAI(opts: {
  system: string;
  userPrompt: string;
  model?: string;
  maxTokens?: number;
}): Promise<AnthropicResult & { provider: AIProvider; usedFallback: boolean }> {
  const primary = detectProvider();
  const fallback = fallbackProvider(primary);

  try {
    const result = await callProvider(primary, opts);
    return { ...result, provider: primary, usedFallback: false };
  } catch (primaryErr) {
    if (!fallback) throw primaryErr;

    console.warn(
      `[callAI] ${primary} failed: ${primaryErr instanceof Error ? primaryErr.message : String(primaryErr)}. Falling back to ${fallback}.`,
    );

    try {
      // Don't pass model from primary provider to fallback — use default
      const result = await callProvider(fallback, { ...opts, model: undefined });
      return { ...result, provider: fallback, usedFallback: true };
    } catch (fallbackErr) {
      // Both failed — throw primary error with fallback info
      const msg = primaryErr instanceof Error ? primaryErr.message : String(primaryErr);
      const fbMsg = fallbackErr instanceof Error ? fallbackErr.message : String(fallbackErr);
      throw new Error(
        `AI niedostępne. ${primary}: ${msg} | Fallback (${fallback}): ${fbMsg}`,
      );
    }
  }
}
