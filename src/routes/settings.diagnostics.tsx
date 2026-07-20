import { useQuery } from "@tanstack/react-query";
import { createFileRoute, Link } from "@tanstack/react-router";
import {
  AlertTriangle,
  CheckCircle2,
  Database,
  HelpCircle,
  Loader2,
  RefreshCw,
  ScrollText,
  Stethoscope,
  XCircle,
} from "lucide-react";

import { PageHeader } from "@/components/page-header";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";

type HealthStatus = "ok" | "down" | "unconfigured";

type UbuntuProbe = {
  status: HealthStatus;
  latencyMs: number | null;
  requestId: string;
};

type HealthResponse = {
  services: {
    ubuntuApi: UbuntuProbe;
  };
};

type UbuntuCheck = {
  name: string;
  present: boolean;
  required: boolean;
  category: "ubuntu";
  minLength?: number;
  lengthOk?: boolean;
};

type DiagnosticsResponse = {
  checks: Array<UbuntuCheck | { category: string }>;
};

type UbuntuConfigState = "complete" | "absent" | "partial";

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
      {
        name: "description",
        content: "Bezpieczne punkty diagnostyczne aplikacji dla zalogowanego operatora.",
      },
    ],
  }),
  component: DiagnosticsPage,
});

function sanitizedHttpError(endpoint: string, status: number): Error {
  if (status === 401 || status === 403) {
    return new Error(`Brak aktywnej sesji operatora (${endpoint}, HTTP ${status}).`);
  }
  return new Error(`Nie udało się pobrać ${endpoint} (HTTP ${status}).`);
}

async function readJson<T>(response: Response, endpoint: string): Promise<T> {
  try {
    return (await response.json()) as T;
  } catch {
    throw new Error(`${endpoint} zwrócił nieprawidłową odpowiedź.`);
  }
}

function DiagnosticsPage() {
  const healthQuery = useQuery<HealthResponse>({
    queryKey: ["diagnostics", "ubuntu-health"],
    queryFn: async () => {
      const response = await fetch("/api/health", { credentials: "include" });
      // HTTP 503 nadal zawiera użyteczny, bezpieczny payload diagnostyczny.
      if (!response.ok && response.status !== 503) {
        throw sanitizedHttpError("/api/health", response.status);
      }
      return readJson<HealthResponse>(response, "/api/health");
    },
    refetchInterval: 60_000,
    refetchOnWindowFocus: false,
  });

  const diagnosticsQuery = useQuery<DiagnosticsResponse>({
    queryKey: ["diagnostics", "ubuntu-env"],
    queryFn: async () => {
      const response = await fetch("/api/diagnostics", { credentials: "include" });
      if (!response.ok) {
        throw sanitizedHttpError("/api/diagnostics", response.status);
      }
      return readJson<DiagnosticsResponse>(response, "/api/diagnostics");
    },
    refetchOnWindowFocus: false,
  });

  const ubuntuChecks = (diagnosticsQuery.data?.checks ?? []).filter(
    (check): check is UbuntuCheck => check.category === "ubuntu" && "name" in check,
  );
  const refreshing = healthQuery.isFetching || diagnosticsQuery.isFetching;

  const refresh = () => {
    void healthQuery.refetch();
    void diagnosticsQuery.refetch();
  };

  return (
    <div className="space-y-4">
      <PageHeader
        title="Diagnostyka"
        description="Narzędzia operacyjne dostępne po zalogowaniu, bez ujawniania sekretów i danych sesji."
        icon={<Stethoscope className="h-5 w-5" />}
      />

      <div className="grid gap-4 lg:grid-cols-2">
        <Link to="/database">
          <Card className="h-full p-5 transition-colors hover:bg-accent">
            <div className="flex items-center gap-2 font-semibold">
              <Database className="h-4 w-4 text-primary" />
              Stan danych i usług
            </div>
            <p className="mt-2 text-sm text-muted-foreground">
              Sprawdź połączenia, joby, rekordy oraz operacyjny stan backendu.
            </p>
          </Card>
        </Link>
        <Link to="/dev/logs">
          <Card className="h-full p-5 transition-colors hover:bg-accent">
            <div className="flex items-center gap-2 font-semibold">
              <ScrollText className="h-4 w-4 text-primary" />
              Logi aplikacji
            </div>
            <p className="mt-2 text-sm text-muted-foreground">
              Przejdź do logów deweloperskich, aby analizować błędy i przebieg zadań.
            </p>
          </Card>
        </Link>
      </div>

      <div className="flex justify-end">
        <Button variant="outline" size="sm" onClick={refresh} disabled={refreshing}>
          <RefreshCw className={`mr-2 h-4 w-4 ${refreshing ? "animate-spin" : ""}`} />
          Odśwież status Ubuntu
        </Button>
      </div>

      <UbuntuApiCard
        probe={healthQuery.data?.services.ubuntuApi}
        checks={ubuntuChecks}
        loading={healthQuery.isLoading || diagnosticsQuery.isLoading}
        healthError={healthQuery.error}
        diagnosticsError={diagnosticsQuery.error}
      />
    </div>
  );
}

function classifyUbuntuConfig(checks: UbuntuCheck[]): {
  state: UbuntuConfigState;
  presentCount: number;
} {
  const presentNames = new Set(checks.filter((check) => check.present).map((check) => check.name));
  const presentCount = UBUNTU_ENV_NAMES.filter((name) => presentNames.has(name)).length;

  if (presentCount === 0) return { state: "absent", presentCount };
  if (presentCount === UBUNTU_ENV_NAMES.length) return { state: "complete", presentCount };
  return { state: "partial", presentCount };
}

