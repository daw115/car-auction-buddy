import { createFileRoute } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  updateAiProviders,
  updateAiModels,
  type AiProviderTask,
  type AiModelsResponse,
} from "@/functions/ai-providers.functions";
import { aiProvidersQuery, aiModelsQuery, settingsQueryKeys } from "@/queries/settings.queries";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Loader2, RotateCcw, Cpu, AlertCircle } from "lucide-react";

export const Route = createFileRoute("/settings/ai")({
  head: () => ({
    meta: [
      { title: "Ustawienia AI — dostawcy per zadanie" },
      { name: "robots", content: "noindex, nofollow" },
      {
        name: "description",
        content:
          "Wybierz dostawcę AI (OpenAI, Anthropic, Gemini, Kiro, local) osobno dla analizy lotów, raportów, normalizacji modeli i innych zadań.",
      },
    ],
  }),
  component: AiSettingsPage,
});

function AiSettingsPage() {
  const qc = useQueryClient();
  const providersQ = useQuery(aiProvidersQuery());
  const tasks = providersQ.data?.tasks ?? null;

  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});

  const providersMut = useMutation({
    mutationFn: (vars: { key: string; value: string | null }) =>
      updateAiProviders({ data: { overrides: { [vars.key]: vars.value } } }),
    onMutate: (vars) => {
      setFieldErrors((p) => {
        const { [vars.key]: _, ...rest } = p;
        return rest;
      });
    },
    onSuccess: (_res, vars) => {
      void qc.invalidateQueries({ queryKey: settingsQueryKeys.aiProviders });
      toast.success(
        vars.value === null
          ? "Przywrócono wartość domyślną z serwera"
          : `Ustawiono override: ${vars.value}`,
      );
    },
    onError: (e: unknown, vars) => {
      const msg = e instanceof Error ? e.message : String(e);
      setFieldErrors((p) => ({ ...p, [vars.key]: msg }));
    },
  });

  const kiroActive = useMemo(
    () => !!tasks?.some((t) => (t.override ?? t.env_value) === "kiro"),
    [tasks],
  );

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <PageHeader
        title="Ustawienia AI"
        description="Wybierz dostawcę AI osobno dla każdego zadania. Zmiany są zapisywane natychmiast."
        icon={<Cpu className="h-5 w-5" />}
        actions={<Badge variant="outline">AI per zadanie</Badge>}
      />

      {providersQ.isLoading ? (
        <Card className="p-6 flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" /> Ładowanie ustawień...
        </Card>
      ) : providersQ.isError ? (
        <Card className="p-6">
          <div className="flex items-start gap-2 text-sm text-destructive">
            <AlertCircle className="h-4 w-4 mt-0.5" />
            <div>
              <div className="font-medium">Błąd ładowania</div>
              <div className="text-xs text-muted-foreground mt-1">
                {providersQ.error instanceof Error
                  ? providersQ.error.message
                  : String(providersQ.error)}
              </div>
            </div>
          </div>
          <Button
            onClick={() => void providersQ.refetch()}
            variant="outline"
            size="sm"
            className="mt-4"
          >
            Spróbuj ponownie
          </Button>
        </Card>
      ) : tasks && tasks.length > 0 ? (
        <div className="space-y-3">
          <KiroModelSelector visible={kiroActive} />
          {tasks.map((task) => (
            <TaskRow
              key={task.key}
              task={task}
              saving={providersMut.isPending && providersMut.variables?.key === task.key}
              errorMsg={fieldErrors[task.key]}
              onChange={(v) => providersMut.mutate({ key: task.key, value: v })}
              onReset={() => providersMut.mutate({ key: task.key, value: null })}
            />
          ))}
        </div>
      ) : (
        <Card className="p-6 text-sm text-muted-foreground">
          Backend nie zwrócił żadnych zadań AI.
        </Card>
      )}
    </div>
  );
}

