// Proxy do backendu FastAPI: /api/settings/ai-providers
import { createServerFn } from "@tanstack/react-start";
import { z } from "zod";

type Cfg = { baseUrl: string; token: string };
function cfg(): Cfg {
  const baseUrl = (process.env.API_BASE_URL ?? "").replace(/\/+$/, "");
  const token = process.env.API_BEARER_TOKEN ?? "";
  if (!baseUrl || !token) throw new Error("Backend nieskonfigurowany (API_BASE_URL / API_BEARER_TOKEN).");
  return { baseUrl, token };
}

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
  let parsed: any = txt;
  try { parsed = JSON.parse(txt); } catch { /* keep text */ }
  if (!res.ok) {
    const msg = typeof parsed === "object" && parsed?.detail
      ? (typeof parsed.detail === "string" ? parsed.detail : JSON.stringify(parsed.detail))
      : `Backend ${res.status}`;
    throw new Error(msg);
  }
  return parsed as T;
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
