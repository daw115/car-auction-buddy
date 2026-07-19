import { createFileRoute, Link } from "@tanstack/react-router";
import { useEffect, useState, useCallback, useMemo } from "react";
import { useServerFn } from "@tanstack/react-start";
import { toast } from "sonner";
import {
  getAiProviders,
  updateAiProviders,
  getAiModels,
  updateAiModels,
  type AiProviderTask,
  type AiModelsResponse,
} from "@/functions/ai-providers.functions";
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
import { ArrowLeft, Loader2, RotateCcw, Cpu, AlertCircle } from "lucide-react";

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
  const getFn = useServerFn(getAiProviders);
  const putFn = useServerFn(updateAiProviders);
  const getModelsFn = useServerFn(getAiModels);

  const [tasks, setTasks] = useState<AiProviderTask[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [savingKey, setSavingKey] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [kiroModels, setKiroModels] = useState<AiModelsResponse | null>(null);
  const [kiroModelsLoading, setKiroModelsLoading] = useState(true);
  const [kiroModelsError, setKiroModelsError] = useState<string | null>(null);

  const loadKiroModels = useCallback(async () => {
    setKiroModelsLoading(true);
    setKiroModelsError(null);
    try {
      const res = await getModelsFn({ data: { provider: "kiro" } });
      setKiroModels(res);
    } catch (e) {
      setKiroModelsError(e instanceof Error ? e.message : String(e));
    } finally {
      setKiroModelsLoading(false);
    }
  }, [getModelsFn]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await getFn();
      setTasks(res.tasks ?? []);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setError(msg);
      toast.error(`Nie udało się pobrać ustawień: ${msg}`);
    } finally {
      setLoading(false);
    }
  }, [getFn]);

  useEffect(() => {
    void load();
  }, [load]);

  const applyOverride = async (key: string, value: string | null) => {
    setSavingKey(key);
    try {
      const res = await putFn({ data: { overrides: { [key]: value } } });
      // Aktualizuj lokalny stan na podstawie zwróconego stanu overrides
      setTasks((prev) => {
        if (!prev) return prev;
        return prev.map((t) => {
          if (t.key !== key) return t;
          const newOverride = res.overrides?.[key] ?? null;
          const effective = newOverride ?? t.env_value ?? t.effective;
          return { ...t, override: newOverride, effective };
        });
      });
      toast.success(
        value === null
          ? "Przywrócono wartość domyślną z serwera"
          : `Ustawiono override: ${value}`,
      );
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      toast.error(`Zapis nie powiódł się: ${msg}`);
    } finally {
      setSavingKey(null);
    }
  };

  return (
    <div className="min-h-screen bg-background">
      <div className="mx-auto max-w-4xl px-6 py-10">
        <div className="mb-6 flex items-center justify-between">
          <Link
            to="/settings"
            className="inline-flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground"
          >
            <ArrowLeft className="h-4 w-4" /> Wróć do ustawień
          </Link>
          <Badge variant="outline" className="gap-1">
            <Cpu className="h-3 w-3" /> AI per zadanie
          </Badge>
        </div>

        <h1 className="mb-2 text-3xl font-bold tracking-tight">Ustawienia AI</h1>
        <p className="mb-6 text-sm text-muted-foreground">
          Wybór dostawcy AI osobno dla każdego zadania. Zmiana zapisywana natychmiast.
          „Domyślne z serwera" oznacza wartość z pliku <code>.env</code> backendu.
        </p>

        {loading ? (
          <Card className="p-6 flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" /> Ładowanie ustawień...
          </Card>
        ) : error ? (
          <Card className="p-6">
            <div className="flex items-start gap-2 text-sm text-destructive">
              <AlertCircle className="h-4 w-4 mt-0.5" />
              <div>
                <div className="font-medium">Błąd ładowania</div>
                <div className="text-xs text-muted-foreground mt-1">{error}</div>
              </div>
            </div>
            <Button onClick={() => void load()} variant="outline" size="sm" className="mt-4">
              Spróbuj ponownie
            </Button>
          </Card>
        ) : tasks && tasks.length > 0 ? (
          <div className="space-y-3">
            {tasks.some((t) => (t.override ?? t.env_value) === "kiro") && (
              <ProviderModelSelector provider="kiro" label="Model Kiro" />
            )}
            {tasks.map((task) => (
              <TaskRow
                key={task.key}
                task={task}
                saving={savingKey === task.key}
                onChange={(v) => void applyOverride(task.key, v)}
                onReset={() => void applyOverride(task.key, null)}
              />
            ))}
          </div>

        ) : (
          <Card className="p-6 text-sm text-muted-foreground">
            Backend nie zwrócił żadnych zadań AI.
          </Card>
        )}
      </div>
    </div>
  );
}