function TaskRow({
  task,
  saving,
  errorMsg,
  onChange,
  onReset,
}: {
  task: AiProviderTask;
  saving: boolean;
  errorMsg?: string;
  onChange: (v: string) => void;
  onReset: () => void;
}) {
  const isOverride = task.override !== null && task.override !== undefined;
  const currentValue = task.override ?? task.env_value ?? "";

  return (
    <Card className="p-4">
      <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <div className="font-medium text-sm">{task.label}</div>
            {isOverride ? (
              <Badge className="bg-warning/15 text-warning hover:bg-warning/20">nadpisane</Badge>
            ) : (
              <Badge variant="secondary">domyślne z serwera</Badge>
            )}
            {saving && <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />}
          </div>
          <div className="mt-1 text-xs text-muted-foreground">
            <code className="text-[11px]">{task.key}</code>
            {" · "}
            aktywne: <span className="font-medium text-foreground">{task.effective ?? "—"}</span>
            {isOverride && task.env_value && (
              <>
                {" "}
                {" · "} .env: <code className="text-[11px]">{task.env_value}</code>
              </>
            )}
          </div>
          {errorMsg && (
            <div className="mt-2 flex items-start gap-1.5 text-xs text-destructive">
              <AlertCircle className="h-3.5 w-3.5 mt-0.5 shrink-0" />
              <span>Nie zapisano: {errorMsg}</span>
            </div>
          )}
        </div>

        <div className="flex items-center gap-2 md:w-auto">
          <Select
            value={currentValue || undefined}
            onValueChange={(v) => onChange(v)}
            disabled={saving}
          >
            <SelectTrigger className="w-full md:w-[220px]">
              <SelectValue placeholder="Wybierz dostawcę" />
            </SelectTrigger>
            <SelectContent>
              {task.options.map((opt) => (
                <SelectItem key={opt} value={opt}>
                  {opt}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button
            variant="outline"
            size="icon"
            onClick={onReset}
            disabled={saving || !isOverride}
            title="Przywróć domyślne (z .env)"
          >
            <RotateCcw className="h-4 w-4" />
          </Button>
        </div>
      </div>
    </Card>
  );
}

function KiroModelSelector({ visible }: { visible: boolean }) {
  const qc = useQueryClient();
  const provider = "kiro";
  const q = useQuery(aiModelsQuery(provider));
  const data: AiModelsResponse | undefined = q.data;
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const mut = useMutation({
    mutationFn: (value: string | null) =>
      updateAiModels({ data: { overrides: { [provider]: value } } }),
    onMutate: () => setErrorMsg(null),
    onSuccess: (_res, value) => {
      void qc.invalidateQueries({ queryKey: settingsQueryKeys.aiModels(provider) });
      toast.success(value === null ? "Przywrócono domyślny model" : `Model: ${value}`);
    },
    onError: (e) => setErrorMsg(e instanceof Error ? e.message : String(e)),
  });

  const models = data?.models ?? [];
  const isOverride = data?.override != null;
  const current = data?.override ?? data?.env_value ?? "";
  const rateHint = useMemo(() => {
    const m = new Map<string, string>();
    for (const model of models) {
      const rm = model.rate_multiplier;
      if (rm == null) continue;
      const suffix = rm < 1 ? " — tańszy" : rm > 1 ? " — droższy" : "";
      m.set(
        model.model_id,
        `${rm.toFixed(2).replace(/\.?0+$/, "")}×${model.rate_unit ? ` ${model.rate_unit}` : ""}${suffix}`,
      );
    }
    return m;
  }, [models]);

  // Render nothing if kiro isn't the active provider AND user hasn't overridden a model
  if (!visible && !data?.override) return null;

  return (
    <Card className="p-4 border-primary/30 bg-primary/5">
      <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <div className="font-medium text-sm">Model Kiro</div>
            {isOverride ? (
              <Badge className="bg-warning/15 text-warning hover:bg-warning/20">nadpisane</Badge>
            ) : (
              <Badge variant="secondary">domyślne z serwera</Badge>
            )}
            {(q.isLoading || mut.isPending) && (
              <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />
            )}
          </div>
          <div className="mt-1 text-xs text-muted-foreground">
            Globalne dla wszystkich zadań używających{" "}
            <code className="text-[11px]">{provider}</code>
            {data?.effective && (
              <>
                {" "}
                · aktywne: <span className="font-medium text-foreground">{data.effective}</span>
              </>
            )}
            {isOverride && data?.env_value && (
              <>
                {" "}
                · .env: <code className="text-[11px]">{data.env_value}</code>
              </>
            )}
          </div>
          {q.isError && (
            <div className="mt-1 text-xs text-destructive">
              {q.error instanceof Error ? q.error.message : String(q.error)}
            </div>
          )}
          {errorMsg && (
            <div className="mt-2 flex items-start gap-1.5 text-xs text-destructive">
              <AlertCircle className="h-3.5 w-3.5 mt-0.5 shrink-0" />
              <span>Nie zapisano: {errorMsg}</span>
            </div>
          )}
        </div>

        <div className="flex items-center gap-2 md:w-auto">
          <Select
            value={current || undefined}
            onValueChange={(v) => mut.mutate(v)}
            disabled={q.isLoading || mut.isPending || models.length === 0}
          >
            <SelectTrigger className="w-full md:w-[320px]">
              <SelectValue placeholder={q.isLoading ? "Ładowanie..." : "Wybierz model"} />
            </SelectTrigger>
            <SelectContent>
              {models.map((m) => (
                <SelectItem key={m.model_id} value={m.model_id}>
                  <div className="flex flex-col">
                    <span className="text-sm">
                      {m.model_name}
                      {rateHint.get(m.model_id) && (
                        <span className="ml-2 text-[11px] text-muted-foreground">
                          {rateHint.get(m.model_id)}
                        </span>
                      )}
                    </span>
                    {m.description && (
                      <span className="text-[11px] text-muted-foreground">{m.description}</span>
                    )}
                  </div>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button
            variant="outline"
            size="icon"
            onClick={() => mut.mutate(null)}
            disabled={q.isLoading || mut.isPending || !isOverride}
            title="Przywróć domyślne (z .env)"
          >
            <RotateCcw className="h-4 w-4" />
          </Button>
        </div>
      </div>
    </Card>
  );
}
