import { useCallback, useEffect, useState } from "react";
import { useServerFn } from "@tanstack/react-start";
import { toast } from "sonner";
import { listLogs, clearLogs } from "@/server/api.functions";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { RefreshCw, Trash2, ChevronRight, ScrollText, AlertCircle, AlertTriangle, Info, Bug, Download, ExternalLink } from "lucide-react";

type LogRow = {
  id: string;
  created_at: string;
  client_id: string | null;
  record_id: string | null;
  operation: string;
  step: string | null;
  level: string;
  message: string;
  details: Record<string, unknown> | null;
  duration_ms: number | null;
};

type RecordSummary = { id: string; title: string | null };

type Props = {
  clientId: string | null;
  recordId?: string | null;
  records?: RecordSummary[];
  onOpenRecord?: (id: string) => void;
};

const LEVEL_STYLES: Record<string, string> = {
  error: "bg-destructive/15 text-destructive border-destructive/30",
  warn: "bg-amber-500/15 text-amber-700 dark:text-amber-400 border-amber-500/30",
  info: "bg-sky-500/10 text-sky-700 dark:text-sky-400 border-sky-500/30",
  debug: "bg-muted text-muted-foreground border-border",
};

function levelIcon(level: string) {
  if (level === "error") return <AlertCircle className="h-3 w-3" />;
  if (level === "warn") return <AlertTriangle className="h-3 w-3" />;
  if (level === "debug") return <Bug className="h-3 w-3" />;
  return <Info className="h-3 w-3" />;
}

type LevelFilter = "info" | "warn" | "error";
const ALL_LEVELS: LevelFilter[] = ["info", "warn", "error"];

function toIsoStart(localDate: string): string | undefined {
  if (!localDate) return undefined;
  const d = new Date(`${localDate}T00:00:00`);
  return isNaN(d.getTime()) ? undefined : d.toISOString();
}
function toIsoEnd(localDate: string): string | undefined {
  if (!localDate) return undefined;
  const d = new Date(`${localDate}T23:59:59.999`);
  return isNaN(d.getTime()) ? undefined : d.toISOString();
}

