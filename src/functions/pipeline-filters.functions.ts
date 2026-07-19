// Proxy do backendu FastAPI: /api/settings/pipeline-filters
import { createServerFn } from "@tanstack/react-start";
import { z } from "zod";

type Cfg = { baseUrl: string; token: string };
function cfg(): Cfg {
  const baseUrl = (process.env.API_BASE_URL ?? "").replace(/\/+$/, "");
  const token = process.env.API_BEARER_TOKEN ?? "";
  if (!baseUrl || !token) throw new Error("Backend nieskonfigurowany (API_BASE_URL / API_BEARER_TOKEN).");
  return { baseUrl, token };
}

export type PipelineFilter = {
  key: string;
  label: string;
  description?: string | null;
  env_value: boolean | null;
  override: boolean | null;
  effective: boolean | null;
};

export type PipelineFiltersResponse = {
  filters: PipelineFilter[];
  auction_window_note?: string | null;
};

async function call<T>(path: string, method: "GET" | "PUT", body?: unknown): Promise<T> {
  const { baseUrl, token } = cfg();
  const res = await fetch(`${baseUrl}${path}`, {
    method,
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: "application/json",
      ...(body != null ? { "Content-Type": "application/json" } : {}),
    },
    body: body != null ? JSON.stringify(body) : undefined,
  });
  const txt = await res.text();
  let parsed: unknown = txt;
  try { parsed = JSON.parse(txt); } catch { /* keep text */ }
  if (!res.ok) {
    const p = parsed as { detail?: unknown } | string;
    const msg =
      typeof p === "object" && p && "detail" in p && p.detail
        ? (typeof p.detail === "string" ? p.detail : JSON.stringify(p.detail))
        : `Backend ${res.status}`;
    throw new Error(msg);
  }
  return parsed as T;
}

export const getPipelineFilters = createServerFn({ method: "GET" }).handler(async () => {
  return call<PipelineFiltersResponse>("/api/settings/pipeline-filters", "GET");
});

export const updatePipelineFilters = createServerFn({ method: "POST" })
  .inputValidator(
    z.object({
      overrides: z.record(z.string(), z.union([z.boolean(), z.null()])),
    }).parse,
  )
  .handler(async ({ data }) => {
    return call<{ status: string; overrides: Record<string, boolean | null> }>(
      "/api/settings/pipeline-filters",
      "PUT",
      { overrides: data.overrides },
    );
  });
