// Proxy do backendu FastAPI: /api/settings/default-criteria
import { createServerFn } from "@tanstack/react-start";
import { z } from "zod";

type Cfg = { baseUrl: string; token: string };
function cfg(): Cfg {
  const baseUrl = (process.env.API_BASE_URL ?? "").replace(/\/+$/, "");
  const token = process.env.API_BEARER_TOKEN ?? "";
  if (!baseUrl || !token) throw new Error("Backend nieskonfigurowany (API_BASE_URL / API_BEARER_TOKEN).");
  return { baseUrl, token };
}

export type DefaultCriteria = {
  make: string | null;
  model: string | null;
  year_from: number | null;
  year_to: number | null;
  budget_usd: number | null;
  max_odometer_mi: number | null;
  fuel_type: string | null;
  allowed_damage_types: string[];
  excluded_damage_types: string[];
  max_results: number;
  sources: string[];
};

export type DefaultCriteriaSaveResponse = {
  status: string;
  settings: DefaultCriteria;
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

const defaultCriteriaSchema = z.object({
  make: z.string().nullable().optional(),
  model: z.string().nullable().optional(),
  year_from: z.number().int().nullable().optional(),
  year_to: z.number().int().nullable().optional(),
  budget_usd: z.number().nullable().optional(),
  max_odometer_mi: z.number().nullable().optional(),
  fuel_type: z.string().nullable().optional(),
  allowed_damage_types: z.array(z.string()).optional(),
  excluded_damage_types: z.array(z.string()).optional(),
  max_results: z.number().int().positive().optional(),
  sources: z.array(z.string()).optional(),
});

export const getDefaultCriteria = createServerFn({ method: "GET" }).handler(async () => {
  return call<DefaultCriteria>("/api/settings/default-criteria", "GET");
});

export const updateDefaultCriteria = createServerFn({ method: "POST" })
  .inputValidator(defaultCriteriaSchema.parse)
  .handler(async ({ data }) => {
    // PUT nadpisuje w całości — caller odpowiada za wysłanie pełnego obiektu.
    return call<DefaultCriteriaSaveResponse>(
      "/api/settings/default-criteria",
      "PUT",
      data,
    );
  });
