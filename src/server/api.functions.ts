import { createServerFn } from "@tanstack/react-start";
import { z } from "zod";
import { supabaseAdmin } from "@/integrations/supabase/client.server";
import { SYSTEM_PROMPT } from "./prompts/system-prompt";
import { parseAnalysisJson, DEFAULT_ANTHROPIC_MODEL } from "./anthropic.server";
import { callAI, detectProvider } from "./ai.server";
import { DEFAULT_GEMINI_MODEL } from "./gemini.server";
import { renderReportHtml, renderMailHtml } from "./report";
import { makeLogger } from "./logger.server";
import type { CarLot, ClientCriteria, AIAnalysis, AnalyzedLot } from "@/lib/types";
import { LOT_SYSTEM_PROMPT } from "./prompts/lot-prompt";
import { buildBrokerHtml, buildClientHtml, fetchImagesAsBase64, type Lot } from "./lot-report";
import { validateArtifactsMeta } from "./validate-artifacts-meta";

// ---------- Clients ----------

export const listClients = createServerFn({ method: "GET" }).handler(async () => {
  const { data, error } = await supabaseAdmin
    .from("clients")
    .select("*")
    .order("created_at", { ascending: false });
  if (error) throw new Error(error.message);
  return data ?? [];
});

export const createClient = createServerFn({ method: "POST" })
  .inputValidator(
    z.object({
      name: z.string().min(1).max(200),
      contact: z.string().max(500).optional().nullable(),
      notes: z.string().max(5000).optional().nullable(),
    }).parse,
  )
  .handler(async ({ data }) => {
    const { data: row, error } = await supabaseAdmin
      .from("clients")
      .insert({ name: data.name, contact: data.contact ?? null, notes: data.notes ?? null })
      .select()
      .single();
    if (error) throw new Error(error.message);
    return row;
  });

export const deleteClient = createServerFn({ method: "POST" })
  .inputValidator(z.object({ id: z.string().uuid() }).parse)
  .handler(async ({ data }) => {
    const { error } = await supabaseAdmin.from("clients").delete().eq("id", data.id);
    if (error) throw new Error(error.message);
    return { ok: true };
  });

// ---------- Records ----------

export const listRecords = createServerFn({ method: "GET" })
  .inputValidator(z.object({ clientId: z.string().uuid().optional() }).parse)
  .handler(async ({ data }) => {
    let q = supabaseAdmin
      .from("records")
      .select("id, client_id, title, status, created_at, updated_at, analysis_status, analysis_started_at, analysis_completed_at, artifacts_meta, analysis_error, retry_count, max_retries, next_retry_at, last_error_at")
      .order("created_at", { ascending: false })
      .limit(200);
    if (data.clientId) q = q.eq("client_id", data.clientId);
    const { data: rows, error } = await q;
    if (error) throw new Error(error.message);
    return rows ?? [];
  });

export const loadRecord = createServerFn({ method: "GET" })
  .inputValidator(z.object({ id: z.string().uuid() }).parse)
  .handler(async ({ data }) => {
    const { data: row, error } = await supabaseAdmin
      .from("records")
      .select("*")
      .eq("id", data.id)
      .single();
    if (error) throw new Error(error.message);
    return row;
  });

const recordPayloadSchema = z.object({
  id: z.string().uuid().optional(),
  client_id: z.string().uuid().nullable().optional(),
  title: z.string().max(300).optional().nullable(),
  status: z.string().max(40).default("draft"),
  criteria: z.any(),
  listings: z.any(),
  ai_input: z.any().optional().nullable(),
  ai_prompt: z.string().optional().nullable(),
  analysis: z.any().optional().nullable(),
  report_html: z.string().optional().nullable(),
  mail_html: z.string().optional().nullable(),
  analysis_status: z.string().max(40).optional().nullable(),
  analysis_started_at: z.string().optional().nullable(),
  analysis_completed_at: z.string().optional().nullable(),
  artifacts_meta: z.any().optional().nullable(),
  analysis_error: z.string().max(5000).optional().nullable(),
  retry_count: z.number().int().min(0).optional(),
  max_retries: z.number().int().min(0).max(10).optional(),
  next_retry_at: z.string().optional().nullable(),
  last_error_at: z.string().optional().nullable(),
});

// Validate artifacts_meta consistency with actual fields after save
// validateArtifactsMeta is imported from ./validate-artifacts-meta

export const saveRecord = createServerFn({ method: "POST" })
  .inputValidator(recordPayloadSchema.parse)
  .handler(async ({ data }) => {
    const payload = { ...data, updated_at: new Date().toISOString() };
    let row: Record<string, unknown>;

    if (data.id) {
      const { data: r, error } = await supabaseAdmin
        .from("records")
        .update(payload)
        .eq("id", data.id)
        .select()
        .single();
      if (error) throw new Error(error.message);
      row = r as Record<string, unknown>;
    } else {
      const { id: _ignore, ...insertPayload } = payload;
      const { data: r, error } = await supabaseAdmin
        .from("records")
        .insert(insertPayload)
        .select()
        .single();
      if (error) throw new Error(error.message);
      row = r as Record<string, unknown>;
    }

    // Post-save validation: fix artifacts_meta inconsistencies
    const validation = validateArtifactsMeta(row);
    if (validation.corrected_meta) {
      const { error: patchErr } = await supabaseAdmin
        .from("records")
        .update({ artifacts_meta: JSON.parse(JSON.stringify(validation.corrected_meta)) })
        .eq("id", row.id as string);
      if (!patchErr) {
        row.artifacts_meta = validation.corrected_meta;
      }
      if (validation.warnings.length > 0) {
        console.warn(`[saveRecord] artifacts_meta corrected for ${String(row.id)}:`, validation.warnings);
      }
    }

    return { ...row, _artifacts_warnings: validation.warnings.length > 0 ? validation.warnings : undefined };
  });

export const deleteRecord = createServerFn({ method: "POST" })
  .inputValidator(z.object({ id: z.string().uuid() }).parse)
  .handler(async ({ data }) => {
    const { error } = await supabaseAdmin.from("records").delete().eq("id", data.id);
    if (error) throw new Error(error.message);
    return { ok: true };
  });

// ---------- App config ----------

export const getConfig = createServerFn({ method: "GET" }).handler(async () => {
  const { data, error } = await supabaseAdmin.from("app_config").select("*").eq("id", 1).single();
  if (error) throw new Error(error.message);
  const provider = detectProvider();
  return {
    config: data,
    env: {
      ANTHROPIC_API_KEY: !!process.env.ANTHROPIC_API_KEY,
      ANTHROPIC_MODEL: process.env.ANTHROPIC_MODEL || DEFAULT_ANTHROPIC_MODEL,
      ANTHROPIC_BASE_URL: process.env.ANTHROPIC_BASE_URL || "https://api.anthropic.com",
      GEMINI_API_KEY: !!process.env.GEMINI_API_KEY,
      GEMINI_MODEL: process.env.GEMINI_MODEL || DEFAULT_GEMINI_MODEL,
      AI_PROVIDER: provider,
      SCRAPER_BASE_URL: !!process.env.SCRAPER_BASE_URL,
      SCRAPER_API_TOKEN: !!process.env.SCRAPER_API_TOKEN,
    },
  };
});

export const updateConfig = createServerFn({ method: "POST" })
  .inputValidator(
    z.object({
      use_mock_data: z.boolean().optional(),
      ai_analysis_mode: z.enum(["anthropic", "auto", "openai", "local"]).optional(),
      filter_seller_insurance_only: z.boolean().optional(),
      min_auction_window_hours: z.number().int().min(0).max(720).optional(),
      max_auction_window_hours: z.number().int().min(0).max(720).optional(),
      collect_all_prefiltered_results: z.boolean().optional(),
      open_all_prefiltered_details: z.boolean().optional(),
    }).parse,
  )
  .handler(async ({ data }) => {
    const { data: row, error } = await supabaseAdmin
      .from("app_config")
      .update({ ...data, updated_at: new Date().toISOString() })
      .eq("id", 1)
      .select()
      .single();
    if (error) throw new Error(error.message);
    return row;
  });

