import { createFileRoute } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { AlertTriangle, CheckCircle2, RefreshCw, XCircle } from "lucide-react";

type Check = {
  name: string;
  present: boolean;
  required: boolean;
  category: "auth" | "backend" | "ai" | "supabase";
  description: string;
  hint?: string;
  minLength?: number;
  lengthOk?: boolean;
};

type Diagnostics = {
  ok: boolean;
  checkedAt: string;
  runtime: { nodeEnv: string };
  checks: Check[];
  summary: { total: number; ok: number; missingRequired: number };
};

const CATEGORY_LABEL: Record<Check["category"], string> = {
  auth: "Autoryzacja / sesje",
  backend: "Backend / scraper",
  ai: "Providery AI",
  supabase: "Lovable Cloud (Supabase)",
};

export const Route = createFileRoute("/settings/diagnostics")({
  head: () => ({
    meta: [
      { title: "Diagnostyka — USA Car Finder" },
      { name: "description", content: "Sprawdzenie wymaganych zmiennych środowiskowych." },
    ],
  }),
  component: DiagnosticsPage,
});

function DiagnosticsPage() {
  const query = useQuery<Diagnostics>({
    queryKey: ["diagnostics", "env"],
    queryFn: async () => {
      const res = await fetch("/api/diagnostics", { credentials: "include" });
      if (!res.ok) throw new Error(`HTTP ${res.status}: ${await res.text()}`);
      return res.json();
    },
    refetchOnWindowFocus: false,
  });

  const grouped = groupByCategory(query.data?.checks ?? []);

  return (
    <div className="mx-auto max-w-4xl p-4 md:p-6 space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Diagnostyka środowiska</h1>
          <p className="text-sm text-muted-foreground">
            Weryfikacja wymaganych zmiennych i sekretów runtime'u.
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={() => query.refetch()}
          disabled={query.isFetching}
        >
          <RefreshCw className={`h-4 w-4 mr-2 ${query.isFetching ? "animate-spin" : ""}`} />
          Odśwież
        </Button>
      </div>

      {query.isLoading && <p className="text-sm text-muted-foreground">Sprawdzam…</p>}

      {query.error && (
        <Alert variant="destructive">
          <AlertTriangle className="h-4 w-4" />
          <AlertTitle>Nie udało się pobrać diagnostyki</AlertTitle>
          <AlertDescription>{(query.error as Error).message}</AlertDescription>
        </Alert>
      )}

      {query.data && (
        <>
          {query.data.ok ? (
            <Alert>
              <CheckCircle2 className="h-4 w-4 text-green-600" />
              <AlertTitle>Wszystkie wymagane zmienne są ustawione</AlertTitle>
              <AlertDescription>
                {query.data.summary.ok}/{query.data.summary.total} zmiennych OK. Ostatnie sprawdzenie:{" "}
                {new Date(query.data.checkedAt).toLocaleString("pl-PL")}
              </AlertDescription>
            </Alert>
          ) : (
            <Alert variant="destructive">
              <XCircle className="h-4 w-4" />
              <AlertTitle>
                Brakuje {query.data.summary.missingRequired} wymaganych zmiennych środowiskowych
              </AlertTitle>
              <AlertDescription>
                Aplikacja może działać niestabilnie (np. „Błąd połączenia z serwerem" przy logowaniu).
                Uzupełnij sekrety w Lovable Cloud → Secrets.
              </AlertDescription>
            </Alert>
          )}

          {(Object.keys(grouped) as Check["category"][]).map((cat) => (
            <Card key={cat} className="p-4 space-y-3">
              <h2 className="font-semibold">{CATEGORY_LABEL[cat]}</h2>
              <div className="space-y-2">
                {grouped[cat].map((c) => (
                  <CheckRow key={c.name} check={c} />
                ))}
              </div>
            </Card>
          ))}
        </>
      )}
    </div>
  );
}

function CheckRow({ check }: { check: Check }) {
  const ok = check.present && (check.lengthOk ?? true);
  const problem = check.required && !ok;

  return (
    <div
      className={`flex items-start gap-3 p-3 rounded-md border ${
        problem ? "border-destructive/40 bg-destructive/5" : "border-border"
      }`}
    >
      <div className="mt-0.5">
        {ok ? (
          <CheckCircle2 className="h-4 w-4 text-green-600" />
        ) : check.required ? (
          <XCircle className="h-4 w-4 text-destructive" />
        ) : (
          <AlertTriangle className="h-4 w-4 text-muted-foreground" />
        )}
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <code className="text-sm font-mono">{check.name}</code>
          {check.required ? (
            <Badge variant="outline">wymagane</Badge>
          ) : (
            <Badge variant="secondary">opcjonalne</Badge>
          )}
          {check.present && !check.lengthOk && (
            <Badge variant="destructive">za krótkie (min {check.minLength})</Badge>
          )}
        </div>
        <p className="text-xs text-muted-foreground mt-1">{check.description}</p>
        {problem && check.hint && (
          <p className="text-xs mt-1 text-destructive">💡 {check.hint}</p>
        )}
      </div>
    </div>
  );
}

function groupByCategory(checks: Check[]): Record<Check["category"], Check[]> {
  const out: Record<Check["category"], Check[]> = {
    auth: [],
    backend: [],
    ai: [],
    supabase: [],
  };
  for (const c of checks) out[c.category].push(c);
  return out;
}
