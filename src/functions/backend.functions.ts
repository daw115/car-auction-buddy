// Proxy do zewnętrznego backendu USA Car Finder (FastAPI).
// Wszystkie wywołania idą przez server function (Cloudflare Worker),
// żeby API_BEARER_TOKEN nie trafił nigdy do bundla klienta.
//
// Sekrety (Lovable Cloud):
//   API_BASE_URL       — np. https://moneybitches.organof.org
//   API_BEARER_TOKEN   — Bearer token dodawany do każdego requestu

import { createServerFn } from "@tanstack/react-start";
import { z } from "zod";
import type { CarLot, ClientCriteria, AnalyzedLot } from "@/lib/types";

// ---------- konfiguracja ----------

function getBackendConfig(): { baseUrl: string; token: string } {
  const baseUrl = (process.env.API_BASE_URL ?? "").replace(/\/+$/, "");
  const token = process.env.API_BEARER_TOKEN ?? "";
  if (!baseUrl || !token) {
    throw new Error(
      "Backend nieskonfigurowany — brak sekretów API_BASE_URL / API_BEARER_TOKEN.",
    );
  }
  return { baseUrl, token };
}

type BackendError = { status: number; message: string; body?: any };

function backendError(status: number, message: string, body?: any): BackendError {
  return { status, message, body };
}

// Wspólne wywołanie backendu. Timeout można podnieść dla długich operacji (search).
async function callBackend<T>(opts: {
  path: string;
  method?: "GET" | "POST" | "PUT" | "DELETE" | "PATCH";
  body?: any;
  timeoutMs?: number;
  responseType?: "json" | "text";
}): Promise<T> {
  const { baseUrl, token } = getBackendConfig();
  const method = opts.method ?? "GET";
  const timeoutMs = opts.timeoutMs ?? 30_000;
  const responseType = opts.responseType ?? "json";

  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(`${baseUrl}${opts.path}`, {
      method,
      headers: {
        Authorization: `Bearer ${token}`,
        Accept: responseType === "json" ? "application/json" : "text/html, */*",
        ...(opts.body != null ? { "Content-Type": "application/json" } : {}),
      },
      body: opts.body != null ? JSON.stringify(opts.body) : undefined,
      signal: ctrl.signal,
    });

    const rawText = await res.text();
    let parsed: any = rawText;
    if (responseType === "json" && rawText) {
      try {
        parsed = JSON.parse(rawText);
      } catch {
        // zostaw jako tekst — backend czasem zwróci HTML błąd
      }
    }

    if (!res.ok) {
      let msg: string;
      if (res.status === 401 || res.status === 403) {
        msg = "Błąd konfiguracji — skontaktuj się z administratorem.";
      } else if (res.status === 404) {
        msg = "Brak wyników — sprawdź kryteria.";
      } else if (res.status >= 500) {
        msg = "Błąd scrapera / backendu, spróbuj ponownie za chwilę.";
      } else {
        msg = `Backend ${res.status}`;
      }
      throw backendError(res.status, msg, parsed);
    }

    return parsed as T;
  } catch (err) {
    if (err && typeof err === "object" && "status" in err) throw err;
    if ((err as Error).name === "AbortError") {
      throw backendError(408, "Przekroczono limit czasu — spróbuj ponownie.");
    }
    throw backendError(0, (err as Error).message || "Błąd połączenia z backendem.");
  } finally {
    clearTimeout(timer);
  }
}

// ---------- typy odpowiedzi backendu ----------

export type BackendSearchResponse = {
  listings: CarLot[];
  source: "mock" | "live";
  job_id: string;
  criteria: ClientCriteria;
  vin_coverage?: any;
  analysis_notice?: string | null;
};

export type BackendJobStatus = {
  job_id: string;
  status: string;
  progress?: number;
  phase?: string;
  phases?: any[];
  step?: string;
  message?: string;
  current?: number;
  total?: number;
  listings?: CarLot[];
  analyzed_lots?: AnalyzedLot[];
  report_endpoints?: Record<string, string>;
  client_reports_html?: string[];
  broker_reports_html?: string[];
};

export type BackendRecordSummary = {
  id: string;
  created_at?: string;
  status?: string;
  client_name?: string | null;
  make?: string | null;
  model?: string | null;
  listings_count?: number;
  [k: string]: any;
};

// ---------- serwer functions wołane z UI ----------

const criteriaShape = z.object({
  make: z.string().min(1).max(80),
  model: z.string().max(80).optional().nullable(),
  year_from: z.number().int().min(1900).max(2100).optional().nullable(),
  year_to: z.number().int().min(1900).max(2100).optional().nullable(),
  budget_usd: z.number().min(0).max(1_000_000).optional().nullable(),
  max_odometer_mi: z.number().int().min(0).max(1_000_000).optional().nullable(),
  fuel_type: z.enum(["Gas", "Hybrid", "Diesel", "Electric"]).optional().nullable(),
  allowed_damage_types: z.array(z.string().max(40)).max(40).optional(),
  excluded_damage_types: z.array(z.string().max(40)).max(40).optional(),
  max_results: z.number().int().min(1).max(15).optional(),
  sources: z.array(z.enum(["copart", "iaai"])).min(1).max(2).optional(),
});

