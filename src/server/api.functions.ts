import { createServerFn } from "@tanstack/react-start";
import { z } from "zod";
import { supabaseAdmin } from "@/integrations/supabase/client.server";
import { SYSTEM_PROMPT } from "./prompts/system-prompt";
import { callAnthropic, parseAnalysisJson, DEFAULT_ANTHROPIC_MODEL, ANTHROPIC_MODELS } from "./anthropic.server";
import { renderReportHtml, renderMailHtml } from "./report";
import { makeLogger } from "./logger.server";
import type { CarLot, ClientCriteria, AIAnalysis, AnalyzedLot } from "@/lib/types";

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
      .select("id, client_id, title, status, created_at, updated_at")
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
});

export const saveRecord = createServerFn({ method: "POST" })
  .inputValidator(recordPayloadSchema.parse)
  .handler(async ({ data }) => {
    const payload = { ...data, updated_at: new Date().toISOString() };
    if (data.id) {
      const { data: row, error } = await supabaseAdmin
        .from("records")
        .update(payload)
        .eq("id", data.id)
        .select()
        .single();
      if (error) throw new Error(error.message);
      return row;
    }
    const { id: _ignore, ...insertPayload } = payload;
    const { data: row, error } = await supabaseAdmin
      .from("records")
      .insert(insertPayload)
      .select()
      .single();
    if (error) throw new Error(error.message);
    return row;
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
  return {
    config: data,
    env: {
      ANTHROPIC_API_KEY: !!process.env.ANTHROPIC_API_KEY,
      ANTHROPIC_MODEL: process.env.ANTHROPIC_MODEL || DEFAULT_ANTHROPIC_MODEL,
      ANTHROPIC_BASE_URL: process.env.ANTHROPIC_BASE_URL || "https://api.anthropic.com",
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
      const json: { content?: Array<{ type: string; text?: string }>; usage?: unknown } = await res.json();
      const text = (json.content ?? []).filter((c) => c.type === "text").map((c) => c.text).join("");
      return {
        ok: true,
        configured: true,
        model,
        baseUrl,
        sample: text.slice(0, 80),
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

function buildUserPrompt(criteria: ClientCriteria, lots: CarLot[]): string {
  const lotsData = lots.map((lot) => ({
    lot_id: lot.lot_id,
    source: lot.source,
    year: lot.year,
    make: lot.make,
    model: lot.model,
    odometer_mi: lot.odometer_mi,
    odometer_km: lot.odometer_km,
    damage_primary: lot.damage_primary,
    damage_secondary: lot.damage_secondary,
    title_type: lot.title_type,
    current_bid_usd: lot.current_bid_usd,
    seller_reserve_usd: lot.seller_reserve_usd,
    seller_type: lot.seller_type,
    location_state: lot.location_state,
    airbags_deployed: lot.airbags_deployed,
    keys: lot.keys,
    enriched_by_extension: lot.enriched_by_extension,
  }));
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

const criteriaSchema = z.object({
  make: z.string().min(1).max(80),
  model: z.string().max(80).nullable().optional(),
  year_from: z.number().int().min(1900).max(2100).nullable().optional(),
  year_to: z.number().int().min(1900).max(2100).nullable().optional(),
  budget_usd: z.number().min(1).max(1_000_000),
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
    const userPrompt = buildUserPrompt(criteria, listings);

    await log.info("start", `Rozpoczęto analizę AI ${listings.length} lotów`, {
      listings_count: listings.length,
      criteria_make: criteria.make,
      criteria_model: criteria.model ?? null,
      budget_usd: criteria.budget_usd,
      prompt_chars: userPrompt.length,
    });

    let raw: string;
    try {
      raw = await callAnthropic({ system: SYSTEM_PROMPT, userPrompt });
      await log.info(
        "anthropic_response",
        `Otrzymano odpowiedź z Anthropic (${raw.length} znaków)`,
        { response_chars: raw.length },
        Date.now() - startedAt,
      );
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      await log.error("anthropic_call", `Błąd wywołania Anthropic: ${msg}`, {
        error: msg,
        prompt_chars: userPrompt.length,
      });
      throw new Error(`Anthropic API: ${msg}`);
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
    const baseUrl = process.env.SCRAPER_BASE_URL?.replace(/\/+$/, "");
    const token = process.env.SCRAPER_API_TOKEN;
    if (!baseUrl) {
      await log.error("config", "Brak SCRAPER_BASE_URL w sekretach");
      throw new Error(
        "SCRAPER_BASE_URL nie jest ustawiony. Ustaw sekrety SCRAPER_BASE_URL i SCRAPER_API_TOKEN, " +
          "albo użyj wklejania ręcznego JSON z wynikami scrapera.",
      );
    }

    await log.info("start", "Rozpoczęto wyszukiwanie online", {
      endpoint: `${baseUrl}/api/search`,
      auth: token ? "bearer" : "none",
      criteria_make: data.criteria.make,
      criteria_model: data.criteria.model ?? null,
      budget_usd: data.criteria.budget_usd,
    });

    let res: Response;
    try {
      res = await fetch(`${baseUrl}/api/search`, {
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
        endpoint: `${baseUrl}/api/search`,
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

    let json: unknown;
    try {
      json = await res.json();
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      await log.error("parse", `Niepoprawny JSON od scrapera: ${msg}`, { error: msg });
      throw new Error(`Scraper invalid JSON: ${msg}`);
    }

    const listings = Array.isArray(json)
      ? (json as CarLot[])
      : (((json as { listings?: CarLot[] }).listings ?? []) as CarLot[]);

    await log.info(
      "done",
      `Pobrano ${listings.length} ofert`,
      { listings_count: listings.length, source: baseUrl },
      Date.now() - startedAt,
    );

    return { listings, source: baseUrl };
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
