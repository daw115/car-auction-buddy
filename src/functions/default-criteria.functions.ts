// Proxy do backendu FastAPI: /api/settings/default-criteria
// Transport przez src/server/backend-transport.server.ts.
import { createServerFn } from "@tanstack/react-start";
import { z } from "zod";
import { assertAuctionSourcesAvailable } from "@/functions/backend.functions";
import { backendRequest } from "@/server/backend-transport.server";
import {
  auctionSourceSchema,
  normalizeAuctionSources,
  type AuctionSource,
} from "@/lib/auction-sources";

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
  try {
    return await backendRequest<T>({ path, method, body });
  } catch (err) {
    const e = err as { message?: string };
    throw new Error(e?.message ?? "Błąd backendu");
  }
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