// ---------- Anthropic connection test ----------

export const testAnthropic = createServerFn({ method: "POST" })
  .inputValidator(z.object({ model: z.string().max(100).optional() }).parse)
  .handler(async ({ data }) => {
    const apiKey = process.env.ANTHROPIC_API_KEY;
    if (!apiKey) {
      return {
        ok: false,
        configured: false,
        error: "Brak ANTHROPIC_API_KEY w sekretach Lovable Cloud. Dodaj sekret i spróbuj ponownie.",
      };
    }
    const baseUrl = (process.env.ANTHROPIC_BASE_URL ?? "https://api.anthropic.com").replace(/\/+$/, "");
    const model = data.model || process.env.ANTHROPIC_MODEL || DEFAULT_ANTHROPIC_MODEL;
    try {
      const res = await fetch(`${baseUrl}/v1/messages`, {
        method: "POST",
        headers: {
          "x-api-key": apiKey,
          "anthropic-version": "2023-06-01",
          "content-type": "application/json",
        },
        body: JSON.stringify({
          model,
          max_tokens: 16,
          messages: [{ role: "user", content: "ping" }],
        }),
      });
      if (!res.ok) {
        const body = await res.text().catch(() => "");
        return {
          ok: false,
          configured: true,
          status: res.status,
          model,
          error: `Anthropic HTTP ${res.status}: ${body.slice(0, 300)}`,
        };
      }
      const json: {
        content?: Array<{ type: string; text?: string }>;
        usage?: { input_tokens?: number; output_tokens?: number };
        model?: string;
      } = await res.json();
      const text = (json.content ?? []).filter((c) => c.type === "text").map((c) => c.text).join("");
      return {
        ok: true,
        configured: true,
        model: json.model ?? model,
        baseUrl,
        sample: text.slice(0, 80),
        usage: {
          input_tokens: json.usage?.input_tokens ?? 0,
          output_tokens: json.usage?.output_tokens ?? 0,
        },
      };
    } catch (e) {
      return {
        ok: false,
        configured: true,
        model,
        error: e instanceof Error ? e.message : String(e),
      };
    }
  });

// ---------- Gemini connection test ----------

export const testGemini = createServerFn({ method: "POST" })
  .inputValidator(z.object({ model: z.string().max(100).optional() }).parse)
  .handler(async ({ data }) => {
    const apiKey = process.env.GEMINI_API_KEY;
    if (!apiKey) {
      return {
        ok: false,
        configured: false,
        error: "Brak GEMINI_API_KEY w sekretach Lovable Cloud. Dodaj sekret i spróbuj ponownie.",
      };
    }
    const model = data.model || process.env.GEMINI_MODEL || DEFAULT_GEMINI_MODEL;
    try {
      const url = `https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent?key=${apiKey}`;
      const res = await fetch(url, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          contents: [{ role: "user", parts: [{ text: "ping" }] }],
          generationConfig: { maxOutputTokens: 16 },
        }),
      });
      if (!res.ok) {
        const body = await res.text().catch(() => "");
        return {
          ok: false,
          configured: true,
          status: res.status,
          model,
          error: `Gemini HTTP ${res.status}: ${body.slice(0, 300)}`,
        };
      }
      const json = await res.json() as {
        candidates?: Array<{ content?: { parts?: Array<{ text?: string }> } }>;
        usageMetadata?: { promptTokenCount?: number; candidatesTokenCount?: number };
        modelVersion?: string;
      };
      const text = (json.candidates?.[0]?.content?.parts ?? []).map((p) => p.text ?? "").join("");
      return {
        ok: true,
        configured: true,
        model: json.modelVersion ?? model,
        sample: text.slice(0, 80),
        usage: {
          input_tokens: json.usageMetadata?.promptTokenCount ?? 0,
          output_tokens: json.usageMetadata?.candidatesTokenCount ?? 0,
        },
      };
    } catch (e) {
      return {
        ok: false,
        configured: true,
        model,
        error: e instanceof Error ? e.message : String(e),
      };
    }
  });

// ---------- AI analysis ----------

type LotForPrompt = {
  lot_id: string;
  source: string | null | undefined;
  url: string | null;
  vin: string | null;
  year: number | null | undefined;
  make: string | null | undefined;
  model: string | null | undefined;
  trim: string | null;
  odometer_mi: number | null | undefined;
  odometer_km: number | null | undefined;
  damage_primary: string | null | undefined;
  damage_secondary: string | null;
  title_type: string | null | undefined;
  current_bid_usd: number | null | undefined;
  buy_now_price_usd: number | null;
  seller_reserve_usd: number | null | undefined;
  seller_type: string | null | undefined;
  location_state: string | null | undefined;
  location_city: string | null;
  auction_date: string | null;
  airbags_deployed: boolean | null | undefined;
  keys: boolean | null | undefined;
  enriched_by_extension: boolean | null | undefined;
};

function lotsToPromptShape(lots: CarLot[]): LotForPrompt[] {
  return lots.map((lot) => ({
    lot_id: lot.lot_id,
    source: lot.source,
    url: lot.url ?? null,
    vin: lot.vin ?? null,
    year: lot.year,
    make: lot.make,
    model: lot.model,
    trim: lot.trim ?? null,
    odometer_mi: lot.odometer_mi,
    odometer_km: lot.odometer_km,
    damage_primary: lot.damage_primary,
    damage_secondary: lot.damage_secondary ?? null,
    title_type: lot.title_type,
    current_bid_usd: lot.current_bid_usd,
    buy_now_price_usd: lot.buy_now_price_usd ?? null,
    seller_reserve_usd: lot.seller_reserve_usd,
    seller_type: lot.seller_type,
    location_state: lot.location_state,
    location_city: lot.location_city ?? null,
    auction_date: lot.auction_date ?? null,
    airbags_deployed: lot.airbags_deployed,
    keys: lot.keys,
    enriched_by_extension: lot.enriched_by_extension ?? null,
  }));
}

function buildUserPromptFromShape(criteria: ClientCriteria, lotsData: LotForPrompt[]): string {
  const excluded =
    criteria.excluded_damage_types && criteria.excluded_damage_types.length > 0
      ? criteria.excluded_damage_types.join(", ")
      : "Flood, Fire";
  return `
Kryteria klienta:
- Marka/model: ${criteria.make} ${criteria.model || "(dowolny)"}
- Rocznik: ${criteria.year_from || "dowolny"}–${criteria.year_to || "dowolny"}
- Budżet maksymalny: ${criteria.budget_usd} USD (łącznie z transportem i naprawą)
- Maksymalny przebieg: ${criteria.max_odometer_mi || "bez limitu"} mil
- Wykluczone typy uszkodzeń: ${excluded}

Oceń poniższe ${lotsData.length} lotów:

${JSON.stringify(lotsData, null, 2)}

Dla każdego lota zwróć obiekt JSON z polami:
- lot_id (string, dokładnie jak w danych wejściowych)
- score (liczba 0.0–10.0)
  WAŻNE: Dodaj +1.5 do score dla stanów wschodnich (NY,NJ,PA,CT,MA,RI,VT,NH,ME,MD,DE,VA,NC,SC,GA,FL)
  WAŻNE: Odejmij -1.0 od score dla stanów zachodnich (CA,OR,WA,NV,AZ,UT,CO,NM)
- recommendation (string: dokładnie "POLECAM", "RYZYKO" lub "ODRZUĆ")
- red_flags (array of strings)
- estimated_repair_usd (int lub null)
- estimated_total_cost_usd (int — bid + naprawa + transport(zależny od lokalizacji) + 500 inne)
- client_description_pl (string — 3-5 zdań po polsku, szczegółowo)
- ai_notes (string — szczegółowe uwagi techniczne dla brokera po polsku)

Zwróć WYŁĄCZNIE poprawny JSON array. Bez żadnego tekstu przed ani po.
`.trim();
}

function buildUserPrompt(criteria: ClientCriteria, lots: CarLot[]): string {
  return buildUserPromptFromShape(criteria, lotsToPromptShape(lots));
}

