import { useCallback, useEffect, useState } from "react";
import { useServerFn } from "@tanstack/react-start";
import { toast } from "sonner";
import { listLogs, clearLogs } from "@/server/api.functions";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { RefreshCw, Trash2, ChevronRight, ScrollText, AlertCircle, AlertTriangle, Info, Bug, Download } from "lucide-react";

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

type Props = {
  clientId: string | null;
  recordId?: string | null;
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

export function LogsPanel({ clientId, recordId }: Props) {
  const fnList = useServerFn(listLogs);
  const fnClear = useServerFn(clearLogs);
  const [rows, setRows] = useState<LogRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [filter, setFilter] = useState<"all" | "scrape" | "ai_analysis">("all");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const r = (await fnList({
        data: {
          clientId: clientId ?? undefined,
          recordId: recordId ?? undefined,
          operation: filter === "all" ? undefined : filter,
          limit: 100,
        },
      })) as LogRow[];
      setRows(r);
    } catch (e) {
      toast.error(`Logi: ${(e as Error).message}`);
    } finally {
      setLoading(false);
    }
  }, [fnList, clientId, recordId, filter]);

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
                  <div className="mt-0.5 text-[10px] text-muted-foreground">
                    {new Date(row.created_at).toLocaleTimeString("pl-PL")}
                    {typeof row.duration_ms === "number" ? ` · ${row.duration_ms} ms` : ""}
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