function TaskRow({
  task,
  saving,
  onChange,
  onReset,
}: {
  task: AiProviderTask;
  saving: boolean;
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
              <Badge className="bg-amber-500/15 text-amber-700 hover:bg-amber-500/20 dark:text-amber-400">
                nadpisane
              </Badge>
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
              <> {" · "} .env: <code className="text-[11px]">{task.env_value}</code></>
            )}
          </div>
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

function ProviderModelSelector({ provider, label }: { provider: string; label: string }) {
  const getFn = useServerFn(getAiModels);
  const putFn = useServerFn(updateAiModels);
  const [data, setData] = useState<AiModelsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setErr(null);
    try {
      const res = await getFn({ data: { provider } });
      setData(res);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [getFn, provider]);

  useEffect(() => { void load(); }, [load]);

  const apply = async (value: string | null) => {
    setSaving(true);
    try {
      const res = await putFn({ data: { overrides: { [provider]: value } } });
      const newOverride = res.overrides?.[provider] ?? null;
      setData((prev) => prev ? {
        ...prev,
        override: newOverride,
        effective: newOverride ?? prev.env_value ?? prev.effective,
      } : prev);
      toast.success(value === null ? "Przywrócono domyślny model" : `Model: ${value}`);
    } catch (e) {
      toast.error(`Zapis nie powiódł się: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setSaving(false);
    }
  };

  const models = data?.models ?? [];
  const isOverride = data?.override != null;
  const current = data?.override ?? data?.env_value ?? "";
  const rateHint = useMemo(() => {
    const m = new Map<string, string>();
    for (const model of models) {
      const rm = model.rate_multiplier;
      if (rm == null) continue;
      const suffix = rm < 1 ? " — tańszy" : rm > 1 ? " — droższy" : "";
      m.set(model.model_id, `${rm.toFixed(2).replace(/\.?0+$/, "")}×${model.rate_unit ? ` ${model.rate_unit}` : ""}${suffix}`);
    }
    return m;
  }, [models]);

  return (
    <Card className="p-4 border-primary/30 bg-primary/5">
      <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <div className="font-medium text-sm">{label}</div>
            {isOverride ? (
              <Badge className="bg-amber-500/15 text-amber-700 hover:bg-amber-500/20 dark:text-amber-400">
                nadpisane
              </Badge>
            ) : (
              <Badge variant="secondary">domyślne z serwera</Badge>
            )}
            {(loading || saving) && <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />}
          </div>
          <div className="mt-1 text-xs text-muted-foreground">
            Globalne dla wszystkich zadań używających <code className="text-[11px]">{provider}</code>
            {data?.effective && <> · aktywne: <span className="font-medium text-foreground">{data.effective}</span></>}
            {isOverride && data?.env_value && <> · .env: <code className="text-[11px]">{data.env_value}</code></>}
          </div>
          {err && <div className="mt-1 text-xs text-destructive">{err}</div>}
        </div>

        <div className="flex items-center gap-2 md:w-auto">
          <Select
            value={current || undefined}
            onValueChange={(v) => void apply(v)}
            disabled={loading || saving || models.length === 0}
          >
            <SelectTrigger className="w-full md:w-[320px]">
              <SelectValue placeholder={loading ? "Ładowanie..." : "Wybierz model"} />
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
            onClick={() => void apply(null)}
            disabled={loading || saving || !isOverride}
            title="Przywróć domyślne (z .env)"
          >
            <RotateCcw className="h-4 w-4" />
          </Button>
        </div>
      </div>
    </Card>
  );
}