function UbuntuApiCard({
  probe,
  checks,
  loading,
  healthError,
  diagnosticsError,
}: {
  probe?: UbuntuProbe;
  checks: UbuntuCheck[];
  loading: boolean;
  healthError: Error | null;
  diagnosticsError: Error | null;
}) {
  const configuration = diagnosticsError || loading ? null : classifyUbuntuConfig(checks);
  const orderedChecks = UBUNTU_ENV_NAMES.map((name) =>
    checks.find((check) => check.name === name),
  ).filter((check): check is UbuntuCheck => check !== undefined);

  return (
    <Card className="space-y-4 p-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="font-semibold">Ubuntu API</h2>
          <p className="text-sm text-muted-foreground">
            Stan połączenia BFF → Cloudflare Access → FastAPI.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {probe?.latencyMs != null && (
            <span className="text-xs text-muted-foreground">{probe.latencyMs} ms</span>
          )}
          <ProbeBadge status={probe?.status} failed={healthError !== null} loading={loading} />
        </div>
      </div>

      {loading && !probe && !healthError && !diagnosticsError && (
        <p className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" /> Sprawdzam…
        </p>
      )}

      {healthError && (
        <Alert variant="destructive">
          <AlertTriangle className="h-4 w-4" />
          <AlertTitle>Błąd odczytu healthchecku</AlertTitle>
          <AlertDescription>{healthError.message}</AlertDescription>
        </Alert>
      )}

      {diagnosticsError && (
        <Alert variant="destructive">
          <AlertTriangle className="h-4 w-4" />
          <AlertTitle>Błąd odczytu konfiguracji</AlertTitle>
          <AlertDescription>{diagnosticsError.message}</AlertDescription>
        </Alert>
      )}

      {configuration?.state === "partial" && (
        <Alert variant="destructive">
          <XCircle className="h-4 w-4" />
          <AlertTitle>Konfiguracja niepełna — fail-closed</AlertTitle>
          <AlertDescription>
            Ustawiono {configuration.presentCount}/{UBUNTU_ENV_NAMES.length} wymaganych zmiennych.
            Transport nie wyśle requestu ani nie przełączy się automatycznie na legacy.
          </AlertDescription>
        </Alert>
      )}

      {configuration?.state === "absent" && (
        <Alert>
          <HelpCircle className="h-4 w-4" />
          <AlertTitle>Ubuntu API nieskonfigurowane</AlertTitle>
          <AlertDescription>
            Selektor używa ścieżki legacy, która wymaga kompletnego API_BASE_URL i API_BEARER_TOKEN.
          </AlertDescription>
        </Alert>
      )}

      {configuration?.state === "complete" && probe?.status === "ok" && (
        <Alert>
          <CheckCircle2 className="h-4 w-4 text-green-600" />
          <AlertTitle>Ubuntu API dostępne</AlertTitle>
          <AlertDescription>Transport jest gotowy do routowania ruchu na Ubuntu.</AlertDescription>
        </Alert>
      )}

      {configuration?.state === "complete" && probe?.status === "down" && (
        <Alert variant="destructive">
          <XCircle className="h-4 w-4" />
          <AlertTitle>Ubuntu API skonfigurowane, ale niedostępne</AlertTitle>
          <AlertDescription>
            Sprawdź Cloudflare Access, service token oraz dostępność FastAPI.
          </AlertDescription>
        </Alert>
      )}

      {configuration?.state === "complete" && probe?.status === "unconfigured" && (
        <Alert variant="destructive">
          <XCircle className="h-4 w-4" />
          <AlertTitle>Konfiguracja obecna, ale nieprawidłowa</AlertTitle>
          <AlertDescription>
            Sprawdź format HTTPS URL i komplet poświadczeń. Transport pozostaje fail-closed.
          </AlertDescription>
        </Alert>
      )}

      {probe?.requestId && (
        <p className="text-xs text-muted-foreground">
          Request-Id ostatniego probe: <code className="font-mono">{probe.requestId}</code>
        </p>
      )}

      <div className="space-y-2">
        {orderedChecks.map((check) => (
          <UbuntuEnvRow key={check.name} check={check} />
        ))}
        {!loading && !diagnosticsError && orderedChecks.length === 0 && (
          <p className="text-xs text-muted-foreground">Brak danych diagnostycznych Ubuntu.</p>
        )}
      </div>
    </Card>
  );
}

function ProbeBadge({
  status,
  failed,
  loading,
}: {
  status?: HealthStatus;
  failed: boolean;
  loading: boolean;
}) {
  if (failed) return <Badge variant="destructive">error</Badge>;
  if (!status && loading) return <Badge variant="secondary">loading</Badge>;
  if (status === "ok") return <Badge variant="outline">ok</Badge>;
  if (status === "down") return <Badge variant="destructive">down</Badge>;
  return <Badge variant="secondary">unconfigured</Badge>;
}

function UbuntuEnvRow({ check }: { check: UbuntuCheck }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border px-3 py-2 text-sm">
      <div className="flex min-w-0 items-center gap-2">
        {check.present ? (
          <CheckCircle2 className="h-4 w-4 shrink-0 text-green-600" />
        ) : (
          <XCircle className="h-4 w-4 shrink-0 text-muted-foreground" />
        )}
        <code className="truncate font-mono">{check.name}</code>
      </div>
      <div className="flex shrink-0 items-center gap-2">
        <Badge variant={check.required ? "outline" : "secondary"}>
          {check.required ? "wymagane" : "opcjonalne"}
        </Badge>
        <Badge variant={check.present ? "outline" : "secondary"}>
          {check.present ? "present" : "absent"}
        </Badge>
        {check.present && check.minLength != null && (
          <Badge variant={check.lengthOk ? "outline" : "destructive"}>
            {check.lengthOk ? "lengthOk" : "invalid"}
          </Badge>
        )}
      </div>
    </div>
  );
}
