// Proxy do backendu FastAPI: /api/settings/ai-providers
// Transport wybierany przez src/server/backend-transport.server.ts
// (Ubuntu API za Cloudflare Access albo legacy API_BASE_URL — nigdy oba
// na raz i bez runtime fallbacku).
import { createServerFn } from "@tanstack/react-start";
import { z } from "zod";
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

async function call<T>(path: string, method: "GET" | "PUT", body?: unknown): Promise<T> {
  try {
    return await backendRequest<T>({ path, method, body });
  } catch (err) {
    const e = err as { status?: number; message?: string };
    throw new Error(e?.message ?? "Błąd backendu");
  }
}

export const getAiProviders = createServerFn({ method: "GET" }).handler(async () => {
  return call<AiProvidersResponse>("/api/settings/ai-providers", "GET");
});

export const updateAiProviders = createServerFn({ method: "POST" })
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
  .inputValidator(z.object({ provider: z.string().min(1) }).parse)
  .handler(async ({ data }) => {
    return call<AiModelsResponse>(
      `/api/settings/ai-models?provider=${encodeURIComponent(data.provider)}`,
      "GET",
    );
  });

export const updateAiModels = createServerFn({ method: "POST" })
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