// Approximate token count. Anthropic/OpenAI tokenizers average ~3.5–4 chars per
// token for mixed PL/EN + JSON. We use 3.5 conservatively (over-estimates rather
// than under).
function estimateTokens(text: string): number {
  return Math.ceil(text.length / 3.5);
}

// Strip optional fields to shrink JSON when the prompt is too large.
function compactLots(lots: LotForPrompt[]): LotForPrompt[] {
  return lots.map((l) => ({
    ...l,
    url: null,
    vin: null,
    trim: null,
    location_city: null,
    damage_secondary: null,
    auction_date: null,
    enriched_by_extension: null,
  }));
}

/**
 * Iteratively shrink the prompt until input tokens + reserved output budget fit
 * within a safe context window. Strategy:
 *   1) build full prompt
 *   2) if too big — drop verbose optional fields
 *   3) if still too big — drop lots from the end (input is already sorted by
 *      relevance from the scraper) until we fit
 *
 * Returns the final prompt + the lot ids actually included so the caller can
 * match Anthropic's response back to the original CarLot objects.
 */
function buildPromptWithinBudget(
  criteria: ClientCriteria,
  lots: CarLot[],
  reservedOutputTokens: number,
  // Conservative budget. Claude 3.5/4 has 200k context; leave headroom for
  // system prompt + cache + safety margin.
  contextBudgetTokens = 180_000,
): {
  prompt: string;
  includedLotIds: string[];
  trimmed: { droppedFields: boolean; droppedLots: number; finalCount: number };
} {
  const fullShape = lotsToPromptShape(lots);
  const inputBudget = Math.max(1000, contextBudgetTokens - reservedOutputTokens);

  let shape = fullShape;
  let prompt = buildUserPromptFromShape(criteria, shape);
  let droppedFields = false;
  let droppedLots = 0;

  if (estimateTokens(prompt) <= inputBudget) {
    return {
      prompt,
      includedLotIds: shape.map((l) => l.lot_id),
      trimmed: { droppedFields: false, droppedLots: 0, finalCount: shape.length },
    };
  }

  // Step 2: drop optional fields.
  shape = compactLots(shape);
  droppedFields = true;
  prompt = buildUserPromptFromShape(criteria, shape);

  // Step 3: drop tail lots until under budget. Keep at least 1.
  while (estimateTokens(prompt) > inputBudget && shape.length > 1) {
    shape = shape.slice(0, -1);
    droppedLots += 1;
    prompt = buildUserPromptFromShape(criteria, shape);
  }

  return {
    prompt,
    includedLotIds: shape.map((l) => l.lot_id),
    trimmed: { droppedFields, droppedLots, finalCount: shape.length },
  };
}

const criteriaSchema = z.object({
  make: z.string().min(1).max(80),
  model: z.string().max(80).nullable().optional(),
  year_from: z.number().int().min(1900).max(2100).nullable().optional(),
  year_to: z.number().int().min(1900).max(2100).nullable().optional(),
  budget_usd: z.number().min(0).max(1_000_000).transform((v) => v || 15000),
  max_odometer_mi: z.number().int().min(0).max(1_000_000).nullable().optional(),
  excluded_damage_types: z.array(z.string().max(40)).max(20).optional(),
  max_results: z.number().int().min(1).max(100).optional(),
  sources: z.array(z.string().max(20)).max(5).optional(),
});

const lotSchema: z.ZodType<CarLot> = z
  .object({
    source: z.string().max(40),
    lot_id: z.string().max(80),
  })
  .passthrough() as unknown as z.ZodType<CarLot>;

export const runAnalysis = createServerFn({ method: "POST" })
  .inputValidator(
    z.object({
      criteria: criteriaSchema,
      listings: z.array(lotSchema).min(1).max(100),
      clientId: z.string().uuid().nullable().optional(),
      recordId: z.string().uuid().nullable().optional(),
    }).parse,
  )
  .handler(async ({ data }): Promise<{
    ai_input: { criteria: ClientCriteria; listings: CarLot[] };
    ai_prompt: string;
    analysis: AnalyzedLot[];
  }> => {
    const log = makeLogger({
      operation: "ai_analysis",
      clientId: data.clientId ?? null,
      recordId: data.recordId ?? null,
    });
    const startedAt = Date.now();
    const criteria = data.criteria as ClientCriteria;
    const listings = data.listings as CarLot[];

    // Read DB-stored AI provider preference
    const { data: cfgRow } = await supabaseAdmin.from("app_config").select("ai_analysis_mode").eq("id", 1).single();
    const dbPreference = cfgRow?.ai_analysis_mode ?? null;
    // Default 4096 — Anthropic responses for typical batches (≤30 lots) fit in
    // ~3-4k tokens. Cap higher only via env override. Keeps response time and
    // cost predictable, also reduces 524 timeout risk.
    const maxTokens = Math.min(
      parseInt(process.env.ANTHROPIC_MAX_TOKENS ?? "0", 10) ||
        Math.max(1500, listings.length * 300),
      4096,
    );

    // Auto-trim prompt if input + reserved output would overflow context window.
    const built = buildPromptWithinBudget(criteria, listings, maxTokens);
    const userPrompt = built.prompt;
    const trimmedListings =
      built.trimmed.droppedLots > 0
        ? listings.filter((l) => built.includedLotIds.includes(l.lot_id))
        : listings;

    await log.info("start", `Rozpoczęto analizę AI ${trimmedListings.length} lotów`, {
      listings_count: trimmedListings.length,
      original_listings_count: listings.length,
      criteria_make: criteria.make,
      criteria_model: criteria.model ?? null,
      budget_usd: criteria.budget_usd,
      prompt_chars: userPrompt.length,
      max_tokens: maxTokens,
      auto_trimmed: built.trimmed.droppedLots > 0 || built.trimmed.droppedFields,
      dropped_optional_fields: built.trimmed.droppedFields,
      dropped_lots: built.trimmed.droppedLots,
    });

    if (built.trimmed.droppedLots > 0 || built.trimmed.droppedFields) {
      await log.warn(
        "prompt_trimmed",
        `Prompt skrócony automatycznie: ${built.trimmed.droppedLots > 0 ? `pominięto ${built.trimmed.droppedLots} lotów, ` : ""}${built.trimmed.droppedFields ? "usunięto opcjonalne pola (url, vin, trim, city, …)" : ""}`,
        {
          dropped_lots: built.trimmed.droppedLots,
          dropped_optional_fields: built.trimmed.droppedFields,
          final_lot_count: built.trimmed.finalCount,
        },
      );
    }

    let raw: string;
    try {
      const result = await callAI({ system: SYSTEM_PROMPT, userPrompt, maxTokens, dbPreference });
      raw = result.text;
      await log.info(
        "ai_response",
        `Odpowiedź AI [${result.provider}${result.usedFallback ? " (fallback)" : ""}]: ${raw.length} znaków, ${result.usage.input_tokens}+${result.usage.output_tokens} tokenów`,
        {
          response_chars: raw.length,
          model: result.model,
          provider: result.provider,
          used_fallback: result.usedFallback,
          stop_reason: result.stop_reason,
          usage: result.usage,
        },
        Date.now() - startedAt,
      );
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      await log.error("ai_call", `Błąd AI: ${msg}`, {
        error: msg,
        prompt_chars: userPrompt.length,
      });
      throw new Error(`AI API: ${msg}`);
    }

    let parsed: unknown;
    try {
      parsed = parseAnalysisJson(raw);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      await log.error("parse_json", `AI zwróciło niepoprawny JSON: ${msg}`, {
        error: msg,
        response_preview: raw.slice(0, 300),
      });
      throw new Error(
        `AI zwróciło niepoprawny JSON: ${msg}\nPierwsze 500 znaków odpowiedzi: ${raw.slice(0, 500)}`,
      );
    }
    if (!Array.isArray(parsed)) {
      await log.error("parse_json", "AI nie zwróciło tablicy JSON", {
        type: typeof parsed,
      });
      throw new Error("AI nie zwróciło tablicy JSON.");
    }

    const lotsById = new Map(listings.map((l) => [l.lot_id, l]));
    const analyzed: AnalyzedLot[] = [];
    let skipped = 0;
    for (const a of parsed as AIAnalysis[]) {
      const lot = lotsById.get(a.lot_id);
      if (!lot) {
        skipped++;
        continue;
      }
      analyzed.push({
        lot,
        analysis: {
          lot_id: a.lot_id,
          score: typeof a.score === "number" ? a.score : 0,
          recommendation: a.recommendation || "RYZYKO",
          red_flags: Array.isArray(a.red_flags) ? a.red_flags : [],
          estimated_repair_usd: a.estimated_repair_usd ?? null,
          estimated_total_cost_usd: a.estimated_total_cost_usd ?? null,
          client_description_pl: a.client_description_pl || "",
          ai_notes: a.ai_notes ?? null,
        },
      });
    }
    analyzed.sort((a, b) => b.analysis.score - a.analysis.score);

    if (skipped > 0) {
      await log.warn("match_lots", `Pominięto ${skipped} pozycji AI bez dopasowanego lota`, {
        skipped,
      });
    }

    const recs = analyzed.reduce<Record<string, number>>((acc, a) => {
      acc[a.analysis.recommendation] = (acc[a.analysis.recommendation] ?? 0) + 1;
      return acc;
    }, {});
    await log.info(
      "done",
      `Analiza zakończona: ${analyzed.length} lotów`,
      { analyzed_count: analyzed.length, recommendations: recs },
      Date.now() - startedAt,
    );

    return {
      ai_input: { criteria, listings },
      ai_prompt: userPrompt,
      analysis: analyzed,
    };
  });