export function LogsPanel({ clientId, recordId, records, onOpenRecord }: Props) {
  const fnList = useServerFn(listLogs);
  const fnClear = useServerFn(clearLogs);
  const [rows, setRows] = useState<LogRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [filter, setFilter] = useState<"all" | "scrape" | "ai_analysis">("all");
  const [levels, setLevels] = useState<Set<LevelFilter>>(new Set(ALL_LEVELS));
  const [dateFrom, setDateFrom] = useState<string>("");
  const [dateTo, setDateTo] = useState<string>("");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const selectedLevels = Array.from(levels);
      const r = (await fnList({
        data: {
          clientId: clientId ?? undefined,
          recordId: recordId ?? undefined,
          operation: filter === "all" ? undefined : filter,
          levels:
            selectedLevels.length > 0 && selectedLevels.length < ALL_LEVELS.length
              ? selectedLevels
              : undefined,
          from: toIsoStart(dateFrom),
          to: toIsoEnd(dateTo),
          limit: 200,
        },
      })) as LogRow[];
      setRows(r);
    } catch (e) {
      toast.error(`Logi: ${(e as Error).message}`);
    } finally {
      setLoading(false);
    }
  }, [fnList, clientId, recordId, filter, levels, dateFrom, dateTo]);

  useEffect(() => {
    void refresh();
    const t = setInterval(() => void refresh(), 8000);
    return () => clearInterval(t);
  }, [refresh]);

  const handleClear = async () => {
    if (!confirm(clientId ? "Wyczyścić logi tego klienta?" : "Wyczyścić wszystkie logi?")) return;
    try {
      await fnClear({ data: { clientId: clientId ?? undefined } });
      toast.success("Logi wyczyszczone");
      await refresh();
    } catch (e) {
      toast.error((e as Error).message);
    }
  };

  const toggle = (id: string) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  return (
    <Card className="mt-3 p-3">
      <div className="mb-2 flex items-center justify-between">
        <div className="flex items-center gap-1.5">
          <ScrollText className="h-4 w-4 text-muted-foreground" />
          <h2 className="text-sm font-semibold">
            Status & logi {clientId ? "klienta" : "(globalne)"}
          </h2>
        </div>
        <div className="flex items-center gap-1">
          <Button variant="ghost" size="sm" onClick={() => void refresh()} title="Odśwież">
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => downloadLogs(rows, "json", scopeLabel(clientId, recordId))}
            disabled={rows.length === 0}
            title="Pobierz JSON"
          >
            <Download className="h-3.5 w-3.5" />
            <span className="ml-1 text-[10px]">JSON</span>
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => downloadLogs(rows, "csv", scopeLabel(clientId, recordId))}
            disabled={rows.length === 0}
            title="Pobierz CSV"
          >
            <Download className="h-3.5 w-3.5" />
            <span className="ml-1 text-[10px]">CSV</span>
          </Button>
          <Button variant="ghost" size="sm" onClick={handleClear} title="Wyczyść logi">
            <Trash2 className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>

      <div className="mb-2 flex gap-1">
        {(["all", "scrape", "ai_analysis"] as const).map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={`rounded px-2 py-0.5 text-[11px] ${
              filter === f
                ? "bg-primary text-primary-foreground"
                : "bg-muted text-muted-foreground hover:bg-muted/70"
            }`}
          >
            {f === "all" ? "Wszystkie" : f === "scrape" ? "Scrape" : "AI"}
          </button>
        ))}
      </div>

      <div className="mb-2 flex flex-wrap items-center gap-1">
        {ALL_LEVELS.map((lvl) => {
          const active = levels.has(lvl);
          return (
            <button
              key={lvl}
              type="button"
              onClick={() =>
                setLevels((prev) => {
                  const next = new Set(prev);
                  if (next.has(lvl)) next.delete(lvl);
                  else next.add(lvl);
                  // Don't allow empty selection — reset to all.
                  if (next.size === 0) return new Set(ALL_LEVELS);
                  return next;
                })
              }
              className={`rounded border px-1.5 py-0.5 text-[10px] capitalize ${
                active ? LEVEL_STYLES[lvl] ?? "" : "border-border bg-background text-muted-foreground opacity-60"
              }`}
              title={`Pokaż poziom: ${lvl}`}
            >
              {lvl}
            </button>
          );
        })}
      </div>

      <div className="mb-2 grid grid-cols-2 gap-1">
        <label className="flex flex-col text-[10px] text-muted-foreground">
          Od
          <input
            type="date"
            value={dateFrom}
            max={dateTo || undefined}
            onChange={(e) => setDateFrom(e.target.value)}
            className="mt-0.5 rounded border border-border bg-background px-1.5 py-0.5 text-[11px]"
          />
        </label>
        <label className="flex flex-col text-[10px] text-muted-foreground">
          Do
          <input
            type="date"
            value={dateTo}
            min={dateFrom || undefined}
            onChange={(e) => setDateTo(e.target.value)}
            className="mt-0.5 rounded border border-border bg-background px-1.5 py-0.5 text-[11px]"
          />
        </label>
        {(dateFrom || dateTo) && (
          <button
            type="button"
            onClick={() => {
              setDateFrom("");
              setDateTo("");
            }}
            className="col-span-2 text-left text-[10px] text-muted-foreground underline hover:text-foreground"
          >
            Wyczyść zakres dat
          </button>
        )}
      </div>

      <div className="max-h-[40vh] space-y-1 overflow-y-auto">
        {rows.length === 0 && (
          <p className="px-1 py-2 text-xs text-muted-foreground">
            Brak zdarzeń. Uruchom wyszukiwanie lub analizę AI.
          </p>
        )}
        {rows.map((row) => {
          const isOpen = expanded.has(row.id);
          const hasDetails = row.details && Object.keys(row.details).length > 0;
          return (
            <div key={row.id} className="rounded-md border border-border/60 text-xs">
              <button
                type="button"
                onClick={() => hasDetails && toggle(row.id)}
                className="flex w-full items-start gap-1.5 px-2 py-1.5 text-left hover:bg-muted/50"
              >
                {hasDetails ? (
                  <ChevronRight
                    className={`mt-0.5 h-3 w-3 shrink-0 transition-transform ${isOpen ? "rotate-90" : ""}`}
                  />
                ) : (
                  <span className="w-3" />
                )}
                <Badge
                  variant="outline"
                  className={`gap-1 px-1.5 py-0 text-[10px] ${LEVEL_STYLES[row.level] ?? ""}`}
                >
                  {levelIcon(row.level)} {row.level}
                </Badge>
                <span className="rounded bg-muted px-1 text-[10px] text-muted-foreground">
                  {row.operation}
                  {row.step ? `·${row.step}` : ""}
                </span>
                <div className="min-w-0 flex-1">
                  <div className="break-words leading-snug">{row.message}</div>
                  <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[10px] text-muted-foreground">
                    <span>{new Date(row.created_at).toLocaleTimeString("pl-PL")}</span>
                    {typeof row.duration_ms === "number" && <span>· {row.duration_ms} ms</span>}
                    {row.record_id && (
                      <RecordChip
                        recordId={row.record_id}
                        title={records?.find((r) => r.id === row.record_id)?.title ?? null}
                        active={row.record_id === recordId}
                        onOpen={onOpenRecord}
                      />
                    )}
                  </div>
                </div>
              </button>
              {isOpen && hasDetails && (
                <pre className="max-h-48 overflow-auto border-t border-border/50 bg-muted/30 px-2 py-1.5 text-[10px] leading-tight">
                  {JSON.stringify(row.details, null, 2)}
                </pre>
              )}
            </div>
          );
        })}
      </div>
    </Card>
  );
}

