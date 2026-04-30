import { createFileRoute, Link } from "@tanstack/react-router";
import { useEffect, useMemo, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Pause, Play, Trash2, ArrowLeft, ChevronRight, Copy, Check } from "lucide-react";
import { toast } from "sonner";

type LogEntry = {
  id: number;
  ts: string;
  level: "info" | "warn" | "error" | "debug" | "http";
  scope: string;
  message: string;
  extra?: Record<string, unknown> | null;
};

const LEVEL_STYLES: Record<LogEntry["level"], string> = {
  info: "bg-cyan-500/15 text-cyan-400 border-cyan-500/30",
  warn: "bg-yellow-500/15 text-yellow-400 border-yellow-500/30",
  error: "bg-red-500/15 text-red-400 border-red-500/30",
  debug: "bg-fuchsia-500/15 text-fuchsia-400 border-fuchsia-500/30",
  http: "bg-blue-500/15 text-blue-400 border-blue-500/30",
};

const LEVELS: LogEntry["level"][] = ["info", "warn", "error", "debug", "http"];

function DevLogsPage() {
  const [entries, setEntries] = useState<LogEntry[]>([]);
  const [paused, setPaused] = useState(false);
  const [filter, setFilter] = useState("");
  const [enabled, setEnabled] = useState<Record<LogEntry["level"], boolean>>({
    info: true,
    warn: true,
    error: true,
    debug: true,
    http: true,
  });
  const [connected, setConnected] = useState(false);
  const pausedRef = useRef(paused);
  const scrollRef = useRef<HTMLDivElement>(null);
  const pendingRef = useRef<LogEntry[]>([]);

  useEffect(() => {
    pausedRef.current = paused;
    if (!paused && pendingRef.current.length > 0) {
      setEntries((prev) => [...prev, ...pendingRef.current].slice(-1000));
      pendingRef.current = [];
    }
  }, [paused]);

  useEffect(() => {
    const es = new EventSource("/api/dev/logs/stream");
    es.onopen = () => setConnected(true);
    es.onerror = () => setConnected(false);
    es.onmessage = (ev) => {
      try {
        const entry = JSON.parse(ev.data) as LogEntry;
        if (pausedRef.current) {
          pendingRef.current.push(entry);
        } else {
          setEntries((prev) => {
            const next = [...prev, entry];
            return next.length > 1000 ? next.slice(-1000) : next;
          });
        }
      } catch {
        // ignore malformed
      }
    };
    return () => es.close();
  }, []);

  // Auto-scroll to bottom on new entries (when not paused).
  useEffect(() => {
    if (paused) return;
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [entries, paused]);

  const filtered = useMemo(() => {
    const q = filter.trim().toLowerCase();
    return entries.filter((e) => {
      if (!enabled[e.level]) return false;
      if (!q) return true;
      return (
        e.message.toLowerCase().includes(q) ||
        e.scope.toLowerCase().includes(q) ||
        (e.extra ? JSON.stringify(e.extra).toLowerCase().includes(q) : false)
      );
    });
  }, [entries, filter, enabled]);

  return (
    <div className="min-h-screen bg-background p-4 md:p-6">
      <div className="mx-auto max-w-6xl space-y-4">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <Button asChild variant="ghost" size="icon">
              <Link to="/">
                <ArrowLeft className="h-4 w-4" />
              </Link>
            </Button>
            <div>
              <h1 className="text-xl font-semibold text-foreground">Dev Logs</h1>
              <p className="text-xs text-muted-foreground">
                Strumień logów serwera w czasie rzeczywistym (SSE)
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <span
              className={`inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-xs ${
                connected
                  ? "border-green-500/40 bg-green-500/10 text-green-500"
                  : "border-muted bg-muted/30 text-muted-foreground"
              }`}
            >
              <span
                className={`h-1.5 w-1.5 rounded-full ${connected ? "bg-green-500" : "bg-muted-foreground"}`}
              />
              {connected ? "live" : "offline"}
            </span>
          </div>
        </div>

        <Card className="p-3">
          <div className="flex flex-wrap items-center gap-2">
            <Input
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              placeholder="Filtruj po wiadomości / scope / extra…"
              className="h-8 max-w-xs"
            />
            <div className="flex flex-wrap items-center gap-1">
              {LEVELS.map((lvl) => (
                <button
                  key={lvl}
                  type="button"
                  onClick={() => setEnabled((s) => ({ ...s, [lvl]: !s[lvl] }))}
                  className={`rounded-md border px-2 py-0.5 text-xs uppercase transition ${
                    enabled[lvl]
                      ? LEVEL_STYLES[lvl]
                      : "border-border bg-muted/30 text-muted-foreground line-through"
                  }`}
                >
                  {lvl}
                </button>
              ))}
            </div>
            <div className="ml-auto flex items-center gap-1">
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setPaused((p) => !p)}
                className="h-8"
              >
                {paused ? <Play className="mr-1 h-3.5 w-3.5" /> : <Pause className="mr-1 h-3.5 w-3.5" />}
                {paused ? `Wznów${pendingRef.current.length ? ` (${pendingRef.current.length})` : ""}` : "Pauza"}
              </Button>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setEntries([])}
                className="h-8"
              >
                <Trash2 className="mr-1 h-3.5 w-3.5" />
                Wyczyść
              </Button>
            </div>
          </div>
        </Card>

        <Card className="overflow-hidden">
          <ScrollArea className="h-[70vh]">
            <div ref={scrollRef} className="h-[70vh] overflow-y-auto p-2 font-mono text-xs">
              {filtered.length === 0 ? (
                <div className="flex h-full items-center justify-center text-muted-foreground">
                  Brak wpisów. Wykonaj jakąś akcję w aplikacji…
                </div>
              ) : (
                filtered.map((e) => (
                  <div
                    key={e.id}
                    className="flex items-start gap-2 border-b border-border/50 px-2 py-1 hover:bg-muted/30"
                  >
                    <span className="shrink-0 text-muted-foreground">
                      {new Date(e.ts).toLocaleTimeString()}
                    </span>
                    <Badge
                      variant="outline"
                      className={`shrink-0 px-1.5 py-0 text-[10px] uppercase ${LEVEL_STYLES[e.level]}`}
                    >
                      {e.level}
                    </Badge>
                    <span className="shrink-0 font-semibold text-foreground">{e.scope}</span>
                    <span className="break-all text-foreground/90">{e.message}</span>
                    {e.extra ? (
                      <span className="ml-auto shrink-0 truncate text-muted-foreground">
                        {JSON.stringify(e.extra)}
                      </span>
                    ) : null}
                  </div>
                ))
              )}
            </div>
          </ScrollArea>
        </Card>

        <p className="text-xs text-muted-foreground">
          Endpoint: <code>/api/dev/logs/stream</code> · Bufor 500 ostatnich wpisów ·
          Auto-scroll wyłącza się podczas pauzy.
        </p>
      </div>
    </div>
  );
}

export const Route = createFileRoute("/dev/logs")({
  component: DevLogsPage,
});