// ---------- Report rendering ----------

export const renderReport = createServerFn({ method: "POST" })
  .inputValidator(
    z.object({
      clientName: z.string().min(1).max(200),
      analyzed: z.array(z.any()),
    }).parse,
  )
  .handler(async ({ data }) => {
    const generatedAt = new Date().toISOString().replace("T", " ").slice(0, 19);
    const lots = data.analyzed as AnalyzedLot[];
    const sorted = [...lots].sort((a, b) => b.analysis.score - a.analysis.score);
    return {
      report_html: renderReportHtml({
        clientName: data.clientName,
        generatedAt,
        lots: sorted,
      }),
      mail_html: renderMailHtml({
        clientName: data.clientName,
        generatedAt,
        topLots: sorted,
      }),
    };
  });

// ---------- Scraper bridge (optional) ----------

// Cache helpers ---------------------------------
const SCRAPE_CACHE_TTL_SECONDS = (() => {
  const raw = process.env.SCRAPE_CACHE_TTL_SECONDS;
  const n = raw ? parseInt(raw, 10) : NaN;
  return Number.isFinite(n) && n > 0 ? n : 3600; // default 1h
})();

// Build a stable cache key from criteria + config fields that affect scrape output.
async function buildScrapeCacheKey(
  criteria: ClientCriteria,
): Promise<{ key: string; configSnapshot: Record<string, unknown> }> {
  const { data: cfg } = await supabaseAdmin
    .from("app_config")
    .select(
      "max_auction_window_hours, min_auction_window_hours, filter_seller_insurance_only, open_all_prefiltered_details, collect_all_prefiltered_results",
    )
    .eq("id", 1)
    .maybeSingle();

  const configSnapshot = {
    max_auction_window_hours: cfg?.max_auction_window_hours ?? null,
    min_auction_window_hours: cfg?.min_auction_window_hours ?? null,
    filter_seller_insurance_only: cfg?.filter_seller_insurance_only ?? null,
    open_all_prefiltered_details: cfg?.open_all_prefiltered_details ?? null,
    collect_all_prefiltered_results: cfg?.collect_all_prefiltered_results ?? null,
  };

  // Normalize criteria: lower-case strings, sort arrays, drop undefined.
  const norm = {
    make: (criteria.make ?? "").trim().toLowerCase(),
    model: (criteria.model ?? "").trim().toLowerCase() || null,
    year_from: criteria.year_from ?? null,
    year_to: criteria.year_to ?? null,
    budget_usd: criteria.budget_usd ?? null,
    max_odometer_mi: criteria.max_odometer_mi ?? null,
    excluded_damage_types: [...(criteria.excluded_damage_types ?? [])]
      .map((s) => s.toLowerCase())
      .sort(),
    max_results: criteria.max_results ?? null,
    sources: [...(criteria.sources ?? [])].map((s) => s.toLowerCase()).sort(),
  };

  const payload = JSON.stringify({ criteria: norm, config: configSnapshot });
  // Use Web Crypto (Workers + Node 20) to hash without importing node:crypto.
  const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(payload));
  const hex = Array.from(new Uint8Array(buf))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
  return { key: hex, configSnapshot };
}

async function readScrapeCache(
  cacheKey: string,
): Promise<{ listings: CarLot[]; source: string; created_at: string } | null> {
  const { data } = await supabaseAdmin
    .from("scrape_cache")
    .select("listings, source, created_at, expires_at")
    .eq("cache_key", cacheKey)
    .gt("expires_at", new Date().toISOString())
    .maybeSingle();
  if (!data) return null;
  return {
    listings: (data.listings as CarLot[]) ?? [],
    source: (data.source as string) ?? "cache",
    created_at: data.created_at as string,
  };
}

async function writeScrapeCache(args: {
  cacheKey: string;
  criteria: ClientCriteria;
  configSnapshot: Record<string, unknown>;
  listings: CarLot[];
  source: string;
}): Promise<void> {
  const expiresAt = new Date(Date.now() + SCRAPE_CACHE_TTL_SECONDS * 1000).toISOString();
  await (supabaseAdmin.from("scrape_cache") as any).upsert(
    {
      cache_key: args.cacheKey,
      criteria: args.criteria,
      config_snapshot: args.configSnapshot,
      listings: args.listings,
      listings_count: args.listings.length,
      source: args.source,
      created_at: new Date().toISOString(),
      expires_at: expiresAt,
    },
    { onConflict: "cache_key" },
  );
}


