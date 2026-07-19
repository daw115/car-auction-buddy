import { createServerFn } from "@tanstack/react-start";
import { z } from "zod";
import { supabaseAdmin } from "@/integrations/supabase/client.server";
import { DEFAULT_ANTHROPIC_MODEL } from "@/server/anthropic.server";
import { detectProvider } from "@/server/ai.server";
import { DEFAULT_GEMINI_MODEL } from "@/server/gemini.server";
import { makeLogger } from "@/server/logger.server";

// ---------- App config ----------

export const getConfig = createServerFn({ method: "GET" }).handler(async () => {
  const { data, error } = await supabaseAdmin.from("app_config").select("*").eq("id", 1).single();
  if (error) throw new Error(error.message);
  const provider = detectProvider(data?.ai_analysis_mode);
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
      ai_analysis_mode: z.enum(["anthropic", "gemini", "auto"]).optional(),
      ai_fallback_mode: z.enum(["error_only", "race_both"]).optional(),
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
    const url = `https://generativelanguage.googleapis.com/v1beta/models/${encodeURIComponent(model)}:generateContent?key=${apiKey}`;
    try {
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
      const json: {
        candidates?: Array<{ content?: { parts?: Array<{ text?: string }> } }>;
        usageMetadata?: { promptTokenCount?: number; candidatesTokenCount?: number };
      } = await res.json();
      const text = (json.candidates?.[0]?.content?.parts ?? []).map((p) => p.text ?? "").join("");
      return {
        ok: true,
        configured: true,
        model,
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

// ---------- Scraper jobs ----------

export const listActiveScraperJobs = createServerFn({ method: "GET" })
  .handler(async () => {
    const baseUrl = process.env.SCRAPER_BASE_URL?.replace(/\/+$/, "");
    const token = process.env.SCRAPER_API_TOKEN;
    if (!baseUrl) return { jobs: [], total: 0 };

    try {
      const res = await fetch(`${baseUrl}/api/jobs?active_only=true`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!res.ok) return { jobs: [], total: 0 };
      return (await res.json()) as {
        jobs: Array<{
          id: string;
          label: string;
          status: "queued" | "running" | "done" | "error" | "cancelled" | "interrupted";
          phase?: string | null;
          phase_info?: Record<string, any>;
          phases?: Array<{
            name: string;
            status: string;
            info?: Record<string, any>;
            started_at: string;
            finished_at?: string | null;
          }>;
          criteria?: Record<string, any>;
          created_at: string;
          finished_at?: string | null;
          listings_count?: number;
          analysis_notice?: string | null;
        }>;
        total: number;
      };
    } catch {
      return { jobs: [], total: 0 };
    }
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

// ---------- Search audit ----------

export type SearchAuditEntry = {
  id: string;
  created_at: string;
  searched_by: string | null;
  message: string;
  make: string | null;
  model: string | null;
  budget_usd: number | null;
  client_id: string | null;
  record_id: string | null;
};

export const listSearchAudit = createServerFn({ method: "GET" })
  .inputValidator(z.object({ limit: z.number().min(1).max(200).optional() }).parse)
  .handler(async ({ data }): Promise<{ entries: SearchAuditEntry[] }> => {
    const { data: rows, error } = await supabaseAdmin
      .from("operation_logs")
      .select("id, created_at, message, details, client_id, record_id")
      .eq("operation", "audit")
      .eq("step", "search.start")
      .order("created_at", { ascending: false })
      .limit(data.limit ?? 50);
    if (error) throw new Error(error.message);
    const entries: SearchAuditEntry[] = (rows ?? []).map((r: Record<string, unknown>) => {
      const d = (r.details ?? {}) as Record<string, unknown>;
      return {
        id: String(r.id),
        created_at: String(r.created_at),
        searched_by: (d.searched_by as string | null) ?? null,
        message: (r.message as string | null) ?? "",
        make: (d.make as string | null) ?? null,
        model: (d.model as string | null) ?? null,
        budget_usd: (d.budget_usd as number | null) ?? null,
        client_id: (r.client_id as string | null) ?? null,
        record_id: (r.record_id as string | null) ?? null,
      };
    });
    return { entries };
  });

// ---------- Health check ----------

type ServiceStatus = "ok" | "down" | "unconfigured";

export const checkHealth = createServerFn({ method: "GET" }).handler(async (): Promise<{
  checkedAt: string;
  durationMs: number;
  services: {
    database: { status: ServiceStatus; error?: string };
    scraper: { status: ServiceStatus; url?: string; error?: string };
    ai: { status: ServiceStatus; provider?: string; model?: string };
  };
}> => {
  const startedAt = Date.now();

  let dbStatus: ServiceStatus = "ok";
  let dbError: string | undefined;
  try {
    const { error } = await supabaseAdmin.from("app_config").select("id").limit(1);
    if (error) { dbStatus = "down"; dbError = error.message; }
  } catch (e) {
    dbStatus = "down";
    dbError = (e as Error).message;
  }

  const scraperUrl = process.env.SCRAPER_BASE_URL?.replace(/\/+$/, "");
  const scraperToken = process.env.SCRAPER_API_TOKEN;
  let scraperStatus: ServiceStatus = "unconfigured";
  let scraperError: string | undefined;
  if (scraperUrl) {
    try {
      const ctrl = new AbortController();
      const timer = setTimeout(() => ctrl.abort(), 5000);
      const res = await fetch(`${scraperUrl}/health`, {
        signal: ctrl.signal,
        headers: scraperToken ? { Authorization: `Bearer ${scraperToken}` } : {},
      });
      clearTimeout(timer);
      if (res.ok) {
        scraperStatus = "ok";
      } else {
        scraperStatus = "down";
        scraperError = `HTTP ${res.status}`;
      }
    } catch (e) {
      scraperStatus = "down";
      scraperError = (e as Error).message?.includes("abort") ? "Timeout (5s)" : (e as Error).message;
    }
  }

  const aiProvider = process.env.AI_PROVIDER || (process.env.ANTHROPIC_API_KEY ? "anthropic" : process.env.GEMINI_API_KEY ? "gemini" : "none");
  const hasAiKey = !!(process.env.ANTHROPIC_API_KEY || process.env.GEMINI_API_KEY);
  const aiModel = aiProvider === "anthropic"
    ? (process.env.ANTHROPIC_MODEL || "claude-sonnet-4-6")
    : aiProvider === "gemini"
      ? (process.env.GEMINI_MODEL || "gemini-2.5-flash")
      : undefined;

  return {
    checkedAt: new Date().toISOString(),
    durationMs: Date.now() - startedAt,
    services: {
      database: { status: dbStatus, error: dbError },
      scraper: { status: scraperStatus, url: scraperUrl ? new URL(scraperUrl).host : undefined, error: scraperError },
      ai: { status: hasAiKey ? "ok" : "unconfigured", provider: aiProvider !== "none" ? aiProvider : undefined, model: aiModel },
    },
  };
});

// ---------- LLM cache ----------

export const clearLlmCache = createServerFn({ method: "POST" })
  .handler(async () => {
    const baseUrl = process.env.SCRAPER_BASE_URL?.replace(/\/+$/, "");
    const token = process.env.SCRAPER_API_TOKEN;
    if (!baseUrl || !token) return { removed: 0 };
    try {
      const res = await fetch(`${baseUrl}/api/llm-cache`, {
        method: "DELETE",
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) return { removed: 0 };
      return res.json() as Promise<{ removed: number }>;
    } catch {
      return { removed: 0 };
    }
  });

// ---------- Database Browser (Python backend) ----------

export const getDbOverview = createServerFn({ method: "GET" }).handler(async () => {
  const baseUrl = process.env.SCRAPER_BASE_URL?.replace(/\/+$/, "");
  const token = process.env.SCRAPER_API_TOKEN;
  if (!baseUrl || !token) return null;
  try {
    const res = await fetch(`${baseUrl}/api/db/overview`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!res.ok) return null;
    return res.json();
  } catch {
    return null;
  }
});

export type BackendRecord = {
  id: number;
  title: string;
  status: "new" | "done" | "cancelled" | "error" | "interrupted";
  notes?: string | null;
  client?: { name?: string; email?: string; phone?: string } | null;
  collected_count: number;
  analysis_notice?: string | null;
  artifact_urls?: Record<string, string>;
  job_id?: string | null;
  searched_by?: string | null;
  created_at: string;
  updated_at: string;
};

export const getBackendRecordsList = createServerFn({ method: "GET" })
  .inputValidator(z.object({
    query: z.string().optional(),
    status: z.string().optional(),
    limit: z.number().optional(),
  }).parse)
  .handler(async ({ data }) => {
    const baseUrl = process.env.SCRAPER_BASE_URL?.replace(/\/+$/, "");
    const token = process.env.SCRAPER_API_TOKEN;
    if (!baseUrl || !token) return { records: [] as BackendRecord[], total: 0 };
    try {
      const params = new URLSearchParams();
      if (data.query) params.set("query", data.query);
      if (data.status) params.set("status", data.status);
      if (data.limit) params.set("limit", String(data.limit));
      const res = await fetch(`${baseUrl}/api/records?${params}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) return { records: [] as BackendRecord[], total: 0 };
      const json = await res.json() as { records: BackendRecord[]; total: number };
      return { records: json.records ?? [], total: json.total ?? 0 };
    } catch {
      return { records: [] as BackendRecord[], total: 0 };
    }
  });

export const deleteBackendRecord = createServerFn({ method: "POST" })
  .inputValidator(z.object({ id: z.coerce.string().min(1) }).parse)
  .handler(async ({ data }) => {
    const baseUrl = process.env.SCRAPER_BASE_URL?.replace(/\/+$/, "");
    const token = process.env.SCRAPER_API_TOKEN;
    if (!baseUrl || !token) {
      return { ok: false as const, status: 0, detail: "Backend nie skonfigurowany" };
    }
    try {
      const res = await fetch(`${baseUrl}/api/records/${data.id}`, {
        method: "DELETE",
        headers: { Authorization: `Bearer ${token}` },
      });
      const json = await res.json().catch(() => ({}));
      if (!res.ok) {
        return { ok: false as const, status: res.status, detail: (json as any)?.detail || `HTTP ${res.status}` };
      }
      return {
        ok: true as const,
        status: res.status,
        record_id: (json as any)?.record_id ?? data.id,
        files_removed: (json as any)?.files_removed ?? 0,
        bytes_freed: (json as any)?.bytes_freed ?? 0,
        skipped: (json as any)?.skipped ?? [],
      };
    } catch (e: any) {
      return { ok: false as const, status: 0, detail: e?.message || "Network error" };
    }
  });

export const getBackendRecordDetails = createServerFn({ method: "GET" })
  .inputValidator(z.object({ id: z.coerce.string().min(1) }).parse)
  .handler(async ({ data }) => {
    const baseUrl = process.env.SCRAPER_BASE_URL?.replace(/\/+$/, "");
    const token = process.env.SCRAPER_API_TOKEN;
    if (!baseUrl || !token) return null;
    try {
      const res = await fetch(`${baseUrl}/api/records/${data.id}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) return null;
      return res.json();
    } catch {
      return null;
    }
  });

// ---------- Lot feedback ----------

async function scraperFetch(path: string, init?: RequestInit) {
  const baseUrl = process.env.SCRAPER_BASE_URL?.replace(/\/+$/, "");
  const token = process.env.SCRAPER_API_TOKEN;
  if (!baseUrl || !token) throw new Error("Backend nie skonfigurowany");
  const res = await fetch(`${baseUrl}${path}`, {
    ...init,
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
      ...(init?.headers || {}),
    },
  });
  const json = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = (json as any)?.detail || `HTTP ${res.status}`;
    const err: any = new Error(detail);
    err.status = res.status;
    throw err;
  }
  return json;
}

export const getRecordFeedback = createServerFn({ method: "GET" })
  .inputValidator(z.object({ recordId: z.coerce.string().min(1) }).parse)
  .handler(async ({ data }) => {
    try {
      return await scraperFetch(`/api/records/${data.recordId}/feedback`);
    } catch {
      return { feedback: [], up: 0, down: 0, total: 0 };
    }
  });

export const submitLotFeedback = createServerFn({ method: "POST" })
  .inputValidator(z.object({
    recordId: z.coerce.string().min(1),
    lot_id: z.string().min(1),
    source: z.enum(["copart", "iaai"]),
    vote: z.enum(["up", "down"]),
    reason: z.string().max(500).optional(),
  }).parse)
  .handler(async ({ data }) => {
    const { recordId, ...body } = data;
    return await scraperFetch(`/api/records/${recordId}/feedback`, {
      method: "POST",
      body: JSON.stringify(body),
    });
  });

export const deleteLotFeedback = createServerFn({ method: "POST" })
  .inputValidator(z.object({
    recordId: z.coerce.string().min(1),
    lot_id: z.string().min(1),
    source: z.enum(["copart", "iaai"]),
  }).parse)
  .handler(async ({ data }) => {
    const params = new URLSearchParams({ source: data.source });
    return await scraperFetch(
      `/api/records/${data.recordId}/feedback/${data.lot_id}?${params}`,
      { method: "DELETE" },
    );
  });

export const analyzeFeedback = createServerFn({ method: "POST" })
  .handler(async () => {
    return await scraperFetch(`/api/feedback/analyze`, { method: "POST" });
  });

export const listAllJobs = createServerFn({ method: "GET" })
  .inputValidator(z.object({ limit: z.number().optional() }).parse)
  .handler(async ({ data }) => {
    const baseUrl = process.env.SCRAPER_BASE_URL?.replace(/\/+$/, "");
    const token = process.env.SCRAPER_API_TOKEN;
    if (!baseUrl || !token) return [];
    try {
      const params = new URLSearchParams({ active_only: "false" });
      if (data.limit) params.set("limit", String(data.limit));
      const res = await fetch(`${baseUrl}/api/jobs?${params}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) return [];
      const json = await res.json();
      return json.jobs ?? [];
    } catch {
      return [];
    }
  });

export const getJobDetails = createServerFn({ method: "GET" })
  .inputValidator(z.object({ id: z.coerce.string().min(1) }).parse)
  .handler(async ({ data }) => {
    const baseUrl = process.env.SCRAPER_BASE_URL?.replace(/\/+$/, "");
    const token = process.env.SCRAPER_API_TOKEN;
    if (!baseUrl || !token) return null;
    try {
      const res = await fetch(`${baseUrl}/api/jobs/${data.id}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) return null;
      return res.json();
    } catch {
      return null;
    }
  });

export const listLlmCacheEntries = createServerFn({ method: "GET" })
  .inputValidator(z.object({ limit: z.number().optional() }).parse)
  .handler(async ({ data }) => {
    const baseUrl = process.env.SCRAPER_BASE_URL?.replace(/\/+$/, "");
    const token = process.env.SCRAPER_API_TOKEN;
    if (!baseUrl || !token) return [];
    try {
      const params = new URLSearchParams();
      if (data.limit) params.set("limit", String(data.limit));
      const res = await fetch(`${baseUrl}/api/llm-cache/list?${params}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) return [];
      const json = await res.json();
      return json.items ?? [];
    } catch {
      return [];
    }
  });

export const deleteLlmCacheEntry = createServerFn({ method: "POST" })
  .inputValidator(z.object({ key: z.string().min(1) }).parse)
  .handler(async ({ data }) => {
    const baseUrl = process.env.SCRAPER_BASE_URL?.replace(/\/+$/, "");
    const token = process.env.SCRAPER_API_TOKEN;
    if (!baseUrl || !token) throw new Error("Backend not configured");
    const res = await fetch(`${baseUrl}/api/llm-cache/entry/${encodeURIComponent(data.key)}`, {
      method: "DELETE",
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return { ok: true };
  });

export const listHtmlCache = createServerFn({ method: "GET" })
  .inputValidator(z.object({ source: z.string().optional(), limit: z.number().optional() }).parse)
  .handler(async ({ data }) => {
    const baseUrl = process.env.SCRAPER_BASE_URL?.replace(/\/+$/, "");
    const token = process.env.SCRAPER_API_TOKEN;
    if (!baseUrl || !token) return [];
    try {
      const params = new URLSearchParams();
      if (data.source) params.set("source", data.source);
      if (data.limit) params.set("limit", String(data.limit));
      const res = await fetch(`${baseUrl}/api/html-cache?${params}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) return [];
      const json = await res.json();
      return json.items ?? [];
    } catch {
      return [];
    }
  });

export const fetchAuthHtml = createServerFn({ method: "POST" })
  .inputValidator(z.object({ path: z.string().min(1).max(500) }).parse)
  .handler(async ({ data }) => {
    const baseUrl = process.env.SCRAPER_BASE_URL?.replace(/\/+$/, "");
    const token = process.env.SCRAPER_API_TOKEN;
    if (!baseUrl || !token) throw new Error("Backend not configured");
    if (!data.path.startsWith("/api/llm-cache/entry/") && !data.path.startsWith("/api/html-cache/")) {
      throw new Error("Forbidden path");
    }
    const res = await fetch(`${baseUrl}${data.path}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.text();
  });

export const regenerateBundles = createServerFn({ method: "POST" })
  .inputValidator(z.object({
    recordId: z.number().int(),
    engine: z.enum(["template", "hybrid"]).optional().default("template"),
  }).parse)
  .handler(async ({ data }) => {
    const baseUrl = process.env.SCRAPER_BASE_URL?.replace(/\/+$/, "");
    const token = process.env.SCRAPER_API_TOKEN;
    if (!baseUrl || !token) throw new Error("Backend not configured");
    const res = await fetch(
      `${baseUrl}/api/records/${data.recordId}/regenerate-bundles?engine=${data.engine}`,
      { method: "POST", headers: { Authorization: `Bearer ${token}` } }
    );
    if (!res.ok) throw new Error(`Regen HTTP ${res.status}`);
    return res.json();
  });

// ---------- Parse client message ----------

export const parseClientMessage = createServerFn({ method: "POST" })
  .inputValidator(z.object({ message: z.string().min(1).max(5000) }).parse)
  .handler(async ({ data }) => {
    const baseUrl = process.env.SCRAPER_BASE_URL?.replace(/\/+$/, "");
    const token = process.env.SCRAPER_API_TOKEN;
    if (!baseUrl || !token) throw new Error("Backend not configured");

    const res = await fetch(`${baseUrl}/api/parse-client-message`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ message: data.message }),
    });

    if (!res.ok) {
      const errText = await res.text().catch(() => "");
      let detail: string = errText;
      try {
        const parsed = JSON.parse(errText);
        detail = typeof parsed?.detail === "string" ? parsed.detail : JSON.stringify(parsed);
      } catch {
        // keep raw text
      }
      return { ok: false as const, status: res.status, detail };
    }

    const body = (await res.json()) as {
      criteria?: any;
      criteria_list?: any[];
      count?: number;
      summary?: string;
      warnings?: string[];
    };
    const list: any[] = body.criteria_list ?? (body.criteria ? [body.criteria] : []);
    return {
      ok: true as const,
      criteria: body.criteria ?? list[0] ?? null,
      criteria_list: list,
      count: body.count ?? list.length,
      summary: body.summary ?? "",
      warnings: body.warnings ?? [],
    };
  });

// ---------- Model Normalizations ----------

export const getModelNormalizations = createServerFn({ method: "GET" }).handler(async () => {
  const baseUrl = process.env.SCRAPER_BASE_URL?.replace(/\/+$/, "");
  const token = process.env.SCRAPER_API_TOKEN;
  if (!baseUrl || !token) return { items: [] };
  try {
    const res = await fetch(`${baseUrl}/api/model-normalizations`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!res.ok) return { items: [] };
    return res.json() as Promise<{
      items: Array<{
        id: string | number;
        make: string;
        original_text: string;
        normalized_model: string;
        reason?: string;
        verified_count?: number;
      }>;
      stats?: {
        total: number;
        by_make: Record<string, number>;
      };
    }>;
  } catch {
    return { items: [] };
  }
});

export const deleteModelNormalization = createServerFn({ method: "POST" })
  .inputValidator(z.object({ id: z.coerce.string().min(1) }).parse)
  .handler(async ({ data }) => {
    const baseUrl = process.env.SCRAPER_BASE_URL?.replace(/\/+$/, "");
    const token = process.env.SCRAPER_API_TOKEN;
    if (!baseUrl || !token) throw new Error("Backend not configured");
    const res = await fetch(`${baseUrl}/api/model-normalizations/${data.id}`, {
      method: "DELETE",
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return { ok: true };
  });
