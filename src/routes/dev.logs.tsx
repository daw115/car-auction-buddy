import { createFileRoute, Link } from "@tanstack/react-router";
import { useEffect, useMemo, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Pause, Play, Trash2, ArrowLeft, ChevronRight, Copy, Check, Download, ArrowDownNarrowWide, ArrowUpNarrowWide, Link2, Layers, ChevronDown } from "lucide-react";
import { toast } from "sonner";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

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
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  const [copiedId, setCopiedId] = useState<number | null>(null);
  const [copiedLinkId, setCopiedLinkId] = useState<number | null>(null);
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");
  const [groupByScope, setGroupByScope] = useState(false);
  const [collapsedScopes, setCollapsedScopes] = useState<Set<string>>(new Set());
  const pausedRef = useRef(paused);
  const scrollRef = useRef<HTMLDivElement>(null);
  const pendingRef = useRef<LogEntry[]>([]);

  const toggleExpanded = (id: number) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const copyExtra = async (entry: LogEntry) => {
    try {
      const payload = JSON.stringify(
        { id: entry.id, ts: entry.ts, level: entry.level, scope: entry.scope, message: entry.message, extra: entry.extra ?? null },
        null,
        2,
      );
      await navigator.clipboard.writeText(payload);
      setCopiedId(entry.id);
      toast.success("Skopiowano JSON wpisu");
      setTimeout(() => setCopiedId((c) => (c === entry.id ? null : c)), 1200);
    } catch {
      toast.error("Nie udało się skopiować");
    }
  };

  const copyResumeLink = async (id: number) => {
    try {
      const url = new URL("/api/dev/logs/stream", window.location.origin);
      url.searchParams.set("since", String(id));
      await navigator.clipboard.writeText(url.toString());
      setCopiedLinkId(id);
      toast.success(`Skopiowano link do wznowienia od #${id}`);
      setTimeout(() => setCopiedLinkId((c) => (c === id ? null : c)), 1200);
    } catch {
      toast.error("Nie udało się skopiować linku");
    }
  };

  const downloadFile = (filename: string, content: string, mime: string) => {
    const blob = new Blob([content], { type: mime });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };

  const exportFilteredJson = () => {
    if (filtered.length === 0) {
      toast.error("Brak wpisów do eksportu");
      return;
    }
    const stamp = new Date().toISOString().replace(/[:.]/g, "-");
    downloadFile(
      `dev-logs-${stamp}.json`,
      JSON.stringify({ exportedAt: new Date().toISOString(), count: filtered.length, entries: filtered }, null, 2),
      "application/json",
    );
    toast.success(`Wyeksportowano ${filtered.length} wpisów (JSON)`);
  };

  const exportFilteredHtml = () => {
    if (filtered.length === 0) {
      toast.error("Brak wpisów do eksportu");
      return;
    }
    const esc = (s: string) =>
      s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);
    const levelColor: Record<LogEntry["level"], string> = {
      info: "#22d3ee",
      warn: "#facc15",
      error: "#f87171",
      debug: "#e879f9",
      http: "#60a5fa",
    };
    const rows = filtered
      .map((e) => {
        const extra = e.extra ? `<pre class="extra">${esc(JSON.stringify(e.extra, null, 2))}</pre>` : "";
        return `<tr>
  <td class="ts">${esc(new Date(e.ts).toLocaleString())}</td>
  <td><span class="level" style="background:${levelColor[e.level]}22;color:${levelColor[e.level]};border-color:${levelColor[e.level]}55">${e.level.toUpperCase()}</span></td>
  <td class="scope">${esc(e.scope)}</td>
  <td class="msg">${esc(e.message)}${extra}</td>
</tr>`;
      })
      .join("\n");
    const html = `<!doctype html>
<html lang="pl"><head><meta charset="utf-8"/>
<title>Dev Logs Export — ${new Date().toISOString()}</title>
<style>
  :root { color-scheme: dark; }
  body { font-family: ui-sans-serif, system-ui, sans-serif; background:#0b0f17; color:#e5e7eb; margin:0; padding:24px; }
  h1 { font-size:18px; margin:0 0 4px; }
  .meta { color:#9ca3af; font-size:12px; margin-bottom:16px; }
  table { width:100%; border-collapse:collapse; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size:12px; }
  th, td { text-align:left; vertical-align:top; padding:6px 8px; border-bottom:1px solid #1f2937; }
  th { color:#9ca3af; font-weight:600; position:sticky; top:0; background:#0b0f17; }
  td.ts { white-space:nowrap; color:#9ca3af; }
  td.scope { white-space:nowrap; font-weight:600; color:#f3f4f6; }
  td.msg { color:#e5e7eb; word-break:break-word; }
  .level { display:inline-block; padding:1px 6px; border-radius:4px; border:1px solid; font-size:10px; }
  .extra { margin:6px 0 0; padding:8px; background:#111827; border:1px solid #1f2937; border-radius:6px; white-space:pre-wrap; word-break:break-all; color:#cbd5e1; font-size:11px; }
  tr:hover td { background:#111827; }
</style></head>
<body>
  <h1>Dev Logs Export</h1>
  <div class="meta">${esc(new Date().toISOString())} · ${filtered.length} wpisów · filtr: ${esc(filter || "—")} · poziomy: ${LEVELS.filter((l) => enabled[l]).join(", ")}</div>
  <table>
    <thead><tr><th>Czas</th><th>Poziom</th><th>Scope</th><th>Wiadomość</th></tr></thead>
    <tbody>
${rows}
    </tbody>
  </table>
</body></html>`;
    const stamp = new Date().toISOString().replace(/[:.]/g, "-");
    downloadFile(`dev-logs-${stamp}.html`, html, "text/html");
    toast.success(`Wyeksportowano ${filtered.length} wpisów (HTML)`);
  };

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

  // Auto-scroll to newest entry (top in desc, bottom in asc).
  useEffect(() => {
    if (paused) return;
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTop = sortDir === "asc" ? el.scrollHeight : 0;
  }, [entries, paused, sortDir]);

  const filtered = useMemo(() => {
    const q = filter.trim().toLowerCase();
    const list = entries.filter((e) => {
      if (!enabled[e.level]) return false;
      if (!q) return true;
      return (
        e.message.toLowerCase().includes(q) ||
        e.scope.toLowerCase().includes(q) ||
        (e.extra ? JSON.stringify(e.extra).toLowerCase().includes(q) : false)
      );
    });
    return sortDir === "asc" ? list : [...list].reverse();
  }, [entries, filter, enabled, sortDir]);

  const lastId = entries.length > 0 ? entries[entries.length - 1].id : null;

  type ScopeGroup = {
    scope: string;
    entries: LogEntry[];
    counts: Partial<Record<LogEntry["level"], number>>;
    lastTs: string;
  };

  const grouped = useMemo<ScopeGroup[]>(() => {
    if (!groupByScope) return [];
    const map = new Map<string, ScopeGroup>();
    for (const e of filtered) {
      let g = map.get(e.scope);
      if (!g) {
        g = { scope: e.scope, entries: [], counts: {}, lastTs: e.ts };
        map.set(e.scope, g);
      }
      g.entries.push(e);
      g.counts[e.level] = (g.counts[e.level] ?? 0) + 1;
      if (e.ts > g.lastTs) g.lastTs = e.ts;
    }
    const list = Array.from(map.values());
    list.sort((a, b) => (sortDir === "asc" ? a.lastTs.localeCompare(b.lastTs) : b.lastTs.localeCompare(a.lastTs)));
    return list;
  }, [filtered, groupByScope, sortDir]);

  const toggleScope = (scope: string) => {
    setCollapsedScopes((prev) => {
      const next = new Set(prev);
      if (next.has(scope)) next.delete(scope);
      else next.add(scope);
      return next;
    });
  };

  const collapseAllScopes = () => {
    setCollapsedScopes(new Set(grouped.map((g) => g.scope)));
  };
  const expandAllScopes = () => setCollapsedScopes(new Set());

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
                onClick={() => setSortDir((d) => (d === "asc" ? "desc" : "asc"))}
                className="h-8"
                title={sortDir === "asc" ? "Najnowsze na dole — kliknij aby odwrócić" : "Najnowsze na górze — kliknij aby odwrócić"}
              >
                {sortDir === "asc" ? (
                  <ArrowDownNarrowWide className="mr-1 h-3.5 w-3.5" />
                ) : (
                  <ArrowUpNarrowWide className="mr-1 h-3.5 w-3.5" />
                )}
                {sortDir === "asc" ? "Rosnąco" : "Malejąco"}
              </Button>
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="ghost" size="sm" className="h-8">
                    <Download className="mr-1 h-3.5 w-3.5" />
                    Eksport
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuItem onClick={exportFilteredJson}>Pobierz JSON</DropdownMenuItem>
                  <DropdownMenuItem onClick={exportFilteredHtml}>Pobierz HTML</DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
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
                filtered.map((e) => {
                  const isOpen = expanded.has(e.id);
                  const hasExtra = !!e.extra && Object.keys(e.extra).length > 0;
                  return (
                    <div
                      key={e.id}
                      className="border-b border-border/50 hover:bg-muted/30"
                    >
                      <div className="flex items-start gap-2 px-2 py-1">
                        <button
                          type="button"
                          onClick={() => toggleExpanded(e.id)}
                          className="mt-0.5 shrink-0 text-muted-foreground hover:text-foreground"
                          aria-label={isOpen ? "Zwiń" : "Rozwiń"}
                        >
                          <ChevronRight
                            className={`h-3.5 w-3.5 transition-transform ${isOpen ? "rotate-90" : ""}`}
                          />
                        </button>
                        <button
                          type="button"
                          onClick={() => copyResumeLink(e.id)}
                          title={`#${e.id} — kliknij, aby skopiować link wznawiający strumień od tego ID`}
                          className="shrink-0 inline-flex items-center gap-1 rounded border border-border/50 bg-muted/30 px-1 py-0 text-[10px] font-mono text-muted-foreground hover:text-foreground hover:border-border"
                        >
                          {copiedLinkId === e.id ? (
                            <Check className="h-2.5 w-2.5" />
                          ) : (
                            <Link2 className="h-2.5 w-2.5" />
                          )}
                          #{e.id}
                        </button>
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
                        <button
                          type="button"
                          onClick={() => toggleExpanded(e.id)}
                          className="break-all text-left text-foreground/90 hover:underline"
                        >
                          {e.message}
                        </button>
                        {hasExtra && !isOpen ? (
                          <span className="ml-auto shrink-0 max-w-[40%] truncate text-muted-foreground">
                            {JSON.stringify(e.extra)}
                          </span>
                        ) : null}
                      </div>
                      {isOpen ? (
                        <div className="ml-6 mr-2 mb-2 rounded-md border border-border/60 bg-muted/40">
                          <div className="flex items-center justify-between gap-2 border-b border-border/60 px-2 py-1">
                            <span className="text-[10px] uppercase tracking-wide text-muted-foreground">
                              {hasExtra ? "extra (JSON)" : "szczegóły"}
                            </span>
                            <Button
                              type="button"
                              variant="ghost"
                              size="sm"
                              className="h-6 px-2 text-[11px]"
                              onClick={() => copyExtra(e)}
                            >
                              {copiedId === e.id ? (
                                <>
                                  <Check className="mr-1 h-3 w-3" />
                                  Skopiowano
                                </>
                              ) : (
                                <>
                                  <Copy className="mr-1 h-3 w-3" />
                                  Kopiuj JSON
                                </>
                              )}
                            </Button>
                          </div>
                          <pre className="max-h-64 overflow-auto whitespace-pre-wrap break-all p-2 text-[11px] leading-relaxed text-foreground/90">
                            {hasExtra
                              ? JSON.stringify(e.extra, null, 2)
                              : JSON.stringify(
                                  { id: e.id, ts: e.ts, level: e.level, scope: e.scope, message: e.message },
                                  null,
                                  2,
                                )}
                          </pre>
                        </div>
                      ) : null}
                    </div>
                  );
                })
              )}
            </div>
          </ScrollArea>
        </Card>

        <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
          <p>
            Endpoint: <code>/api/dev/logs/stream</code> · Bufor 500 ostatnich wpisów ·
            Auto-scroll wyłącza się podczas pauzy.
          </p>
          {lastId !== null ? (
            <button
              type="button"
              onClick={() => copyResumeLink(lastId)}
              className="inline-flex items-center gap-1 rounded border border-border/50 bg-muted/30 px-2 py-0.5 font-mono hover:text-foreground hover:border-border"
              title="Skopiuj link wznawiający strumień od ostatniego ID"
            >
              {copiedLinkId === lastId ? (
                <Check className="h-3 w-3" />
              ) : (
                <Link2 className="h-3 w-3" />
              )}
              resume od #{lastId}
            </button>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function DevLogsGate() {
  const [status, setStatus] = useState<"checking" | "locked" | "ok" | "unavailable">("checking");
  const [unavailableReason, setUnavailableReason] = useState<string>("");
  const [token, setToken] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const check = async () => {
    try {
      const res = await fetch("/api/dev/auth", { credentials: "same-origin" });
      if (res.status === 403 || res.status === 503) {
        const body = (await res.json().catch(() => ({}))) as { reason?: string };
        setUnavailableReason(body.reason ?? `HTTP ${res.status}`);
        setStatus("unavailable");
        return;
      }
      const body = (await res.json()) as { authenticated: boolean };
      setStatus(body.authenticated ? "ok" : "locked");
    } catch {
      setStatus("locked");
    }
  };

  useEffect(() => {
    void check();
  }, []);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!token) return;
    setSubmitting(true);
    try {
      const res = await fetch("/api/dev/auth", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({ token }),
      });
      if (res.ok) {
        toast.success("Zalogowano");
        setToken("");
        setStatus("ok");
      } else {
        const body = (await res.json().catch(() => ({}))) as { reason?: string };
        toast.error(body.reason ?? "Nieprawidłowe hasło");
      }
    } catch {
      toast.error("Błąd połączenia");
    } finally {
      setSubmitting(false);
    }
  };

  if (status === "checking") {
    return (
      <div className="min-h-screen bg-background p-6 text-sm text-muted-foreground">
        Sprawdzanie dostępu…
      </div>
    );
  }

  if (status === "unavailable") {
    return (
      <div className="min-h-screen bg-background p-4 md:p-6">
        <div className="mx-auto max-w-md">
          <Card className="p-6 space-y-3">
            <h1 className="text-lg font-semibold text-foreground">Dev Logs niedostępne</h1>
            <p className="text-sm text-muted-foreground">{unavailableReason}</p>
            <Button asChild variant="outline" size="sm">
              <Link to="/">
                <ArrowLeft className="h-4 w-4 mr-1" /> Wróć
              </Link>
            </Button>
          </Card>
        </div>
      </div>
    );
  }

  if (status === "locked") {
    return (
      <div className="min-h-screen bg-background p-4 md:p-6">
        <div className="mx-auto max-w-md">
          <Card className="p-6 space-y-4">
            <div>
              <h1 className="text-lg font-semibold text-foreground">Dev Logs — logowanie</h1>
              <p className="text-xs text-muted-foreground mt-1">
                Wprowadź hasło dostępu (DEV_LOGS_TOKEN).
              </p>
            </div>
            <form onSubmit={submit} className="space-y-3">
              <Input
                type="password"
                value={token}
                onChange={(e) => setToken(e.target.value)}
                placeholder="Hasło"
                autoFocus
              />
              <div className="flex items-center justify-between">
                <Button asChild variant="ghost" size="sm">
                  <Link to="/">
                    <ArrowLeft className="h-4 w-4 mr-1" /> Anuluj
                  </Link>
                </Button>
                <Button type="submit" size="sm" disabled={submitting || !token}>
                  {submitting ? "Logowanie…" : "Zaloguj"}
                </Button>
              </div>
            </form>
          </Card>
        </div>
      </div>
    );
  }

  return <DevLogsPage />;
}

export const Route = createFileRoute("/dev/logs")({
  component: DevLogsGate,
});