export const runScraperSearch = createServerFn({ method: "POST" })
  .inputValidator(
    z.object({
      criteria: criteriaSchema,
      clientId: z.string().uuid().nullable().optional(),
      recordId: z.string().uuid().nullable().optional(),
    }).parse,
  )
  .handler(async ({ data }): Promise<{ listings: CarLot[]; source: string }> => {
    const log = makeLogger({
      operation: "scrape",
      clientId: data.clientId ?? null,
      recordId: data.recordId ?? null,
    });
    const startedAt = Date.now();

    // Mock data fallback — controlled via app_config.use_mock_data.
    const { data: cfg } = await supabaseAdmin
      .from("app_config")
      .select("use_mock_data")
      .eq("id", 1)
      .maybeSingle();
    if (cfg?.use_mock_data) {
      const listings = buildMockListings(data.criteria);
      await log.info(
        "done",
        `Mock: zwrócono ${listings.length} przykładowych lotów`,
        { listings_count: listings.length, source: "mock" },
        Date.now() - startedAt,
      );
      return { listings, source: "mock" };
    }

    const baseUrl = process.env.SCRAPER_BASE_URL?.replace(/\/+$/, "");
    const token = process.env.SCRAPER_API_TOKEN;
    if (!baseUrl) {
      await log.error("config", "Brak SCRAPER_BASE_URL w sekretach");
      throw new Error(
        "SCRAPER_BASE_URL nie jest ustawiony. Włącz tryb demo (mock data) w konfiguracji " +
          "albo ustaw sekrety SCRAPER_BASE_URL i SCRAPER_API_TOKEN.",
      );
    }

    await log.info("start", "Rozpoczęto wyszukiwanie online", {
      endpoint: `${baseUrl}/search`,
      auth: token ? "bearer" : "none",
      criteria_make: data.criteria.make,
      criteria_model: data.criteria.model ?? null,
      budget_usd: data.criteria.budget_usd,
    });

    let res: Response;
    try {
      res = await fetch(`${baseUrl}/search`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ criteria: data.criteria }),
      });
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      await log.error("network", `Błąd sieciowy: ${msg}`, {
        endpoint: `${baseUrl}/search`,
        error: msg,
      });
      throw new Error(`Scraper network error: ${msg}`);
    }

    if (!res.ok) {
      const body = await res.text().catch(() => "");
      await log.error(
        "http_error",
        `Scraper zwrócił HTTP ${res.status}`,
        { status: res.status, body_preview: body.slice(0, 300) },
      );
      throw new Error(`Scraper HTTP ${res.status}: ${body.slice(0, 400)}`);
    }

    let initial: { job_id?: string; status?: string; listings?: CarLot[] } | CarLot[];
    try {
      initial = await res.json();
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      await log.error("parse", `Niepoprawny JSON od scrapera: ${msg}`, { error: msg });
      throw new Error(`Scraper invalid JSON: ${msg}`);
    }

    let listings: CarLot[];

    // If backend returned listings synchronously, use them. Otherwise poll job.
    if (Array.isArray(initial)) {
      listings = initial as CarLot[];
    } else if (initial.listings && Array.isArray(initial.listings) && !initial.job_id) {
      listings = initial.listings;
    } else if (initial.job_id) {
      const jobId = initial.job_id;
      await log.info("queued", `Job ${jobId} w kolejce, polling...`, { job_id: jobId });

      const pollUrl = `${baseUrl}/api/jobs/${jobId}`;
      const deadline = Date.now() + 5 * 60 * 1000; // 5 min
      const pollIntervalMs = 4000;
      let lastStatus = "queued";
      listings = [];

      while (Date.now() < deadline) {
        await new Promise((r) => setTimeout(r, pollIntervalMs));
        let pollRes: Response;
        try {
          pollRes = await fetch(pollUrl, {
            headers: token ? { Authorization: `Bearer ${token}` } : {},
          });
        } catch (e) {
          const msg = e instanceof Error ? e.message : String(e);
          await log.warn("poll_network", `Polling network error: ${msg}`, { job_id: jobId, error: msg });
          continue;
        }
        if (!pollRes.ok) {
          const body = await pollRes.text().catch(() => "");
          await log.warn("poll_http", `Polling HTTP ${pollRes.status}`, {
            job_id: jobId,
            status: pollRes.status,
            body_preview: body.slice(0, 200),
          });
          continue;
        }
        let pj: { status?: string; listings?: CarLot[]; error?: string; progress?: number };
        try {
          pj = await pollRes.json();
        } catch {
          continue;
        }
        if (pj.status && pj.status !== lastStatus) {
          lastStatus = pj.status;
          await log.info("poll", `Job status: ${pj.status}`, { job_id: jobId, status: pj.status });
        }
        if (pj.status === "done" || pj.status === "completed" || pj.status === "finished" || pj.status === "success" || pj.status === "complete" || (typeof pj.progress === "number" && pj.progress >= 1.0)) {
          listings = Array.isArray(pj.listings) ? pj.listings : [];
          break;
        }
        if (pj.status === "error" || pj.status === "failed") {
          await log.error("job_failed", `Job zakończony błędem: ${pj.error ?? "unknown"}`, {
            job_id: jobId,
            error: pj.error,
          });
          throw new Error(`Scraper job failed: ${pj.error ?? "unknown"}`);
        }
      }

      if (lastStatus !== "done" && lastStatus !== "completed" && lastStatus !== "finished" && lastStatus !== "success" && lastStatus !== "complete") {
        await log.error("timeout", `Polling timeout po 5 min`, { job_id: jobId, last_status: lastStatus });
        throw new Error(`Scraper job timeout (job_id=${jobId}, last_status=${lastStatus})`);
      }
    } else {
      listings = [];
    }

    await log.info(
      "done",
      `Pobrano ${listings.length} ofert`,
      { listings_count: listings.length, source: baseUrl },
      Date.now() - startedAt,
    );

    return { listings, source: baseUrl };
  });

// Start scraper job — returns job_id immediately (or listings if backend is sync/mock).
export const startScraperSearch = createServerFn({ method: "POST" })
  .inputValidator(
    z.object({
      criteria: criteriaSchema,
      clientId: z.string().uuid().nullable().optional(),
      recordId: z.string().uuid().nullable().optional(),
    }).parse,
  )
  .handler(async ({ data }): Promise<
    | { mode: "sync"; listings: CarLot[]; source: string; cache_hit?: boolean; cache_key?: string }
    | { mode: "job"; job_id: string; source: string; cache_key: string }
  > => {
    const log = makeLogger({
      operation: "scrape",
      clientId: data.clientId ?? null,
      recordId: data.recordId ?? null,
    });


    // Mock mode short-circuit
    const { data: cfg } = await supabaseAdmin
      .from("app_config")
      .select("use_mock_data")
      .eq("id", 1)
      .maybeSingle();
    if (cfg?.use_mock_data) {
      const listings = buildMockListings(data.criteria);
      await log.info("done", `Mock: zwrócono ${listings.length} lotów`, {
        listings_count: listings.length,
        source: "mock",
      });
      return { mode: "sync", listings, source: "mock" };
    }

    // Cache lookup BEFORE hitting scraper.
    const { key: cacheKey, configSnapshot } = await buildScrapeCacheKey(data.criteria);
    const cached = await readScrapeCache(cacheKey);
    if (cached) {
      await log.info(
        "cache_hit",
        `Cache hit: ${cached.listings.length} lotów (zapisane: ${cached.created_at})`,
        {
          cache_key: cacheKey,
          listings_count: cached.listings.length,
          cached_at: cached.created_at,
        },
      );
      return {
        mode: "sync",
        listings: cached.listings,
        source: `cache:${cached.source}`,
        cache_hit: true,
        cache_key: cacheKey,
      };
    }

    const baseUrl = process.env.SCRAPER_BASE_URL?.replace(/\/+$/, "");
    const token = process.env.SCRAPER_API_TOKEN;
    if (!baseUrl) {
      await log.error("config", "Brak SCRAPER_BASE_URL");
      throw new Error("SCRAPER_BASE_URL nie jest ustawiony.");
    }

    await log.info("start", "Start wyszukiwania (job)", {
      endpoint: `${baseUrl}/search`,
      criteria_make: data.criteria.make,
      cache_key: cacheKey,
    });

    const res = await fetch(`${baseUrl}/search`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({ criteria: data.criteria }),
    });
    if (!res.ok) {
      const body = await res.text().catch(() => "");
      await log.error("http_error", `HTTP ${res.status}`, {
        status: res.status,
        body_preview: body.slice(0, 300),
      });
      throw new Error(`Scraper HTTP ${res.status}: ${body.slice(0, 400)}`);
    }
    const json = (await res.json()) as
      | { job_id?: string; status?: string; listings?: CarLot[] }
      | CarLot[];

    if (Array.isArray(json)) {
      await writeScrapeCache({
        cacheKey,
        criteria: data.criteria,
        configSnapshot,
        listings: json,
        source: baseUrl,
      });
      return { mode: "sync", listings: json, source: baseUrl, cache_hit: false, cache_key: cacheKey };
    }
    if (json.job_id) {
      await log.info("queued", `Job ${json.job_id} w kolejce`, {
        job_id: json.job_id,
        cache_key: cacheKey,
      });
      return { mode: "job", job_id: json.job_id, source: baseUrl, cache_key: cacheKey };
    }
    if (json.listings) {
      await writeScrapeCache({
        cacheKey,
        criteria: data.criteria,
        configSnapshot,
        listings: json.listings,
        source: baseUrl,
      });
      return {
        mode: "sync",
        listings: json.listings,
        source: baseUrl,
        cache_hit: false,
        cache_key: cacheKey,
      };
    }
    throw new Error("Scraper: brak job_id ani listings w odpowiedzi");
  });

