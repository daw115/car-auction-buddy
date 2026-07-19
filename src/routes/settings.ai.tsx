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

  const [tasks, setTasks] = useState<AiProviderTask[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [savingKey, setSavingKey] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

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
