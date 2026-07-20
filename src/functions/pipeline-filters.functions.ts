// Proxy do backendu FastAPI: /api/settings/pipeline-filters
// Transport przez src/server/backend-transport.server.ts.
import { createServerFn } from "@tanstack/react-start";
import { z } from "zod";
import { backendRequest } from "@/server/backend-transport.server";

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
  try {
    return await backendRequest<T>({ path, method, body });
  } catch (err) {
    const e = err as { message?: string };
    throw new Error(e?.message ?? "Błąd backendu");
  }
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
