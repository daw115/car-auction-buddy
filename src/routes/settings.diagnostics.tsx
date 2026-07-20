import { createFileRoute } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { AlertTriangle, CheckCircle2, RefreshCw, XCircle, Loader2, HelpCircle } from "lucide-react";
import { JsonDetails } from "@/components/JsonDetails";

type Check = {
  name: string;
  present: boolean;
  required: boolean;
  category: "auth" | "backend" | "ai" | "supabase" | "ubuntu";
  description: string;
  hint?: string;
  minLength?: number;
  lengthOk?: boolean;
  legacy?: boolean;
};

type Diagnostics = {
  ok: boolean;
  checkedAt: string;
  runtime: { nodeEnv: string };
  checks: Check[];
  summary: { total: number; ok: number; missingRequired: number };
};

type HealthStatus = "ok" | "down" | "unconfigured";
type UbuntuProbe = {
  status: HealthStatus;
  latencyMs?: number | null;
  requestId?: string | null;
};
type HealthResponse = {
  ok: boolean;
  checkedAt: string;
  durationMs: number;
  services: {
    database: HealthStatus;
    scraper: HealthStatus;
    ai: HealthStatus;
    ubuntuApi?: UbuntuProbe;
  };
};

type ConfigResponse = {
  config: Record<string, unknown> | null;
  env: Record<string, unknown>;
};

const CATEGORY_LABEL: Record<Check["category"], string> = {
  auth: "Autoryzacja / sesje",
  backend: "Backend / scraper",
  ai: "Providery AI",
  supabase: "Lovable Cloud (Supabase)",
  ubuntu: "Ubuntu API (migracja)",
};

const SERVICE_LABEL: Record<"database" | "scraper" | "ai", string> = {
  database: "Baza danych",
  scraper: "Backend / scraper (/health)",
  ai: "Provider AI",
};

const UBUNTU_ENV_NAMES = [
  "UBUNTU_API_BASE_URL",
  "UBUNTU_API_BEARER_TOKEN",
  "CF_ACCESS_CLIENT_ID",
  "CF_ACCESS_CLIENT_SECRET",
] as const;