// Poll scraper job status (called by UI every 4s).
export const pollScraperJob = createServerFn({ method: "POST" })
  .inputValidator(
    z.object({
      jobId: z.string().min(1),
      cacheKey: z.string().min(1).optional(),
      criteria: criteriaSchema.optional(),
    }).parse,
  )
  .handler(async ({ data }): Promise<{
    status: string;
    listings?: CarLot[];
    error?: string;
    progress?: number;
    step?: string;
    message?: string;
    current?: number;
    total?: number;
    phase?: string;
  }> => {
    const baseUrl = process.env.SCRAPER_BASE_URL?.replace(/\/+$/, "");
    const token = process.env.SCRAPER_API_TOKEN;
    if (!baseUrl) throw new Error("SCRAPER_BASE_URL nie jest ustawiony.");

    const log = makeLogger({ operation: "scrape", clientId: null, recordId: null });

    const res = await fetch(`${baseUrl}/api/jobs/${data.jobId}`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!res.ok) {
      const body = await res.text().catch(() => "");
      await log.warn("poll_http", `Poll HTTP ${res.status} dla job ${data.jobId}`, {
        job_id: data.jobId,
        http_status: res.status,
        body_preview: body.slice(0, 200),
      });
      // Return not_found so the client can clean up localStorage
      if (res.status === 404) {
        return { status: "not_found", error: `Job ${data.jobId} nie istnieje na serwerze scrapera.` };
      }
      throw new Error(`Poll HTTP ${res.status}: ${body.slice(0, 200)}`);
    }
    const j = (await res.json()) as {
      status?: string;
      listings?: CarLot[];
      error?: string;
      progress?: number;
      step?: string;
      message?: string;
      current?: number;
      total?: number;
      phase?: string;
    };

    const status = j.status ?? "unknown";
    const DONE_STATUSES = ["done", "completed", "finished", "success", "complete"];

    // Compose human-readable suffix for log message.
    const parts: string[] = [`status: ${status}`];
    if (j.phase) parts.push(`faza: ${j.phase}`);
    if (j.step) parts.push(`krok: ${j.step}`);
    if (typeof j.current === "number" && typeof j.total === "number") {
      parts.push(`${j.current}/${j.total}`);
    }
    if (typeof j.progress === "number") {
      parts.push(`${Math.round(j.progress * 100)}%`);
    }

    await log.info("poll", `Job ${data.jobId} — ${parts.join(" · ")}`, {
      job_id: data.jobId,
      status,
      progress: j.progress,
      step: j.step,
      phase: j.phase,
      current: j.current,
      total: j.total,
      message: j.message,
    });

    if (DONE_STATUSES.includes(status)) {
      await log.info("done", `Job ${data.jobId} zakończony, wyników: ${j.listings?.length ?? 0}`, {
        job_id: data.jobId,
        listings_count: j.listings?.length ?? 0,
      });
    } else if (status === "failed" || status === "error") {
      await log.error("job_failed", `Job ${data.jobId} zakończony błędem: ${j.error ?? "brak opisu"}`, {
        job_id: data.jobId,
        error: j.error,
      });
    }

    // Persist to cache when the job finishes successfully.
    if (
      DONE_STATUSES.includes(status) &&
      Array.isArray(j.listings) &&
      data.cacheKey &&
      data.criteria
    ) {
      try {
        const { configSnapshot } = await buildScrapeCacheKey(data.criteria);
        await writeScrapeCache({
          cacheKey: data.cacheKey,
          criteria: data.criteria,
          configSnapshot,
          listings: j.listings,
          source: baseUrl,
        });
      } catch {
        // Cache write failures should not break the user-visible flow.
      }
    }

    return {
      status,
      listings: j.listings,
      error: j.error,
      progress: typeof j.progress === "number" ? j.progress : undefined,
      step: j.step,
      message: j.message,
      current: typeof j.current === "number" ? j.current : undefined,
      total: typeof j.total === "number" ? j.total : undefined,
      phase: j.phase,
    };
  });

// Cancel a running scraper job.
// Clear scrape cache. Pass cacheKey to drop a single entry, or omit to wipe all.
export const clearScrapeCache = createServerFn({ method: "POST" })
  .inputValidator(
    z.object({
      cacheKey: z.string().min(1).optional(),
      onlyExpired: z.boolean().optional(),
    }).parse,
  )
  .handler(async ({ data }) => {
    let q = supabaseAdmin.from("scrape_cache").delete();
    if (data.cacheKey) {
      q = q.eq("cache_key", data.cacheKey);
    } else if (data.onlyExpired) {
      q = q.lt("expires_at", new Date().toISOString());
    } else {
      q = q.not("id", "is", null);
    }
    const { error, count } = await q;
    if (error) throw new Error(error.message);
    return { ok: true, deleted: count ?? null };
  });

export const cancelScraperJob = createServerFn({ method: "POST" })
  .inputValidator(
    z.object({
      jobId: z.string().min(1),
      clientId: z.string().uuid().nullable().optional(),
      recordId: z.string().uuid().nullable().optional(),
    }).parse,
  )
  .handler(async ({ data }): Promise<{ ok: boolean; status?: string }> => {
    const log = makeLogger({
      operation: "scrape",
      clientId: data.clientId ?? null,
      recordId: data.recordId ?? null,
    });
    const baseUrl = process.env.SCRAPER_BASE_URL?.replace(/\/+$/, "");
    const token = process.env.SCRAPER_API_TOKEN;
    if (!baseUrl) throw new Error("SCRAPER_BASE_URL nie jest ustawiony.");

    // Try DELETE /api/jobs/{id} first; fall back to POST /api/jobs/{id}/cancel.
    const headers: Record<string, string> = token ? { Authorization: `Bearer ${token}` } : {};
    let res = await fetch(`${baseUrl}/api/jobs/${data.jobId}`, {
      method: "DELETE",
      headers,
    }).catch(() => null);

    if (!res || !res.ok) {
      res = await fetch(`${baseUrl}/api/jobs/${data.jobId}/cancel`, {
        method: "POST",
        headers,
      }).catch(() => null);
    }

    if (!res || !res.ok) {
      const status = res?.status ?? 0;
      const body = res ? await res.text().catch(() => "") : "";
      await log.warn("cancel_failed", `Anulowanie nieudane (HTTP ${status})`, {
        job_id: data.jobId,
        status,
        body_preview: body.slice(0, 200),
      });
      throw new Error(`Cancel HTTP ${status}: ${body.slice(0, 200)}`);
    }

    let parsed: { status?: string } = {};
    try {
      parsed = await res.json();
    } catch {
      /* empty body is fine */
    }
    await log.info("cancelled", `Job ${data.jobId} anulowany`, { job_id: data.jobId });
    return { ok: true, status: parsed.status ?? "cancelled" };
  });

// ---------- Operation logs ----------

export const listLogs = createServerFn({ method: "GET" })
  .inputValidator(
    z.object({
      clientId: z.string().uuid().nullable().optional(),
      recordId: z.string().uuid().nullable().optional(),
      operation: z.string().max(40).optional(),
      levels: z.array(z.enum(["info", "warn", "error", "debug"])).max(4).optional(),
      from: z.string().datetime().optional(),
      to: z.string().datetime().optional(),
      limit: z.number().int().min(1).max(500).optional(),
    }).parse,
  )
  .handler(async ({ data }) => {
    let q = supabaseAdmin
      .from("operation_logs")
      .select("id, created_at, client_id, record_id, operation, step, level, message, details, duration_ms")
      .order("created_at", { ascending: false })
      .limit(data.limit ?? 100);
    if (data.clientId) q = q.eq("client_id", data.clientId);
    if (data.recordId) q = q.eq("record_id", data.recordId);
    if (data.operation) q = q.eq("operation", data.operation);
    if (data.levels && data.levels.length > 0) q = q.in("level", data.levels);
    if (data.from) q = q.gte("created_at", data.from);
    if (data.to) q = q.lte("created_at", data.to);
    const { data: rows, error } = await q;
    if (error) throw new Error(error.message);
    return rows ?? [];
  });

