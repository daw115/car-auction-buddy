import { createFileRoute, Link } from "@tanstack/react-router";
import { useEffect, useState, useCallback } from "react";
import { useServerFn } from "@tanstack/react-start";
import { toast } from "sonner";
import {
  getPipelineFilters,
  updatePipelineFilters,
  type PipelineFilter,
} from "@/functions/pipeline-filters.functions";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
import { ArrowLeft, Loader2, RotateCcw, Filter, AlertCircle } from "lucide-react";

export const Route = createFileRoute("/settings/filters")({
  head: () => ({
    meta: [
      { title: "Filtry systemowe — pipeline scrapera" },
      { name: "robots", content: "noindex, nofollow" },
      {
        name: "description",
        content:
          "Globalne przełączniki filtrów pipeline scrapera: tylko insurance, wykluczenie kabrioletów.",
      },
    ],
  }),
  component: FiltersPage,
});

function FiltersPage() {
  const getFn = useServerFn(getPipelineFilters);
  const putFn = useServerFn(updatePipelineFilters);

  const [filters, setFilters] = useState<PipelineFilter[] | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [savingKey, setSavingKey] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await getFn();
      setFilters(res.filters ?? []);
      setNote(res.auction_window_note ?? null);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setError(msg);
      toast.error(`Nie udało się pobrać filtrów: ${msg}`);
    } finally {
      setLoading(false);
    }
  }, [getFn]);

  useEffect(() => {
    void load();
  }, [load]);

  const apply = async (key: string, value: boolean | null) => {
    setSavingKey(key);
    try {
      const res = await putFn({ data: { overrides: { [key]: value } } });
      setFilters((prev) => {
        if (!prev) return prev;
        return prev.map((f) => {
          if (f.key !== key) return f;
          const newOverride = res.overrides?.[key] ?? null;
          const effective = newOverride ?? f.env_value;
          return { ...f, override: newOverride, effective };
        });
      });
      toast.success(value === null ? "Przywrócono wartość domyślną." : "Zapisano.");
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      toast.error(`Nie zapisano: ${msg}`);
    } finally {
      setSavingKey(null);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-semibold">
            <Filter className="h-6 w-6" /> Filtry systemowe
          </h1>
          <p className="text-sm text-muted-foreground">
            Globalne przełączniki pipeline scrapera. Zmiana działa natychmiast, bez restartu.
          </p>
        </div>
        <Button variant="ghost" size="sm" asChild>
          <Link to="/settings">
            <ArrowLeft className="mr-1 h-4 w-4" /> Ustawienia
          </Link>
        </Button>
      </div>

      {loading && (
        <Card className="flex items-center gap-2 p-6 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" /> Ładuję…
        </Card>
      )}

      {error && !loading && (
        <Card className="flex items-start gap-2 border-destructive/40 bg-destructive/5 p-4 text-sm text-destructive">
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
          <div className="flex-1">
            <div className="font-medium">Błąd</div>
            <div className="text-xs opacity-90">{error}</div>
          </div>
          <Button size="sm" variant="outline" onClick={() => void load()}>Ponów</Button>
        </Card>
      )}

      {!loading && !error && filters && (
        <div className="space-y-3">
          {filters.length === 0 && (
            <Card className="p-6 text-sm text-muted-foreground">Brak filtrów zwróconych przez backend.</Card>
          )}
          {filters.map((f) => {
            const overridden = f.override !== null && f.override !== undefined;
            const saving = savingKey === f.key;
            const value = f.effective ?? f.env_value ?? false;
            return (
              <Card key={f.key} className="p-4">
                <div className="flex flex-wrap items-start gap-4">
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <div className="font-medium">{f.label}</div>
                      {overridden ? (
                        <Badge variant="secondary">nadpisane</Badge>
                      ) : (
                        <Badge variant="outline">domyślne z .env</Badge>
                      )}
                      <code className="rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
                        {f.key}
                      </code>
                    </div>
                    {f.description && (
                      <p className="mt-1 text-xs text-muted-foreground">{f.description}</p>
                    )}
                    <p className="mt-2 text-[11px] text-muted-foreground">
                      .env: <b>{String(f.env_value ?? "—")}</b> · efektywnie: <b>{String(f.effective ?? "—")}</b>
                    </p>
                  </div>
                  <div className="flex items-center gap-3">
                    <Switch
                      checked={!!value}
                      disabled={saving}
                      onCheckedChange={(v) => void apply(f.key, v)}
                    />
                    <Button
                      size="sm"
                      variant="ghost"
                      disabled={saving || !overridden}
                      onClick={() => void apply(f.key, null)}
                      title="Przywróć wartość domyślną z .env"
                    >
                      {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <RotateCcw className="h-4 w-4" />}
                    </Button>
                  </div>
                </div>
              </Card>
            );
          })}

          {note && (
            <Card className="border-muted-foreground/20 bg-muted/30 p-3 text-xs text-muted-foreground">
              {note}
            </Card>
          )}
        </div>
      )}
    </div>
  );
}