export const Route = createFileRoute("/settings/diagnostics")({
  head: () => ({
    meta: [
      { title: "Diagnostyka — USA Car Finder" },
      { name: "description", content: "Sprawdzenie stanu backendu, konfiguracji i sekretów." },
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

  const healthQuery = useQuery<HealthResponse>({
    queryKey: ["diagnostics", "health"],
    queryFn: async () => {
      const res = await fetch("/api/health", { credentials: "include" });
      // 200 lub 503 — obie odpowiedzi zawierają body z detalami
      return (await res.json()) as HealthResponse;
    },
    refetchOnWindowFocus: false,
    refetchInterval: 60_000,
  });

  const configQuery = useQuery<ConfigResponse>({
    queryKey: ["diagnostics", "config"],
    queryFn: async () => {
      const res = await fetch("/api/config", { credentials: "include" });
      if (!res.ok) throw new Error(`HTTP ${res.status}: ${await res.text()}`);
      return res.json();
    },
    refetchOnWindowFocus: false,
  });

  const envOk = query.data?.ok ?? null;
  const healthOk = healthQuery.data?.ok ?? null;
  const configOk = configQuery.data ? !!configQuery.data.config : configQuery.error ? false : null;
  const readiness: "ready" | "degraded" | "loading" =
    envOk === null || healthOk === null || configOk === null
      ? "loading"
      : envOk && healthOk && configOk
        ? "ready"
        : "degraded";

  const refetchAll = () => {
    void query.refetch();
    void healthQuery.refetch();
    void configQuery.refetch();
  };

  const grouped = groupByCategory(query.data?.checks ?? []);
  const anyFetching = query.isFetching || healthQuery.isFetching || configQuery.isFetching;

  return (
    <div className="mx-auto max-w-4xl p-4 md:p-6 space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Diagnostyka środowiska</h1>
          <p className="text-sm text-muted-foreground">
            Stan backendu, konfiguracji aplikacji i sekretów runtime'u.
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={refetchAll} disabled={anyFetching}>
          <RefreshCw className={`h-4 w-4 mr-2 ${anyFetching ? "animate-spin" : ""}`} />
          Odśwież
        </Button>
      </div>

      <ReadinessBanner
        readiness={readiness}
        envOk={envOk}
        healthOk={healthOk}
        configOk={configOk}
      />

      <Card className="p-4 space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="font-semibold">Backend /health</h2>
          {healthQuery.data && (
            <span className="text-xs text-muted-foreground">
              {healthQuery.data.durationMs}ms ·{" "}
              {new Date(healthQuery.data.checkedAt).toLocaleTimeString("pl-PL")}
            </span>
          )}
        </div>
        {healthQuery.isLoading && (
          <p className="text-sm text-muted-foreground flex items-center gap-2">
            <Loader2 className="h-4 w-4 animate-spin" /> Sprawdzam…
          </p>
        )}
        {healthQuery.error && (
          <Alert variant="destructive">
            <AlertTriangle className="h-4 w-4" />
            <AlertDescription>{(healthQuery.error as Error).message}</AlertDescription>
          </Alert>
        )}
        {healthQuery.data && (
          <div className="space-y-2">
            {(["database", "scraper", "ai"] as const).map((k) => (
              <ServiceRow key={k} label={SERVICE_LABEL[k]} status={healthQuery.data!.services[k]} />
            ))}
          </div>
        )}
      </Card>

      <UbuntuApiCard
        probe={healthQuery.data?.services.ubuntuApi}
        envs={query.data?.checks.filter((c) => c.category === "ubuntu") ?? []}
        loading={healthQuery.isLoading || query.isLoading}
        healthError={healthQuery.error as Error | null}
        envError={query.error as Error | null}
      />

      <Card className="p-4 space-y-3">
        <h2 className="font-semibold">Konfiguracja /config</h2>
        {configQuery.isLoading && (
          <p className="text-sm text-muted-foreground flex items-center gap-2">
            <Loader2 className="h-4 w-4 animate-spin" /> Sprawdzam…
          </p>
        )}
        {configQuery.error && (
          <Alert variant="destructive">
            <AlertTriangle className="h-4 w-4" />
            <AlertDescription>{(configQuery.error as Error).message}</AlertDescription>
          </Alert>
        )}
        {configQuery.data && (
          <>
            <div className="flex items-center gap-2 text-sm">
              {configQuery.data.config ? (
                <>
                  <CheckCircle2 className="h-4 w-4 text-green-600" />
                  Rekord <code className="font-mono">app_config</code> odczytany z bazy.
                </>
              ) : (
                <>
                  <XCircle className="h-4 w-4 text-destructive" />
                  Brak rekordu <code className="font-mono">app_config</code>.
                </>
              )}
            </div>
            <details className="text-xs">
              <summary className="cursor-pointer text-muted-foreground hover:text-foreground">
                Pokaż surową odpowiedź
              </summary>
              <div className="mt-2">
                <JsonDetails data={configQuery.data} />
              </div>
            </details>
          </>
        )}
      </Card>

      {query.isLoading && <p className="text-sm text-muted-foreground">Sprawdzam zmienne…</p>}

      {query.error && (
        <Alert variant="destructive">
          <AlertTriangle className="h-4 w-4" />
          <AlertTitle>Nie udało się pobrać diagnostyki zmiennych</AlertTitle>
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
                {query.data.summary.ok}/{query.data.summary.total} zmiennych OK. Ostatnie
                sprawdzenie: {new Date(query.data.checkedAt).toLocaleString("pl-PL")}
              </AlertDescription>
            </Alert>
          ) : (
            <Alert variant="destructive">
              <XCircle className="h-4 w-4" />
              <AlertTitle>
                Brakuje {query.data.summary.missingRequired} wymaganych zmiennych środowiskowych
              </AlertTitle>
              <AlertDescription>
                Aplikacja może działać niestabilnie (np. „Błąd połączenia z serwerem" przy
                logowaniu). Uzupełnij sekrety w Lovable Cloud → Secrets.
              </AlertDescription>
            </Alert>
          )}

          {(Object.keys(grouped) as Check["category"][])
            .filter((c) => c !== "ubuntu")
            .map((cat) => (
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

function ReadinessBanner({
  readiness,
  envOk,
  healthOk,
  configOk,
}: {
  readiness: "ready" | "degraded" | "loading";
  envOk: boolean | null;
  healthOk: boolean | null;
  configOk: boolean | null;
}) {
  if (readiness === "loading") {
    return (
      <Alert>
        <HelpCircle className="h-4 w-4" />
        <AlertTitle className="flex items-center gap-2">
          <Loader2 className="h-4 w-4 animate-spin" /> Sprawdzam gotowość aplikacji…
        </AlertTitle>
      </Alert>
    );
  }
  if (readiness === "ready") {
    return (
      <Alert>
        <CheckCircle2 className="h-4 w-4 text-green-600" />
        <AlertTitle>Aplikacja gotowa do pracy</AlertTitle>
        <AlertDescription>Backend, konfiguracja i sekrety są w porządku.</AlertDescription>
      </Alert>
    );
  }
  return (
    <Alert variant="destructive">
      <XCircle className="h-4 w-4" />
      <AlertTitle>Aplikacja NIE jest w pełni gotowa</AlertTitle>
      <AlertDescription>
        <ul className="list-disc pl-5 mt-1 text-sm">
          <li>Sekrety / zmienne: {envOk ? "OK" : "problem"}</li>
          <li>Backend (/health): {healthOk ? "OK" : "problem"}</li>
          <li>Konfiguracja (/config): {configOk ? "OK" : "problem"}</li>
        </ul>
      </AlertDescription>
    </Alert>
  );
}

function ServiceRow({ label, status }: { label: string; status: HealthStatus }) {
  const icon =
    status === "ok" ? (
      <CheckCircle2 className="h-4 w-4 text-green-600" />
    ) : status === "down" ? (
      <XCircle className="h-4 w-4 text-destructive" />
    ) : (
      <AlertTriangle className="h-4 w-4 text-muted-foreground" />
    );
  const label2 = status === "ok" ? "OK" : status === "down" ? "Niedostępny" : "Nieskonfigurowany";
  return (
    <div className="flex items-center justify-between rounded-md border border-border px-3 py-2 text-sm">
      <span className="flex items-center gap-2">
        {icon} {label}
      </span>
      <Badge
        variant={status === "ok" ? "outline" : status === "down" ? "destructive" : "secondary"}
      >
        {label2}
      </Badge>
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
        {problem && check.hint && <p className="text-xs mt-1 text-destructive">💡 {check.hint}</p>}
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
    ubuntu: [],
  };
  for (const c of checks) out[c.category].push(c);
  return out;
}

type UbuntuConfigState = "complete" | "absent" | "partial";

function classifyUbuntuConfig(envs: Check[]): {
  state: UbuntuConfigState;
  presentCount: number;
  total: number;
} {
  const required = envs.filter((e) =>
    UBUNTU_ENV_NAMES.includes(e.name as (typeof UBUNTU_ENV_NAMES)[number]),
  );
  const total = UBUNTU_ENV_NAMES.length;
  const presentCount = required.filter((e) => e.present).length;
  if (presentCount === 0) return { state: "absent", presentCount, total };
  if (presentCount === total) return { state: "complete", presentCount, total };
  return { state: "partial", presentCount, total };
}

function UbuntuApiCard({
  probe,
  envs,
  loading,
  healthError,
  envError,
}: {
  probe?: UbuntuProbe;
  envs: Check[];
  loading: boolean;
  healthError: Error | null;
  envError: Error | null;
}) {
  const cfg = classifyUbuntuConfig(envs);
  const probeStatus = probe?.status ?? "unconfigured";

  return (
    <Card className="p-4 space-y-3">
      <div className="flex items-center justify-between gap-2">
        <h2 className="font-semibold">Ubuntu API</h2>
        <div className="flex items-center gap-2">
          {probe?.latencyMs != null && (
            <span className="text-xs text-muted-foreground">{probe.latencyMs}ms</span>
          )}
          <ProbeBadge status={probeStatus} />
        </div>
      </div>

      {loading && !probe && !envs.length && (
        <p className="text-sm text-muted-foreground flex items-center gap-2">
          <Loader2 className="h-4 w-4 animate-spin" /> Sprawdzam…
        </p>
      )}

      {healthError && (
        <Alert variant="destructive">
          <AlertTriangle className="h-4 w-4" />
          <AlertTitle>Błąd sieci lub sesji przy pobieraniu /api/health</AlertTitle>
          <AlertDescription>{healthError.message}</AlertDescription>
        </Alert>
      )}
      {envError && (
        <Alert variant="destructive">
          <AlertTriangle className="h-4 w-4" />
          <AlertTitle>Błąd sieci lub sesji przy pobieraniu /api/diagnostics</AlertTitle>
          <AlertDescription>{envError.message}</AlertDescription>
        </Alert>
      )}

      {cfg.state === "partial" && (
        <Alert variant="destructive">
          <XCircle className="h-4 w-4" />
          <AlertTitle>Konfiguracja niepełna — fail-closed</AlertTitle>
          <AlertDescription>
            Ustawionych {cfg.presentCount}/{cfg.total} zmiennych Ubuntu. Transport nie przełączy się
            na Ubuntu API dopóki wszystkie cztery zmienne nie są obecne. Uzupełnij brakujące lub
            usuń istniejące, aby przywrócić spójny stan.
          </AlertDescription>
        </Alert>
      )}
      {cfg.state === "absent" && (
        <Alert>
          <HelpCircle className="h-4 w-4" />
          <AlertTitle>Ubuntu API nieskonfigurowane</AlertTitle>
          <AlertDescription>
            Aplikacja używa legacy backendu (API_BASE_URL). To poprawny stan przed migracją.
          </AlertDescription>
        </Alert>
      )}
      {cfg.state === "complete" && probeStatus === "down" && (
        <Alert variant="destructive">
          <XCircle className="h-4 w-4" />
          <AlertTitle>Ubuntu API skonfigurowane, ale niedostępne</AlertTitle>
          <AlertDescription>
            Cloudflare Access odrzuca żądanie lub host nie odpowiada. Sprawdź service token i
            dostępność FastAPI.
          </AlertDescription>
        </Alert>
      )}
      {cfg.state === "complete" && probeStatus === "ok" && (
        <Alert>
          <CheckCircle2 className="h-4 w-4 text-green-600" />
          <AlertTitle>Ubuntu API dostępne</AlertTitle>
          <AlertDescription>Transport gotowy do routowania ruchu na Ubuntu.</AlertDescription>
        </Alert>
      )}

      {probe?.requestId && (
        <p className="text-xs text-muted-foreground">
          Request-Id ostatniego probe: <code className="font-mono">{probe.requestId}</code>
        </p>
      )}

      <div className="space-y-2">
        {envs.length === 0 && !loading && (
          <p className="text-xs text-muted-foreground">Brak danych o zmiennych.</p>
        )}
        {envs.map((c) => (
          <UbuntuEnvRow key={c.name} check={c} />
        ))}
      </div>
    </Card>
  );
}

function ProbeBadge({ status }: { status: HealthStatus }) {
  if (status === "ok") return <Badge variant="outline">ok</Badge>;
  if (status === "down") return <Badge variant="destructive">down</Badge>;
  return <Badge variant="secondary">unconfigured</Badge>;
}

function UbuntuEnvRow({ check }: { check: Check }) {
  return (
    <div className="flex items-center justify-between rounded-md border border-border px-3 py-2 text-sm">
      <div className="flex items-center gap-2 min-w-0">
        {check.present ? (
          <CheckCircle2 className="h-4 w-4 text-green-600 shrink-0" />
        ) : (
          <XCircle className="h-4 w-4 text-muted-foreground shrink-0" />
        )}
        <code className="font-mono truncate">{check.name}</code>
      </div>
      <div className="flex items-center gap-2 shrink-0">
        {check.required ? (
          <Badge variant="outline">wymagane</Badge>
        ) : (
          <Badge variant="secondary">opcjonalne</Badge>
        )}
        <Badge variant={check.present ? "outline" : "secondary"}>
          {check.present ? "present" : "absent"}
        </Badge>
        {check.present && check.minLength != null && (
          <Badge variant={check.lengthOk ? "outline" : "destructive"}>
            {check.lengthOk ? "lengthOk" : `min ${check.minLength}`}
          </Badge>
        )}
      </div>
    </div>
  );
}