// Logs scoped to a specific scraper job_id. Combines local operation_logs
// (filtered by details->>job_id) with the scraper backend's own job logs if available.
export const getJobLogs = createServerFn({ method: "POST" })
  .inputValidator(z.object({ jobId: z.string().min(1) }).parse)
  .handler(async ({ data }) => {
    type LogRow = {
      id: string;
      created_at: string;
      level: string;
      step: string | null;
      message: string;
      details: any;
      source: "local" | "scraper";
    };

    // 1) Local operation_logs filtered by job_id stored in details.
    const { data: localRows, error } = await supabaseAdmin
      .from("operation_logs")
      .select("id, created_at, level, step, message, details")
      .eq("details->>job_id", data.jobId)
      .order("created_at", { ascending: true })
      .limit(500);

    const local: LogRow[] = (localRows ?? []).map((r) => ({
      id: r.id,
      created_at: r.created_at,
      level: r.level,
      step: r.step,
      message: r.message,
      details: r.details,
      source: "local" as const,
    }));

    // 2) Scraper backend logs (best-effort, not all backends expose this).
    let scraper: LogRow[] = [];
    let scraperFetchError: string | null = null;
    const baseUrl = process.env.SCRAPER_BASE_URL?.replace(/\/+$/, "");
    const token = process.env.SCRAPER_API_TOKEN;
    if (baseUrl) {
      try {
        const headers: Record<string, string> = token
          ? { Authorization: `Bearer ${token}` }
          : {};
        const res = await fetch(`${baseUrl}/api/jobs/${data.jobId}/logs`, { headers });
        if (res.ok) {
          const j = (await res.json()) as
            | Array<{
                ts?: string;
                timestamp?: string;
                level?: string;
                step?: string;
                message?: string;
                msg?: string;
                details?: unknown;
              }>
            | { logs?: unknown[] };
          const arr = Array.isArray(j) ? j : Array.isArray(j.logs) ? j.logs : [];
          scraper = arr.map((r, i) => {
            const row = r as {
              ts?: string;
              timestamp?: string;
              level?: string;
              step?: string;
              message?: string;
              msg?: string;
              details?: unknown;
            };
            return {
              id: `scraper-${i}`,
              created_at: row.ts ?? row.timestamp ?? new Date().toISOString(),
              level: row.level ?? "info",
              step: row.step ?? null,
              message: row.message ?? row.msg ?? "",
              details: row.details ?? null,
              source: "scraper" as const,
            };
          });
        } else if (res.status !== 404) {
          scraperFetchError = `Scraper /logs HTTP ${res.status}`;
        }
      } catch (e) {
        scraperFetchError = e instanceof Error ? e.message : String(e);
      }
    }

    const all = [...local, ...scraper].sort((a, b) =>
      a.created_at.localeCompare(b.created_at),
    );

    return {
      jobId: data.jobId,
      logs: all,
      local_error: error?.message ?? null,
      scraper_error: scraperFetchError,
    };
  });

export const clearLogs = createServerFn({ method: "POST" })
  .inputValidator(
    z.object({
      clientId: z.string().uuid().nullable().optional(),
    }).parse,
  )
  .handler(async ({ data }) => {
    let q = supabaseAdmin.from("operation_logs").delete();
    if (data.clientId) {
      q = q.eq("client_id", data.clientId);
    } else {
      // Delete all when no scope provided.
      q = q.not("id", "is", null);
    }
    const { error } = await q;
    if (error) throw new Error(error.message);
    return { ok: true };
  });

const DEFAULT_LOG_RETENTION_DAYS = 30;

function getLogRetentionDays(): number {
  const raw = process.env.LOG_RETENTION_DAYS;
  const parsed = raw ? parseInt(raw, 10) : NaN;
  if (!Number.isFinite(parsed) || parsed <= 0) return DEFAULT_LOG_RETENTION_DAYS;
  return Math.min(parsed, 3650);
}

export const getLogRetention = createServerFn({ method: "GET" }).handler(async () => {
  return {
    days: getLogRetentionDays(),
    default: DEFAULT_LOG_RETENTION_DAYS,
    source: process.env.LOG_RETENTION_DAYS ? "env" : "default",
  };
});

export const cleanupLogs = createServerFn({ method: "POST" }).handler(async () => {
  const days = getLogRetentionDays();
  const cutoff = new Date(Date.now() - days * 24 * 60 * 60 * 1000).toISOString();
  const { error, count } = await supabaseAdmin
    .from("operation_logs")
    .delete({ count: "exact" })
    .lt("created_at", cutoff);
  if (error) throw new Error(error.message);
  return { ok: true, retention_days: days, cutoff, deleted: count ?? 0 };
});

// ---------- Mock listings (demo / E2E test) ----------

function buildMockListings(criteria: ClientCriteria): CarLot[] {
  const make = criteria.make || "Audi";
  const model = criteria.model || "A5";
  const year = criteria.year_from || 2018;
  const budget = criteria.budget_usd || 15000;
  const wantCount = Math.min(Math.max(criteria.max_results ?? 12, 1), 50);

  const damages = [
    "FRONT END", "REAR END", "ALL OVER", "MINOR DENT/SCRATCHES",
    "HAIL", "SIDE", "UNDERCARRIAGE", "ROLLOVER", "MECHANICAL", "NORMAL WEAR",
  ];
  const states = ["NJ", "CA", "TX", "NY", "FL", "GA", "IL", "PA", "OH", "AZ"];
  const cities: Record<string, string> = {
    NJ: "Newark", CA: "Adelanto", TX: "Houston", NY: "Long Island",
    FL: "Miami", GA: "Atlanta", IL: "Chicago", PA: "Philadelphia",
    OH: "Columbus", AZ: "Phoenix",
  };
  const sources: Array<"copart" | "iaai"> = ["copart", "iaai"];
  const titleStatuses = ["CLEAN", "SALVAGE", "REBUILT"];

  const out: CarLot[] = [];
  for (let i = 1; i <= wantCount; i++) {
    const src = sources[i % 2];
    const state = states[i % states.length];
    const dmg = damages[i % damages.length];
    const bidFactor = 0.35 + ((i * 37) % 50) / 100; // 0.35–0.85
    const bid = Math.round(budget * bidFactor);
    const odo = 20000 + ((i * 9173) % 130000);
    out.push({
      source: src,
      lot_id: `${src.toUpperCase()}-${100000 + i}`,
      url: `https://example.${src}.com/lot/${100000 + i}`,
      make,
      model,
      year: year + (i % 6),
      odometer_mi: odo,
      vin: `WAU${(1000000000 + i).toString().padStart(14, "0")}`,
      damage_primary: dmg,
      damage_secondary: i % 3 === 0 ? "REAR END" : null,
      location_state: state,
      location_city: cities[state] ?? "Unknown",
      seller_type: i % 2 === 0 ? "INSURANCE COMPANY" : "DEALER",
      title_type: titleStatuses[i % titleStatuses.length],
      current_bid_usd: bid,
      buy_now_price_usd: bid + 1500,
      auction_date: new Date(Date.now() + (24 + i * 6) * 3600 * 1000).toISOString(),
      images: [`https://picsum.photos/seed/lot${i}/640/480`],
    });
  }
  return out;
}

// ---------- Lot reports (broker + klient) — port generatora z Pythona ----------

type LotMeta = { rank_group?: "TOP" | "REJECTED"; rank_position?: number; rank_reason?: string };

