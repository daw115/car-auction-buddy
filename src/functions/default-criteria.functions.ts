// Proxy do backendu FastAPI: /api/settings/default-criteria
import { createServerFn } from "@tanstack/react-start";
import { z } from "zod";
import { assertAuctionSourcesAvailable } from "@/functions/backend.functions";
import {
  auctionSourceSchema,
  normalizeAuctionSources,
  type AuctionSource,
} from "@/lib/auction-sources";

type Cfg = { baseUrl: string; token: string };
function cfg(): Cfg {
  const baseUrl = (process.env.API_BASE_URL ?? "").replace(/\/+$/, "");
  const token = process.env.API_BEARER_TOKEN ?? "";
  if (!baseUrl || !token)
    throw new Error("Backend nieskonfigurowany (API_BASE_URL / API_BEARER_TOKEN).");
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
  sources: AuctionSource[];
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
  try {
    parsed = JSON.parse(txt);
  } catch {
    /* keep text */
  }
  if (!res.ok) {
    const p = parsed as { detail?: unknown } | string;
    const msg =
      typeof p === "object" && p && "detail" in p && p.detail
        ? typeof p.detail === "string"
          ? p.detail
          : JSON.stringify(p.detail)
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
  sources: z.array(auctionSourceSchema).min(1).max(3).optional(),
});

export const getDefaultCriteria = createServerFn({ method: "GET" }).handler(async () => {
  const raw = await call<unknown>("/api/settings/default-criteria", "GET");
  const parsed = defaultCriteriaSchema.parse(raw);
  return {
    make: parsed.make ?? null,
    model: parsed.model ?? null,
    year_from: parsed.year_from ?? null,
    year_to: parsed.year_to ?? null,
    budget_usd: parsed.budget_usd ?? null,
    max_odometer_mi: parsed.max_odometer_mi ?? null,
    fuel_type: parsed.fuel_type ?? null,
    allowed_damage_types: parsed.allowed_damage_types ?? [],
    excluded_damage_types: parsed.excluded_damage_types ?? [],
    max_results: parsed.max_results ?? 15,
    sources: normalizeAuctionSources(parsed.sources),
  } satisfies DefaultCriteria;
});

export const updateDefaultCriteria = createServerFn({ method: "POST" })
  .inputValidator(defaultCriteriaSchema.parse)
  .handler(async ({ data }) => {
    await assertAuctionSourcesAvailable(data.sources);
    // PUT nadpisuje w całości — caller odpowiada za wysłanie pełnego obiektu.
    return call<DefaultCriteriaSaveResponse>("/api/settings/default-criteria", "PUT", data);
  });
