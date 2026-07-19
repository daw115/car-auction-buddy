import { queryOptions } from "@tanstack/react-query";
import {
  getAiProviders,
  getAiModels,
  type AiProvidersResponse,
  type AiModelsResponse,
} from "@/functions/ai-providers.functions";
import {
  getPipelineFilters,
  type PipelineFiltersResponse,
} from "@/functions/pipeline-filters.functions";

const STALE = 30_000;

export function aiProvidersQuery() {
  return queryOptions<AiProvidersResponse>({
    queryKey: ["settings", "ai-providers"],
    queryFn: () => getAiProviders(),
    staleTime: STALE,
  });
}

export function aiModelsQuery(provider: string) {
  return queryOptions<AiModelsResponse>({
    queryKey: ["settings", "ai-models", provider],
    queryFn: () => getAiModels({ data: { provider } }),
    staleTime: STALE,
    enabled: !!provider,
  });
}

export function pipelineFiltersQuery() {
  return queryOptions<PipelineFiltersResponse>({
    queryKey: ["settings", "pipeline-filters"],
    queryFn: () => getPipelineFilters(),
    staleTime: STALE,
  });
}

export const settingsQueryKeys = {
  aiProviders: ["settings", "ai-providers"] as const,
  aiModels: (provider: string) => ["settings", "ai-models", provider] as const,
  pipelineFilters: ["settings", "pipeline-filters"] as const,
};
