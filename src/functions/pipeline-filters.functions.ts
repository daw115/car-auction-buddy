// Proxy do backendu FastAPI: /api/settings/pipeline-filters
// Transport wybierany przez wspólny server-only backend transport.
import { createServerFn, createServerOnlyFn } from "@tanstack/react-start";
import { z } from "zod";
import { siteSessionMiddleware } from "@/functions/site-session-middleware.functions";
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

const call = createServerOnlyFn(async function call<T>(
  path: string,
  method: "GET" | "PUT",
  body?: unknown,
): Promise<T> {
  try {
    return await backendRequest<T>({ path, method, body });
  } catch (error) {
    const message = (error as { message?: unknown } | undefined)?.message;
    throw new Error(typeof message === "string" ? message : "Błąd backendu");
  }
});

export const getPipelineFilters = createServerFn({ method: "GET" })
  .middleware([siteSessionMiddleware])
  .handler(async () => {
    return call<PipelineFiltersResponse>("/api/settings/pipeline-filters", "GET");
  });

export const updatePipelineFilters = createServerFn({ method: "POST" })
  .middleware([siteSessionMiddleware])
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