/**
 * POST /api/search — synchroniczne wywołanie (do kilku minut).
 * UI musi trzymać loader i NIE zakładać timeoutu.
 */
export const backendSearch = createServerFn({ method: "POST" })
  .inputValidator(
    z
      .object({
        criteria: criteriaShape,
        demo: z.boolean().optional(),
      })
      .parse,
  )
  .handler(async ({ data }) => {
    return callBackend<BackendSearchResponse>({
      path: "/api/search",
      method: "POST",
      body: data,
      timeoutMs: 5 * 60 * 1000, // 5 minut — realny scraping + analiza AI
    });
  });

/** GET /api/jobs/{job_id} — polling statusu długiego joba. */
export const backendJobStatus = createServerFn({ method: "GET" })
  .inputValidator(z.object({ jobId: z.string().min(1).max(200) }).parse)
  .handler(async ({ data }) => {
    return callBackend<BackendJobStatus>({
      path: `/api/jobs/${encodeURIComponent(data.jobId)}`,
      method: "GET",
      timeoutMs: 30_000,
    });
  });

/** GET /api/records — lista historii wyszukiwań. */
export const backendListRecords = createServerFn({ method: "GET" }).handler(async () => {
  return callBackend<BackendRecordSummary[] | { records: BackendRecordSummary[] }>({
    path: "/api/records",
    method: "GET",
  });
});

/** GET /api/records/{id} — szczegóły rekordu. */
export const backendGetRecord = createServerFn({ method: "GET" })
  .inputValidator(z.object({ id: z.string().min(1).max(200) }).parse)
  .handler(async ({ data }) => {
    return callBackend<Record<string, any>>({
      path: `/api/records/${encodeURIComponent(data.id)}`,
      method: "GET",
    });
  });

/** GET /api/records/{id}/feedback — odczyt feedbacku brokera. */
export const backendGetFeedback = createServerFn({ method: "GET" })
  .inputValidator(z.object({ id: z.string().min(1).max(200) }).parse)
  .handler(async ({ data }) => {
    return callBackend<Record<string, any>>({
      path: `/api/records/${encodeURIComponent(data.id)}/feedback`,
      method: "GET",
    });
  });

/** POST /api/records/{id}/feedback — zapis feedbacku brokera. */
export const backendSaveFeedback = createServerFn({ method: "POST" })
  .inputValidator(
    z
      .object({
        id: z.string().min(1).max(200),
        feedback: z.record(z.string(), z.any()),
      })
      .parse,
  )
  .handler(async ({ data }) => {
    return callBackend<Record<string, any>>({
      path: `/api/records/${encodeURIComponent(data.id)}/feedback`,
      method: "POST",
      body: data.feedback,
    });
  });

const reportModeSchema = z.enum([
  "client-html",
  "broker-html",
  "client-llm",
  "broker-llm",
  "offer-email-html",
  "pdf",
]);

/**
 * POST na jeden z endpointów raportu.
 * Zwraca surowy HTML (albo tekst) — UI otwiera w nowej karcie / pobiera.
 */
export const backendGenerateReport = createServerFn({ method: "POST" })
  .inputValidator(
    z
      .object({
        mode: reportModeSchema,
        approved_lots: z.array(z.any()).min(1),
        criteria: criteriaShape.optional(),
        client_name: z.string().max(200).optional(),
        client_email: z.string().max(200).optional(),
        tracking_url: z.string().max(500).optional(),
      })
      .parse,
  )
  .handler(async ({ data }) => {
    const pathMap: Record<z.infer<typeof reportModeSchema>, string> = {
      "client-html": "/report/client-html",
      "broker-html": "/report/broker-html",
      "client-llm": "/report/client-llm",
      "broker-llm": "/report/broker-llm",
      "offer-email-html": "/report/offer-email-html",
      pdf: "/report",
    };
    const { mode, ...body } = data;
    const html = await callBackend<string>({
      path: pathMap[mode],
      method: "POST",
      body,
      timeoutMs: 3 * 60 * 1000,
      responseType: "text",
    });
    return { mode, html };
  });

// ---------- diagnostyka / health ----------

export const backendHealth = createServerFn({ method: "GET" }).handler(async () => {
  try {
    const [telegram, cache, db] = await Promise.allSettled([
      callBackend<any>({ path: "/api/telegram/status", timeoutMs: 8_000 }),
      callBackend<any>({ path: "/api/llm-cache/stats", timeoutMs: 8_000 }),
      callBackend<any>({ path: "/api/db/overview", timeoutMs: 8_000 }),
    ]);
    return {
      configured: true,
      telegram: telegram.status === "fulfilled" ? telegram.value : { error: true },
      llm_cache: cache.status === "fulfilled" ? cache.value : { error: true },
      db: db.status === "fulfilled" ? db.value : { error: true },
    };
  } catch (e) {
    return { configured: false, error: (e as { message?: string })?.message ?? "any" };
  }
});
