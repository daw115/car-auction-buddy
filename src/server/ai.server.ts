// Unified AI caller — tries primary provider, falls back to secondary.
// Provider priority: DB config (ai_analysis_mode) > env AI_PROVIDER > auto-detect by available keys.
// Fallback mode: "error_only" (try secondary only on error) or "race_both" (race both in parallel).

import { callAnthropic, type AnthropicResult } from "./anthropic.server";
import { callGemini } from "./gemini.server";

export type AIProvider = "anthropic" | "gemini";
export type AIFallbackMode = "error_only" | "race_both";

/**
 * Detect primary provider.
 * Priority: dbPreference (from app_config.ai_analysis_mode) > env AI_PROVIDER > auto by keys.
 */
export function detectProvider(dbPreference?: string | null): AIProvider {
  const db = dbPreference?.toLowerCase();
  if (db === "gemini") return "gemini";
  if (db === "anthropic") return "anthropic";

  const explicit = process.env.AI_PROVIDER?.toLowerCase();
  if (explicit === "gemini") return "gemini";
  if (explicit === "anthropic") return "anthropic";

  if (process.env.ANTHROPIC_API_KEY) return "anthropic";
  if (process.env.GEMINI_API_KEY) return "gemini";
  return "anthropic";
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

export type AICallResult = AnthropicResult & {
  provider: AIProvider;
  usedFallback: boolean;
  fallbackMode: AIFallbackMode;
};

/**
 * callAI — unified AI caller with two fallback strategies:
 *
 * "error_only": try primary → on failure try fallback (sequential)
 * "race_both": fire both in parallel → use fastest successful response
 */
export async function callAI(opts: {
  system: string;
  userPrompt: string;
  model?: string;
  maxTokens?: number;
  dbPreference?: string | null;
  fallbackMode?: AIFallbackMode;
}): Promise<AICallResult> {
  const primary = detectProvider(opts.dbPreference);
  const fallback = fallbackProvider(primary);
  const mode: AIFallbackMode = opts.fallbackMode ?? "error_only";

  // No fallback available → just call primary
  if (!fallback) {
    const result = await callProvider(primary, opts);
    return { ...result, provider: primary, usedFallback: false, fallbackMode: mode };
  }

  if (mode === "race_both") {
    return raceProviders(primary, fallback, opts, mode);
  }

  return errorOnlyFallback(primary, fallback, opts, mode);
}

// ---------- error_only strategy ----------

async function errorOnlyFallback(
  primary: AIProvider,
  fallback: AIProvider,
  opts: { system: string; userPrompt: string; model?: string; maxTokens?: number },
  mode: AIFallbackMode,
): Promise<AICallResult> {
  try {
    const result = await callProvider(primary, opts);
    return { ...result, provider: primary, usedFallback: false, fallbackMode: mode };
  } catch (primaryErr) {
    console.warn(
      `[callAI:error_only] ${primary} failed: ${primaryErr instanceof Error ? primaryErr.message : String(primaryErr)}. Falling back to ${fallback}.`,
    );

    try {
      const result = await callProvider(fallback, { ...opts, model: undefined });
      return { ...result, provider: fallback, usedFallback: true, fallbackMode: mode };
    } catch (fallbackErr) {
      const msg = primaryErr instanceof Error ? primaryErr.message : String(primaryErr);
      const fbMsg = fallbackErr instanceof Error ? fallbackErr.message : String(fallbackErr);
      throw new Error(`AI niedostępne. ${primary}: ${msg} | Fallback (${fallback}): ${fbMsg}`);
    }
  }
}

// ---------- race_both strategy ----------

async function raceProviders(
  primary: AIProvider,
  fallback: AIProvider,
  opts: { system: string; userPrompt: string; model?: string; maxTokens?: number },
  mode: AIFallbackMode,
): Promise<AICallResult> {
  type Tagged = { provider: AIProvider; result: AnthropicResult };

  const primaryPromise: Promise<Tagged> = callProvider(primary, opts)
    .then((result) => ({ provider: primary, result }));

  const fallbackPromise: Promise<Tagged> = callProvider(fallback, { ...opts, model: undefined })
    .then((result) => ({ provider: fallback, result }));

  // Promise.any resolves with the first fulfilled; rejects only if ALL reject.
  try {
    const winner = await Promise.any([primaryPromise, fallbackPromise]);

    console.info(
      `[callAI:race_both] Winner: ${winner.provider} (model: ${winner.result.model})`,
    );

    return {
      ...winner.result,
      provider: winner.provider,
      usedFallback: winner.provider !== primary,
      fallbackMode: mode,
    };
  } catch (aggregateErr) {
    // AggregateError — both failed
    const errors = (aggregateErr as AggregateError).errors ?? [aggregateErr];
    const msgs = errors.map((e: unknown) => (e instanceof Error ? e.message : String(e)));
    throw new Error(
      `AI niedostępne (oba dostawcy). ${primary}: ${msgs[0] ?? "?"} | ${fallback}: ${msgs[1] ?? "?"}`,
    );
  }
}