export const runLotReports = createServerFn({ method: "POST" })
  .inputValidator(
    z.object({
      criteria: criteriaSchema,
      listings: z.array(lotSchema).min(1).max(100),
      clientId: z.string().uuid().nullable().optional(),
      recordId: z.string().uuid().nullable().optional(),
    }).parse,
  )
  .handler(async ({ data }) => {
    const log = makeLogger({
      operation: "lot_reports",
      clientId: data.clientId ?? null,
      recordId: data.recordId ?? null,
    });
    const startedAt = Date.now();
    const criteria = data.criteria as ClientCriteria;
    const listings = data.listings as CarLot[];

    const userPrompt = `Kryteria klienta:
- Marka/model: ${criteria.make} ${criteria.model || "(dowolny)"}
- Rocznik: ${criteria.year_from || "?"}–${criteria.year_to || "?"}
- Budżet: ${criteria.budget_usd} USD
- Max przebieg: ${criteria.max_odometer_mi || "bez limitu"} mi
- Wykluczone uszkodzenia: ${(criteria.excluded_damage_types || ["Flood", "Fire"]).join(", ")}

Loty wejściowe (${listings.length}):
${JSON.stringify(listings, null, 2)}

Wybierz TOP3 + BOTTOM2 i zwróć tablicę kompletnych obiektów LOT zgodnych ze schematem w system prompt.`;

    await log.info("start", `Generuję raporty LOT (${listings.length} wejść)`, {
      listings_count: listings.length,
      prompt_chars: userPrompt.length,
    });

    let raw: string;
    try {
      const result = await callAI({
        system: LOT_SYSTEM_PROMPT,
        userPrompt,
        maxTokens: 16384,
      });
      raw = result.text;
      await log.info(
        "ai_response",
        `AI [${result.provider}${result.usedFallback ? " fallback" : ""}]: ${raw.length} znaków, ${result.usage.input_tokens}+${result.usage.output_tokens} tokenów`,
        { response_chars: raw.length, model: result.model, provider: result.provider, usage: result.usage },
        Date.now() - startedAt,
      );
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      await log.error("ai_call", `Błąd AI: ${msg}`);
      throw new Error(`AI API: ${msg}`);
    }

    let parsed: unknown;
    try {
      parsed = parseAnalysisJson(raw);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      await log.error("parse_json", `Niepoprawny JSON: ${msg}`, { preview: raw.slice(0, 400) });
      throw new Error(`AI zwróciło niepoprawny JSON: ${msg}`);
    }
    if (!Array.isArray(parsed)) {
      throw new Error("AI nie zwróciło tablicy LOT.");
    }

    type LotWithMeta = Lot & { _meta?: LotMeta };
    const lots = (parsed as LotWithMeta[]).filter((x) => x && typeof x === "object" && x.lot_id);

    const withImages = await Promise.all(
      lots.map(async (lot) => {
        const urls = Array.isArray(lot.image_urls) ? lot.image_urls : [];
        const images = await fetchImagesAsBase64(urls, 8);
        const meta = (lot._meta ?? {}) as LotMeta;
        const group: "TOP" | "REJECTED" = meta.rank_group === "REJECTED" ? "REJECTED" : "TOP";
        return { lot, images, group, meta };
      }),
    );

    withImages.sort((a, b) => {
      if (a.group !== b.group) return a.group === "TOP" ? -1 : 1;
      return (a.meta.rank_position ?? 99) - (b.meta.rank_position ?? 99);
    });

    const broker_html = buildBrokerHtml(
      withImages.map(({ lot, images, group }) => ({ lot, images, group })),
    );
    // Klient: TOP3 + 2 odrzucone (jako 4 i 5, bez wzmianki że to najgorsze — zabieg marketingowy).
    // Wszystkie 5 prezentowane jako równorzędna oferta.
    const tops = withImages.filter((x) => x.group === "TOP").slice(0, 3);
    const fillers = withImages.filter((x) => x.group === "REJECTED").slice(0, 2);
    const clientLots = [...tops, ...fillers];
    let client_html = "";
    if (clientLots.length > 0) {
      const docs = clientLots.map((t) => buildClientHtml(t.lot, t.images));
      // wyciągnij <body>...</body> z każdego, połącz w pierwszym dokumencie
      const bodies = docs.map((d) => {
        const m = d.match(/<body>([\s\S]*?)<\/body>/i);
        return m ? m[1] : d;
      });
      const separator = `<div style="height:24px;background:linear-gradient(180deg,#0a0e14 0%,transparent 100%)"></div>`;
      client_html = docs[0].replace(
        /<body>[\s\S]*?<\/body>/i,
        `<body>${bodies.join(separator)}</body>`,
      );
    }

    await log.info(
      "done",
      `Wygenerowano raporty: ${withImages.length} lotów (TOP=${withImages.filter((x) => x.group === "TOP").length}, REJ=${withImages.filter((x) => x.group === "REJECTED").length})`,
      { lots_count: withImages.length },
      Date.now() - startedAt,
    );

    return {
      report_html: broker_html,
      mail_html: client_html,
      lots: withImages.map(({ lot, group, meta }) => ({
        lot_id: lot.lot_id,
        score: lot.score,
        status: lot.status,
        group,
        rank_position: meta.rank_position ?? null,
        rank_reason: meta.rank_reason ?? null,
      })),
    };
  });


// ---------- Report bundle (HTML + JSON ZIP) ----------

export const getReportBundle = createServerFn({ method: "POST" })
  .inputValidator(z.object({ recordId: z.string().uuid() }).parse)
  .handler(async ({ data }): Promise<{
    filename: string;
    base64: string;
    size: number;
  }> => {
    const { zipSync, strToU8 } = await import("fflate");

    const { data: row, error } = await supabaseAdmin
      .from("records")
      .select("id, title, status, created_at, criteria, listings, analysis, report_html, mail_html, client_id, clients(name)")
      .eq("id", data.recordId)
      .maybeSingle();

    if (error) throw new Error(error.message);
    if (!row) throw new Error("Rekord nie istnieje");

    const analyzed = (row.analysis ?? []) as AnalyzedLot[];
    const clientName =
      (row.clients as { name?: string } | null)?.name ?? "Klient";
    const generatedAt = new Date().toISOString().replace("T", " ").slice(0, 19);

    // Render HTML on-the-fly if not stored yet (handles older records).
    let reportHtml = row.report_html as string | null;
    if (!reportHtml && analyzed.length > 0) {
      reportHtml = renderReportHtml({
        clientName,
        generatedAt,
        lots: [...analyzed].sort((a, b) => b.analysis.score - a.analysis.score),
      });
    }

    const meta = {
      record_id: row.id,
      title: row.title,
      status: row.status,
      created_at: row.created_at,
      generated_at: generatedAt,
      client: { id: row.client_id, name: clientName },
      criteria: row.criteria,
      lots_count: Array.isArray(row.listings) ? row.listings.length : 0,
      analyzed_count: analyzed.length,
    };

    const files: Record<string, Uint8Array> = {
      "report.html": strToU8(reportHtml ?? "<!doctype html><p>Brak raportu</p>"),
      "analysis.json": strToU8(JSON.stringify(analyzed, null, 2)),
      "lots.json": strToU8(JSON.stringify(row.listings ?? [], null, 2)),
      "meta.json": strToU8(JSON.stringify(meta, null, 2)),
    };
    if (row.mail_html) {
      files["mail.html"] = strToU8(row.mail_html as string);
    }

    const zipped = zipSync(files, { level: 6 });
    // Convert to base64 (chunked to avoid call-stack issues on Workers).
    let binary = "";
    const chunk = 0x8000;
    for (let i = 0; i < zipped.length; i += chunk) {
      binary += String.fromCharCode(...zipped.subarray(i, i + chunk));
    }
    const base64 = btoa(binary);

    const safeTitle = (row.title ?? "raport")
      .replace(/[^a-zA-Z0-9_-]+/g, "_")
      .slice(0, 60) || "raport";
    const datePart = new Date(row.created_at as string).toISOString().slice(0, 10);
    const filename = `${safeTitle}_${datePart}.zip`;

    return { filename, base64, size: zipped.length };
  });

// ---------- Retry logging ----------

export const logRetryEvent = createServerFn({ method: "POST" })
  .inputValidator((d: unknown) =>
    z.object({
      recordId: z.string(),
      clientId: z.string().optional(),
      criteria: z.record(z.unknown()),
      retryCount: z.number(),
      source: z.enum(["manual", "auto"]).default("manual"),
    }).parse(d),
  )
  .handler(async ({ data }) => {
    const log = makeLogger({
      operation: "ai_analysis",
      recordId: data.recordId,
      clientId: data.clientId ?? null,
    });
    await log.info("retry_start", `Ponowne uruchomienie analizy (${data.source}), próba ${data.retryCount + 1}`, {
      criteria: data.criteria,
      source: data.source,
      retry_count: data.retryCount,
    });
    return { ok: true };
  });