function scopeLabel(clientId: string | null, recordId?: string | null): string {
  if (recordId) return `record-${recordId.slice(0, 8)}`;
  if (clientId) return `client-${clientId.slice(0, 8)}`;
  return "all";
}

function csvEscape(value: unknown): string {
  if (value == null) return "";
  const s = typeof value === "string" ? value : JSON.stringify(value);
  if (/[",\n\r]/.test(s)) return `"${s.replace(/"/g, '""')}"`;
  return s;
}

function toCsv(rows: LogRow[]): string {
  const headers = [
    "created_at",
    "operation",
    "step",
    "level",
    "message",
    "duration_ms",
    "client_id",
    "record_id",
    "details",
  ];
  const lines = [headers.join(",")];
  for (const r of rows) {
    lines.push(
      [
        r.created_at,
        r.operation,
        r.step ?? "",
        r.level,
        r.message,
        r.duration_ms ?? "",
        r.client_id ?? "",
        r.record_id ?? "",
        r.details ? JSON.stringify(r.details) : "",
      ]
        .map(csvEscape)
        .join(","),
    );
  }
  return lines.join("\n");
}

function triggerDownload(filename: string, content: string, mime: string) {
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function downloadLogs(rows: LogRow[], format: "json" | "csv", scope: string) {
  const ts = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
  if (format === "json") {
    triggerDownload(`logs-${scope}-${ts}.json`, JSON.stringify(rows, null, 2), "application/json");
  } else {
    triggerDownload(`logs-${scope}-${ts}.csv`, toCsv(rows), "text/csv");
  }
}

function RecordChip({
  recordId,
  title,
  active,
  onOpen,
}: {
  recordId: string;
  title: string | null;
  active: boolean;
  onOpen?: (id: string) => void;
}) {
  const label = title?.trim() || `${recordId.slice(0, 8)}`;
  const baseCls =
    "inline-flex items-center gap-1 rounded border px-1.5 py-0 text-[10px] max-w-[180px] truncate";
  const stateCls = active
    ? "border-primary/40 bg-primary/10 text-primary"
    : "border-border bg-background hover:bg-accent hover:text-accent-foreground";

  if (!onOpen) {
    return (
      <span className={`${baseCls} ${stateCls}`} title={`Rekord ${recordId}`}>
        <ExternalLink className="h-2.5 w-2.5 shrink-0" />
        <span className="truncate">{label}</span>
      </span>
    );
  }
  return (
    <button
      type="button"
      onClick={(e) => {
        e.stopPropagation();
        onOpen(recordId);
      }}
      className={`${baseCls} ${stateCls}`}
      title={`Otwórz rekord ${recordId}`}
    >
      <ExternalLink className="h-2.5 w-2.5 shrink-0" />
      <span className="truncate">{label}</span>
    </button>
  );
}
