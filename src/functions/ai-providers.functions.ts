// Proxy do backendu FastAPI: /api/settings/ai-providers
// Transport wybierany przez wspólny server-only backend transport.
import { createServerFn, createServerOnlyFn } from "@tanstack/react-start";
import { z } from "zod";
import { siteSessionMiddleware } from "@/functions/site-session-middleware.functions";
import { backendRequest } from "@/server/backend-transport.server";

export type AiProviderTask = {
  key: string;
  label: string;
  options: string[];
  env_value: string | null;
  override: string | null;
  effective: string | null;
};

export type AiProvidersResponse = { tasks: AiProviderTask[] };

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

export const getAiProviders = createServerFn({ method: "GET" })
  .middleware([siteSessionMiddleware])
  .handler(async () => {
    return call<AiProvidersResponse>("/api/settings/ai-providers", "GET");
  });

export const updateAiProviders = createServerFn({ method: "POST" })
  .middleware([siteSessionMiddleware])
  .inputValidator(
    z.object({
      overrides: z.record(z.string(), z.union([z.string(), z.null()])),
    }).parse,
  )
  .handler(async ({ data }) => {
    return call<{ status: string; overrides: Record<string, string | null> }>(
      "/api/settings/ai-providers",
      "PUT",
      { overrides: data.overrides },
    );
  });

export type AiModelInfo = {
  model_name: string;
  description?: string | null;
  model_id: string;
  context_window_tokens?: number | null;
  rate_multiplier?: number | null;
  rate_unit?: string | null;
};

export type AiModelsResponse = {
  provider: string;
  models: AiModelInfo[];
  env_value: string | null;
  override: string | null;
  effective: string | null;
};

export const getAiModels = createServerFn({ method: "GET" })
  .middleware([siteSessionMiddleware])
  .inputValidator(z.object({ provider: z.string().min(1) }).parse)
  .handler(async ({ data }) => {
    return call<AiModelsResponse>(
      `/api/settings/ai-models?provider=${encodeURIComponent(data.provider)}`,
      "GET",
    );
  });

export const updateAiModels = createServerFn({ method: "POST" })
  .middleware([siteSessionMiddleware])
  .inputValidator(
    z.object({
      overrides: z.record(z.string(), z.union([z.string(), z.null()])),
    }).parse,
  )
  .handler(async ({ data }) => {
    return call<{ status: string; overrides: Record<string, string | null> }>(
      "/api/settings/ai-models",
      "PUT",
      { overrides: data.overrides },
    );
  });
