import { createFileRoute, Link } from "@tanstack/react-router";
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { updatePipelineFilters } from "@/functions/pipeline-filters.functions";
import { pipelineFiltersQuery, settingsQueryKeys } from "@/queries/settings.queries";
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
  const qc = useQueryClient();
  const q = useQuery(pipelineFiltersQuery());
  const filters = q.data?.filters ?? null;
  const note = q.data?.auction_window_note ?? null;

  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});

  const mut = useMutation({
    mutationFn: (vars: { key: string; value: boolean | null }) =>
      updatePipelineFilters({ data: { overrides: { [vars.key]: vars.value } } }),
    onMutate: (vars) => {
      setFieldErrors((p) => {
        const { [vars.key]: _, ...rest } = p;
        return rest;
      });
    },
    onSuccess: (_res, vars) => {
      void qc.invalidateQueries({ queryKey: settingsQueryKeys.pipelineFilters });
      toast.success(vars.value === null ? "Przywrócono wartość domyślną." : "Zapisano.");
    },
    onError: (e: unknown, vars) => {
      const msg = e instanceof Error ? e.message : String(e);
      setFieldErrors((p) => ({ ...p, [vars.key]: msg }));
    },
  });

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

      {q.isLoading && (
        <Card className="flex items-center gap-2 p-6 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" /> Ładuję…
        </Card>
      )}

      {q.isError && (
        <Card className="flex items-start gap-2 border-destructive/40 bg-destructive/5 p-4 text-sm text-destructive">
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
          <div className="flex-1">
            <div className="font-medium">Błąd</div>
            <div className="text-xs opacity-90">
              {q.error instanceof Error ? q.error.message : String(q.error)}
            </div>
          </div>
          <Button size="sm" variant="outline" onClick={() => void q.refetch()}>Ponów</Button>
        </Card>
      )}

      {!q.isLoading && !q.isError && filters && (
        <div className="space-y-3">
          {filters.length === 0 && (
            <Card className="p-6 text-sm text-muted-foreground">
              Brak filtrów zwróconych przez backend.
            </Card>
          )}
          {filters.map((f) => {
            const overridden = f.override !== null && f.override !== undefined;
            const saving = mut.isPending && mut.variables?.key === f.key;
            const value = f.effective ?? f.env_value ?? false;
            const errorMsg = fieldErrors[f.key];
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
                      .env: <b>{String(f.env_value ?? "—")}</b> · efektywnie:{" "}
                      <b>{String(f.effective ?? "—")}</b>
                    </p>
                    {errorMsg && (
                      <div className="mt-2 flex items-start gap-1.5 text-xs text-destructive">
                        <AlertCircle className="h-3.5 w-3.5 mt-0.5 shrink-0" />
                        <span>Nie zapisano: {errorMsg}</span>
                      </div>
                    )}
                  </div>
                  <div className="flex items-center gap-3">
                    <Switch
                      checked={!!value}
                      disabled={saving}
                      onCheckedChange={(v) => mut.mutate({ key: f.key, value: v })}
                    />
                    <Button
                      size="sm"
                      variant="ghost"
                      disabled={saving || !overridden}
                      onClick={() => mut.mutate({ key: f.key, value: null })}
                      title="Przywróć wartość domyślną z .env"
                    >
                      {saving ? (
                        <Loader2 className="h-4 w-4 animate-spin" />
                      ) : (
                        <RotateCcw className="h-4 w-4" />
                      )}
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
