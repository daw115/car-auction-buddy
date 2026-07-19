import { useCallback, useEffect, useState } from "react";
import { useServerFn } from "@tanstack/react-start";
import {
  AlertCircle,
  CheckCircle2,
  Clock,
  Loader2,
  RefreshCw,
  Wifi,
} from "lucide-react";

import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { backendHealth } from "@/functions/backend.functions";

type HealthService = {
  status: "ok" | "down" | "unconfigured";
  error?: string;
  url?: string;
  provider?: string;
  model?: string;
};
type HealthResult = {
  checkedAt: string;
  durationMs: number;
  services: { database: HealthService; backend: HealthService };
};

export function ConnectionStatusPanel() {
  const fnCheckHealth = useServerFn(backendHealth);
  const [health, setHealth] = useState<HealthResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const doCheck = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const r = (await fnCheckHealth()) as HealthResult;
      setHealth(r);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [fnCheckHealth]);

  useEffect(() => {
    void doCheck();
    const iv = setInterval(() => void doCheck(), 60_000);
    return () => clearInterval(iv);
  }, [doCheck]);

  const statusIcon = (s: HealthService["status"]) => {
    if (s === "ok") return <CheckCircle2 className="h-3.5 w-3.5 text-[oklch(0.55_0.16_145)]" />;
    if (s === "down") return <AlertCircle className="h-3.5 w-3.5 text-destructive" />;
    return <AlertCircle className="h-3.5 w-3.5 text-muted-foreground" />;
  };

  const statusLabel = (s: HealthService["status"]) =>
    s === "ok" ? "Online" : s === "down" ? "Niedostępny" : "Nieskonfigurowany";

  const statusColor = (s: HealthService["status"]) =>
    s === "ok"
      ? "text-[oklch(0.55_0.16_145)]"
      : s === "down"
        ? "text-destructive"
        : "text-muted-foreground";

  const formatTime = (iso: string) => {
    try {
      return new Date(iso).toLocaleTimeString("pl-PL", {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      });
    } catch {
      return iso;
    }
  };

  return (
    <Card className="p-3">
      <div className="mb-2 flex items-center justify-between">
        <h2 className="flex items-center gap-1.5 text-sm font-semibold">
          <Wifi className="h-3.5 w-3.5" /> Status połączeń
        </h2>
        <Button variant="ghost" size="sm" onClick={() => void doCheck()} disabled={loading}>
          {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
        </Button>
      </div>

      {error && <p className="mb-2 text-xs text-destructive">{error}</p>}

      {health && (
        <div className="space-y-2">
          <ServiceRow label="Baza danych" service={health.services.database} statusIcon={statusIcon} statusLabel={statusLabel} statusColor={statusColor} />
          <ServiceRow label="Backend (usacar-api)" service={health.services.backend} statusIcon={statusIcon} statusLabel={statusLabel} statusColor={statusColor} showUrl />

          <div className="flex items-center justify-between pt-1 text-[10px] text-muted-foreground">
            <span className="flex items-center gap-1">
              <Clock className="h-3 w-3" /> Ostatni check: {formatTime(health.checkedAt)}
            </span>
            <span>{health.durationMs}ms</span>
          </div>
        </div>
      )}

      {!health && !error && loading && (
        <div className="flex items-center justify-center py-3">
          <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
        </div>
      )}
    </Card>
  );
}

function ServiceRow({
  label,
  service,
  statusIcon,
  statusLabel,
  statusColor,
  showUrl,
  showProvider,
}: {
  label: string;
  service: HealthService;
  statusIcon: (s: HealthService["status"]) => React.ReactNode;
  statusLabel: (s: HealthService["status"]) => string;
  statusColor: (s: HealthService["status"]) => string;
  showUrl?: boolean;
  showProvider?: boolean;
}) {
  return (
    <div className="rounded-md border border-border px-2 py-1.5">
      <div className="flex items-center justify-between">
        <span className="flex items-center gap-1.5 text-xs font-medium">
          {statusIcon(service.status)} {label}
        </span>
        <span className={`text-[10px] font-medium ${statusColor(service.status)}`}>
          {statusLabel(service.status)}
        </span>
      </div>
      {showUrl && service.url && (
        <p className="mt-0.5 text-[10px] text-muted-foreground">{service.url}</p>
      )}
      {showProvider && service.provider && (
        <p className="mt-0.5 text-[10px] text-muted-foreground">
          {service.provider}
          {service.model ? ` · ${service.model}` : ""}
        </p>
      )}
      {service.error && (
        <p className="mt-1 text-[10px] text-destructive leading-tight">{service.error}</p>
      )}
    </div>
  );
}
