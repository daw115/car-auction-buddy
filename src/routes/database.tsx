import { createFileRoute, Link } from "@tanstack/react-router";
import { useState, useEffect, useCallback } from "react";
import { useServerFn } from "@tanstack/react-start";
import { toast } from "sonner";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ThemeToggle } from "@/components/theme-toggle";
import {
  getDbOverview,
  getBackendRecordsList,
  getBackendRecordDetails,
  deleteBackendRecord,
  listAllJobs,
  getJobDetails,
  listLlmCacheEntries,
  deleteLlmCacheEntry,
  clearLlmCache,
  listHtmlCache,
  fetchAuthHtml,
  getModelNormalizations,
  deleteModelNormalization,
  getRecordFeedback,
  submitLotFeedback,
  deleteLotFeedback,
  analyzeFeedback,
} from "@/functions/api.functions";
import { SITE_USERS } from "@/lib/site-user";
import { Textarea } from "@/components/ui/textarea";
import {
  RefreshCw,
  Loader2,
  Eye,
  Trash2,
  Database,
  Search,
  ArrowLeft,
  FileText,
  HardDrive,
  Cpu,
  Globe,
  Inbox,
  ThumbsUp,
  ThumbsDown,
  Brain,
} from "lucide-react";

export const Route = createFileRoute("/database")({
  head: () => ({
    meta: [
      { title: "Baza danych — USA Car Finder" },
      { name: "description", content: "Przeglądaj bazę danych aplikacji" },
    ],
  }),
  component: DatabasePage,
});

// ── Helpers ──

function fmtDate(d: string | null | undefined) {
  if (!d) return "—";
  try {
    return new Date(d).toLocaleString("pl-PL", {
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return d;
  }
}

function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null) return "—";
  const s = Math.round(seconds);
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m ${s % 60}s`;
  return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
}

function durationColorClass(seconds: number | null | undefined): string {
  if (seconds == null) return "text-muted-foreground italic";
  if (seconds < 300) return "text-emerald-600 dark:text-emerald-400";
  if (seconds < 900) return "text-blue-600 dark:text-blue-400";
  return "text-orange-600 dark:text-orange-400";
}

function fmtSize(kb: number | undefined) {
  if (!kb) return "—";
  return kb > 1024 ? `${(kb / 1024).toFixed(1)} MB` : `${kb.toFixed(1)} KB`;
}

function EmptyState({ text }: { text: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
      <Inbox className="h-10 w-10 mb-2" />
      <p className="text-sm">{text}</p>
    </div>
  );
}

function Spin() {
  return <Loader2 className="h-4 w-4 animate-spin" />;
}

// ── Overview Section ──

function OverviewSection() {
  const [data, setData] = useState<Record<string, any> | null>(null);
  const [loading, setLoading] = useState(true);
  const fn = useServerFn(getDbOverview);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fn();
      setData(r);
    } catch {
      toast.error("Nie udało się pobrać overview");
    } finally {
      setLoading(false);
    }
  }, [fn]);

  useEffect(() => { load(); }, []);

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between pb-3">
        <CardTitle className="text-base">📊 Przegląd baz danych</CardTitle>
        <Button variant="outline" size="sm" onClick={load} disabled={loading}>
          {loading ? <Spin /> : <RefreshCw className="h-3.5 w-3.5" />}
          <span className="ml-1.5">Refresh</span>
        </Button>
      </CardHeader>
      <CardContent>
        {loading && !data ? (
          <div className="flex justify-center py-6"><Spin /></div>
        ) : !data ? (
          <EmptyState text="Backend niedostępny" />
        ) : (
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <StatCard
              icon={<FileText className="h-4 w-4" />}
              label="Search records"
              value={data.app_db?.search_records ?? 0}
              sub={data.app_db?.latest_record_at ? `Najnowszy: ${fmtDate(data.app_db.latest_record_at)}` : undefined}
            />
            <StatCard
              icon={<Cpu className="h-4 w-4" />}
              label="Jobs"
              value={data.jobs_db?.total ?? 0}
              sub={data.jobs_db?.by_status ? Object.entries(data.jobs_db.by_status).map(([k, v]) => `${k}: ${v}`).join(", ") : undefined}
            />
            <StatCard
              icon={<HardDrive className="h-4 w-4" />}
              label="LLM cache"
              value={`${data.llm_cache?.fresh ?? 0} świeżych`}
              sub={data.llm_cache?.ttl_hours ? `TTL ${data.llm_cache.ttl_hours}h` : undefined}
            />
            <StatCard
              icon={<Globe className="h-4 w-4" />}
              label="HTML cache"
              value={`${data.html_cache?.total_files ?? 0} plików`}
              sub={data.html_cache?.total_size_kb ? fmtSize(data.html_cache.total_size_kb) : undefined}
            />
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function StatCard({ icon, label, value, sub }: { icon: React.ReactNode; label: string; value: string | number; sub?: string }) {
  return (
    <div className="rounded-lg border bg-card p-3">
      <div className="flex items-center gap-2 text-xs text-muted-foreground mb-1">
        {icon} {label}
      </div>
      <div className="text-lg font-semibold">{value}</div>
      {sub && <div className="text-xs text-muted-foreground mt-0.5 truncate">{sub}</div>}
    </div>
  );
}

// ── Search Records Section ──

function statusBadge(status: string | undefined) {
  if (!status) return <Badge variant="outline" className="text-[10px]">—</Badge>;
  switch (status) {
    case "done":
    case "new":
      return <Badge variant="default" className="text-[10px]">✅ Ukończone</Badge>;
    case "cancelled":
      return <Badge variant="secondary" className="text-[10px]">⛔ Anulowane</Badge>;
    case "error":
      return <Badge variant="destructive" className="text-[10px]">❌ Błąd</Badge>;
    case "interrupted":
      return <Badge variant="outline" className="text-[10px]">⚠️ Przerwane</Badge>;
    default:
      return <Badge variant="outline" className="text-[10px]">{status}</Badge>;
  }
}

function RecordsSection() {
  const [records, setRecords] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState("");
  const [limit, setLimit] = useState(50);
  const [onlyCompleted, setOnlyCompleted] = useState(true);
  const [userFilter, setUserFilter] = useState<string>("all");
  const [detail, setDetail] = useState<any>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [confirmDel, setConfirmDel] = useState<any | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const fn = useServerFn(getBackendRecordsList);
  const fnDetail = useServerFn(getBackendRecordDetails);
  const fnDelete = useServerFn(deleteBackendRecord);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fn({ data: { query: query || undefined, limit } });
      setRecords(r?.records ?? []);
    } catch {
      toast.error("Nie udało się pobrać rekordów");
    } finally {
      setLoading(false);
    }
  }, [fn, query, limit]);

  useEffect(() => { load(); }, [limit]);

  const [detailRecordId, setDetailRecordId] = useState<string | null>(null);
  const [analyzeOpen, setAnalyzeOpen] = useState(false);

  const openDetail = async (id: string) => {
    setDetailRecordId(String(id));
    setDetailLoading(true);
    try {
      const r = await fnDetail({ data: { id } });
      setDetail(r);
    } catch {
      toast.error("Nie udało się pobrać szczegółów");
    } finally {
      setDetailLoading(false);
    }
  };

  const handleDelete = async () => {
    if (!confirmDel) return;
    const id = String(confirmDel.id);
    setDeletingId(id);
    try {
      const res = await fnDelete({ data: { id } });
      if (res.ok) {
        const kb = (res.bytes_freed / 1024).toFixed(0);
        toast.success(`Usunięto rekord #${res.record_id} (${res.files_removed} plików, ${kb} KB zwolnione)`);
        setConfirmDel(null);
        load();
      } else {
        toast.error(`Nie udało się usunąć: ${res.detail}`);
      }
    } catch (e: any) {
      toast.error(`Nie udało się usunąć: ${e?.message || "błąd"}`);
    } finally {
      setDeletingId(null);
    }
  };

  const getSearchedBy = (r: any): string | null =>
    r?.searched_by ?? r?.criteria?.searched_by ?? r?.meta?.searched_by ?? null;

  const filtered = records
    .filter((r: any) =>
      onlyCompleted ? r.status === "done" || r.status === "new" || !r.status : true,
    )
    .filter((r: any) => {
      if (userFilter === "all") return true;
      if (userFilter === "__none__") return !getSearchedBy(r);
      return getSearchedBy(r) === userFilter;
    });

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between pb-3">
        <CardTitle className="text-base">📋 Search Records</CardTitle>
        <div className="flex items-center gap-2 flex-wrap">
          <Button variant="outline" size="sm" onClick={() => setAnalyzeOpen(true)} className="text-xs gap-1">
            <Brain className="h-3.5 w-3.5" /> Przeanalizuj feedback
          </Button>
          <Select value={userFilter} onValueChange={setUserFilter}>
            <SelectTrigger className="h-8 w-36 text-xs">
              <SelectValue placeholder="Użytkownik" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">👥 Wszyscy</SelectItem>
              {SITE_USERS.map((u) => (
                <SelectItem key={u} value={u}>👤 {u}</SelectItem>
              ))}
              <SelectItem value="__none__">— Bez przypisania</SelectItem>
            </SelectContent>
          </Select>
          <Button
            variant={onlyCompleted ? "default" : "outline"}
            size="sm"
            onClick={() => setOnlyCompleted(!onlyCompleted)}
            className="text-xs"
          >
            {onlyCompleted ? "✅ Tylko ukończone" : "📋 Wszystkie"}
          </Button>
          <Input
            placeholder="Szukaj…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && load()}
            className="h-8 w-48"
          />
          <Select value={String(limit)} onValueChange={(v) => setLimit(Number(v))}>
            <SelectTrigger className="h-8 w-20"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="50">50</SelectItem>
              <SelectItem value="100">100</SelectItem>
              <SelectItem value="200">200</SelectItem>
            </SelectContent>
          </Select>
          <Button variant="outline" size="sm" onClick={load} disabled={loading}>
            {loading ? <Spin /> : <Search className="h-3.5 w-3.5" />}
          </Button>
        </div>
      </CardHeader>
      <CardContent>
        {loading && records.length === 0 ? (
          <div className="flex justify-center py-6"><Spin /></div>
        ) : filtered.length === 0 ? (
          <EmptyState text="Brak rekordów" />
        ) : (
          <div className="max-h-[500px] overflow-auto rounded border">
            <Table>
              <TableHeader className="sticky top-0 bg-card z-10">
                <TableRow>
                  <TableHead>Data</TableHead>
                  <TableHead>Tytuł</TableHead>
                  <TableHead>Klient</TableHead>
                  <TableHead>Zrobione przez</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Info</TableHead>
                  <TableHead className="text-right">Lots</TableHead>
                  <TableHead className="text-right">Czas trwania</TableHead>
                  <TableHead />
                  <TableHead className="text-right">Akcje</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filtered.map((r: any) => {
                  const isRunning = r.status === "running";
                  const isDeleting = deletingId === String(r.id);
                  const searchedBy =
                    r.searched_by ?? r.criteria?.searched_by ?? r.meta?.searched_by ?? null;
                  return (
                    <TableRow key={r.id} className="cursor-pointer" onClick={() => openDetail(r.id)}>
                      <TableCell className="text-xs whitespace-nowrap">{fmtDate(r.created_at)}</TableCell>
                      <TableCell className="max-w-[200px] truncate text-xs">{r.title || "—"}</TableCell>
                      <TableCell className="text-xs">{r.client?.name || r.client || "—"}</TableCell>
                      <TableCell className="text-xs">
                        {searchedBy ? (
                          <Badge variant="secondary" className="text-[10px]">{searchedBy}</Badge>
                        ) : (
                          <span className="text-muted-foreground">—</span>
                        )}
                      </TableCell>
                      <TableCell>{statusBadge(r.status)}</TableCell>
                      <TableCell className="text-xs text-muted-foreground max-w-[200px] truncate">
                        {r.analysis_notice || "—"}
                      </TableCell>
                      <TableCell className="text-right text-xs">{r.collected_count ?? "—"}</TableCell>
                      <TableCell
                        className={`text-right text-xs whitespace-nowrap ${durationColorClass(r.duration_seconds)}`}
                        title={
                          r.duration_seconds != null
                            ? `${Math.round(r.duration_seconds)}s = ${formatDuration(r.duration_seconds)}`
                            : undefined
                        }
                      >
                        {formatDuration(r.duration_seconds)}
                      </TableCell>
                      <TableCell>
                        <Eye className="h-3.5 w-3.5 text-muted-foreground" />
                      </TableCell>
                      <TableCell className="text-right">
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-7 w-7 text-destructive hover:text-destructive hover:bg-destructive/10"
                          disabled={isRunning || isDeleting}
                          title={isRunning ? "Najpierw anuluj scrape" : "Usuń rekord"}
                          onClick={(e) => {
                            e.stopPropagation();
                            setConfirmDel(r);
                          }}
                        >
                          {isDeleting ? <Spin /> : <Trash2 className="h-3.5 w-3.5" />}
                        </Button>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </div>
        )}

        <Dialog
          open={!!detail || !!detailRecordId}
          onOpenChange={(o) => {
            if (!o) {
              setDetail(null);
              setDetailRecordId(null);
            }
          }}
        >
          <DialogContent className="max-w-3xl max-h-[85vh] overflow-auto">
            <DialogHeader>
              <DialogTitle>Szczegóły rekordu {detailRecordId ? `#${detailRecordId}` : ""}</DialogTitle>
            </DialogHeader>
            {detailLoading ? (
              <div className="flex justify-center py-8"><Spin /></div>
            ) : detail && detailRecordId ? (
              <RecordDetailView record={detail} recordId={detailRecordId} />
            ) : null}
          </DialogContent>
        </Dialog>

        <AnalyzeFeedbackDialog open={analyzeOpen} onOpenChange={setAnalyzeOpen} />


        <AlertDialog open={!!confirmDel} onOpenChange={(o) => !o && !deletingId && setConfirmDel(null)}>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>Usunąć wyszukiwanie?</AlertDialogTitle>
              <AlertDialogDescription>
                {confirmDel && (
                  <>
                    Rekord #{confirmDel.id}: <strong>{confirmDel.title || "—"}</strong> z{" "}
                    {fmtDate(confirmDel.created_at)}. Operacja usunie też wszystkie wygenerowane
                    raporty HTML z dysku ({confirmDel.collected_count ?? 0} lotów). Tej akcji nie
                    można cofnąć.
                  </>
                )}
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel disabled={!!deletingId}>Anuluj</AlertDialogCancel>
              <AlertDialogAction
                onClick={(e) => { e.preventDefault(); handleDelete(); }}
                disabled={!!deletingId}
                className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              >
                {deletingId ? "Usuwanie..." : "Usuń"}
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      </CardContent>
    </Card>
  );
}

// ── Jobs Section ──

function JobsSection() {
  const [jobs, setJobs] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState("all");
  const [detail, setDetail] = useState<any>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const fn = useServerFn(listAllJobs);
  const fnDetail = useServerFn(getJobDetails);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fn({ data: { limit: 50 } });
      setJobs(r ?? []);
    } catch {
      toast.error("Nie udało się pobrać jobów");
    } finally {
      setLoading(false);
    }
  }, [fn]);

  useEffect(() => { load(); }, []);

  const filtered = statusFilter === "all" ? jobs : jobs.filter((j: any) => j.status === statusFilter);

  const openDetail = async (id: string) => {
    setDetailLoading(true);
    try {
      const r = await fnDetail({ data: { id } });
      setDetail(r);
    } catch {
      toast.error("Nie udało się pobrać szczegółów joba");
    } finally {
      setDetailLoading(false);
    }
  };

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between pb-3">
        <CardTitle className="text-base">⚙️ Jobs</CardTitle>
        <div className="flex items-center gap-2">
          <Select value={statusFilter} onValueChange={setStatusFilter}>
            <SelectTrigger className="h-8 w-32"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Wszystkie</SelectItem>
              <SelectItem value="done">done</SelectItem>
              <SelectItem value="error">error</SelectItem>
              <SelectItem value="cancelled">cancelled</SelectItem>
              <SelectItem value="interrupted">interrupted</SelectItem>
            </SelectContent>
          </Select>
          <Button variant="outline" size="sm" onClick={load} disabled={loading}>
            {loading ? <Spin /> : <RefreshCw className="h-3.5 w-3.5" />}
          </Button>
        </div>
      </CardHeader>
      <CardContent>
        {loading && jobs.length === 0 ? (
          <div className="flex justify-center py-6"><Spin /></div>
        ) : filtered.length === 0 ? (
          <EmptyState text="Brak jobów" />
        ) : (
          <div className="max-h-[500px] overflow-auto rounded border">
            <Table>
              <TableHeader className="sticky top-0 bg-card z-10">
                <TableRow>
                  <TableHead>ID</TableHead>
                  <TableHead>Created</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Faza</TableHead>
                  <TableHead>Czas</TableHead>
                  <TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
                {filtered.map((j: any) => {
                  const phases = j.phases ?? [];
                  const lastPhase = phases[phases.length - 1];
                  const dur = j.created_at && j.finished_at
                    ? `${Math.round((new Date(j.finished_at).getTime() - new Date(j.created_at).getTime()) / 1000)}s`
                    : "—";
                  return (
                    <TableRow key={j.id} className="cursor-pointer" onClick={() => openDetail(j.id)}>
                      <TableCell className="text-xs font-mono">{String(j.id).slice(0, 8)}</TableCell>
                      <TableCell className="text-xs whitespace-nowrap">{fmtDate(j.created_at)}</TableCell>
                      <TableCell>
                        <Badge variant={j.status === "done" ? "default" : j.status === "error" ? "destructive" : "secondary"} className="text-[10px]">
                          {j.status}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-xs">{lastPhase?.name ?? "—"}</TableCell>
                      <TableCell className="text-xs">{dur}</TableCell>
                      <TableCell><Eye className="h-3.5 w-3.5 text-muted-foreground" /></TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </div>
        )}

        <Dialog open={!!detail} onOpenChange={(o) => !o && setDetail(null)}>
          <DialogContent className="max-w-2xl max-h-[80vh] overflow-auto">
            <DialogHeader>
              <DialogTitle>Szczegóły joba</DialogTitle>
            </DialogHeader>
            {detailLoading ? (
              <div className="flex justify-center py-8"><Spin /></div>
            ) : detail ? (
              <div className="space-y-4">
                {detail.phases && Array.isArray(detail.phases) && (
                  <div>
                    <h4 className="text-sm font-medium mb-2">Phases timeline</h4>
                    <div className="space-y-1">
                      {detail.phases.map((p: any, i: number) => (
                        <div key={i} className="flex items-center gap-2 text-xs">
                          <Badge variant={p.status === "done" ? "default" : "secondary"} className="text-[10px]">{p.status ?? "?"}</Badge>
                          <span className="font-medium">{p.name}</span>
                          {p.duration_s != null && <span className="text-muted-foreground">{p.duration_s}s</span>}
                        </div>
                      ))}
                    </div>
                  </div>
                )}
                <pre className="text-xs bg-muted p-4 rounded overflow-auto max-h-[40vh] whitespace-pre-wrap">
                  {JSON.stringify(detail, null, 2)}
                </pre>
              </div>
            ) : null}
          </DialogContent>
        </Dialog>
      </CardContent>
    </Card>
  );
}

// ── LLM Cache Section ──

function LlmCacheSection() {
  const [items, setItems] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const fn = useServerFn(listLlmCacheEntries);
  const fnDelete = useServerFn(deleteLlmCacheEntry);
  const fnClear = useServerFn(clearLlmCache);
  const fnHtml = useServerFn(fetchAuthHtml);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fn({ data: { limit: 100 } });
      setItems(r ?? []);
    } catch {
      toast.error("Nie udało się pobrać LLM cache");
    } finally {
      setLoading(false);
    }
  }, [fn]);

  useEffect(() => { load(); }, []);

  const handleDelete = async (key: string) => {
    try {
      await fnDelete({ data: { key } });
      toast.success("Wpis usunięty");
      load();
    } catch {
      toast.error("Nie udało się usunąć");
    }
  };

  const handleClearAll = async () => {
    try {
      await fnClear();
      toast.success("Cache wyczyszczony");
      load();
    } catch {
      toast.error("Nie udało się wyczyścić cache");
    }
  };

  const openHtml = async (key: string) => {
    try {
      const html = await fnHtml({ data: { path: `/api/llm-cache/entry/${encodeURIComponent(key)}` } });
      const blob = new Blob([html], { type: "text/html;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      window.open(url, "_blank");
      setTimeout(() => URL.revokeObjectURL(url), 120_000);
    } catch {
      toast.error("Nie udało się otworzyć raportu");
    }
  };

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between pb-3">
        <CardTitle className="text-base">💾 LLM Cache</CardTitle>
        <div className="flex items-center gap-2">
          <Badge variant="secondary" className="text-[10px]">{items.length} wpisów</Badge>
          <AlertDialog>
            <AlertDialogTrigger asChild>
              <Button variant="destructive" size="sm" disabled={items.length === 0}>
                <Trash2 className="h-3.5 w-3.5 mr-1" /> Wyczyść cały cache
              </Button>
            </AlertDialogTrigger>
            <AlertDialogContent>
              <AlertDialogHeader>
                <AlertDialogTitle>Wyczyścić cały LLM cache?</AlertDialogTitle>
                <AlertDialogDescription>
                  Usunie wszystkie {items.length} wpisów. Kolejne raporty będą generowane od nowa (~30s/lot).
                </AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel>Anuluj</AlertDialogCancel>
                <AlertDialogAction onClick={handleClearAll}>Wyczyść</AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
          <Button variant="outline" size="sm" onClick={load} disabled={loading}>
            {loading ? <Spin /> : <RefreshCw className="h-3.5 w-3.5" />}
          </Button>
        </div>
      </CardHeader>
      <CardContent>
        {loading && items.length === 0 ? (
          <div className="flex justify-center py-6"><Spin /></div>
        ) : items.length === 0 ? (
          <EmptyState text="Cache pusty" />
        ) : (
          <div className="max-h-[500px] overflow-auto rounded border">
            <Table>
              <TableHeader className="sticky top-0 bg-card z-10">
                <TableRow>
                  <TableHead>Data</TableHead>
                  <TableHead>Source</TableHead>
                  <TableHead>Lot ID</TableHead>
                  <TableHead>Kind</TableHead>
                  <TableHead>Provider</TableHead>
                  <TableHead className="text-right">Size</TableHead>
                  <TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
                {items.map((it: any) => (
                  <TableRow key={it.cache_key}>
                    <TableCell className="text-xs whitespace-nowrap">{fmtDate(it.generated_at)}</TableCell>
                    <TableCell className="text-xs">{it.source ?? "—"}</TableCell>
                    <TableCell className="text-xs font-mono">{it.lot_id ?? "—"}</TableCell>
                    <TableCell>
                      <Badge variant="outline" className="text-[10px]">{it.kind ?? "—"}</Badge>
                    </TableCell>
                    <TableCell className="text-xs">{it.provider ?? "—"}</TableCell>
                    <TableCell className="text-right text-xs">{it.html_size ? fmtSize(it.html_size / 1024) : "—"}</TableCell>
                    <TableCell className="flex items-center gap-1">
                      <Button variant="ghost" size="icon" className="h-7 w-7" onClick={(e) => { e.stopPropagation(); openHtml(it.cache_key); }}>
                        <Eye className="h-3.5 w-3.5" />
                      </Button>
                      <AlertDialog>
                        <AlertDialogTrigger asChild>
                          <Button variant="ghost" size="icon" className="h-7 w-7 text-destructive" onClick={(e) => e.stopPropagation()}>
                            <Trash2 className="h-3.5 w-3.5" />
                          </Button>
                        </AlertDialogTrigger>
                        <AlertDialogContent>
                          <AlertDialogHeader>
                            <AlertDialogTitle>Usunąć wpis?</AlertDialogTitle>
                            <AlertDialogDescription>Lot {it.lot_id} ({it.kind}) zostanie usunięty z cache.</AlertDialogDescription>
                          </AlertDialogHeader>
                          <AlertDialogFooter>
                            <AlertDialogCancel>Anuluj</AlertDialogCancel>
                            <AlertDialogAction onClick={() => handleDelete(it.cache_key)}>Usuń</AlertDialogAction>
                          </AlertDialogFooter>
                        </AlertDialogContent>
                      </AlertDialog>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ── HTML Cache Section ──

function HtmlCacheSection() {
  const [items, setItems] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [source, setSource] = useState("all");
  const fn = useServerFn(listHtmlCache);
  const fnHtml = useServerFn(fetchAuthHtml);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fn({ data: { source: source === "all" ? undefined : source, limit: 200 } });
      setItems(r ?? []);
    } catch {
      toast.error("Nie udało się pobrać HTML cache");
    } finally {
      setLoading(false);
    }
  }, [fn, source]);

  useEffect(() => { load(); }, [source]);

  const openHtml = async (item: any) => {
    try {
      const path = item.url || `/api/html-cache/${item.source}/${item.filename}`;
      const html = await fnHtml({ data: { path } });
      const blob = new Blob([html], { type: "text/html;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      window.open(url, "_blank");
      setTimeout(() => URL.revokeObjectURL(url), 120_000);
    } catch {
      toast.error("Nie udało się otworzyć strony");
    }
  };

  const copartCount = items.filter((i: any) => i.source === "copart").length;
  const iaaiCount = items.filter((i: any) => i.source === "iaai").length;
  const copartSize = items.filter((i: any) => i.source === "copart").reduce((s: number, i: any) => s + (i.size_kb ?? 0), 0);
  const iaaiSize = items.filter((i: any) => i.source === "iaai").reduce((s: number, i: any) => s + (i.size_kb ?? 0), 0);

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between pb-3">
        <CardTitle className="text-base">🌐 HTML Cache</CardTitle>
        <div className="flex items-center gap-2">
          <Badge variant="secondary" className="text-[10px]">
            {copartCount} copart ({fmtSize(copartSize)}) · {iaaiCount} iaai ({fmtSize(iaaiSize)})
          </Badge>
          <Select value={source} onValueChange={setSource}>
            <SelectTrigger className="h-8 w-28"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Wszystkie</SelectItem>
              <SelectItem value="copart">Copart</SelectItem>
              <SelectItem value="iaai">IAAI</SelectItem>
            </SelectContent>
          </Select>
          <Button variant="outline" size="sm" onClick={load} disabled={loading}>
            {loading ? <Spin /> : <RefreshCw className="h-3.5 w-3.5" />}
          </Button>
        </div>
      </CardHeader>
      <CardContent>
        {loading && items.length === 0 ? (
          <div className="flex justify-center py-6"><Spin /></div>
        ) : items.length === 0 ? (
          <EmptyState text="Cache pusty" />
        ) : (
          <div className="max-h-[500px] overflow-auto rounded border">
            <Table>
              <TableHeader className="sticky top-0 bg-card z-10">
                <TableRow>
                  <TableHead>Modified</TableHead>
                  <TableHead>Source</TableHead>
                  <TableHead>Filename</TableHead>
                  <TableHead className="text-right">Size</TableHead>
                  <TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
                {items.map((it: any, i: number) => (
                  <TableRow key={`${it.source}-${it.filename}-${i}`}>
                    <TableCell className="text-xs whitespace-nowrap">{fmtDate(it.modified_at)}</TableCell>
                    <TableCell>
                      <Badge variant="outline" className="text-[10px]">{it.source}</Badge>
                    </TableCell>
                    <TableCell className="text-xs font-mono max-w-[250px] truncate">{it.filename}</TableCell>
                    <TableCell className="text-right text-xs">{fmtSize(it.size_kb)}</TableCell>
                    <TableCell>
                      <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => openHtml(it)}>
                        <Eye className="h-3.5 w-3.5" />
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ── Model Normalizations Section ──

function NormalizationsSection() {
  const [data, setData] = useState<{ items: any[]; stats?: any } | null>(null);
  const [loading, setLoading] = useState(true);
  const fn = useServerFn(getModelNormalizations);
  const fnDelete = useServerFn(deleteModelNormalization);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fn();
      setData(r ?? { items: [] });
    } catch {
      toast.error("Nie udało się pobrać normalizacji");
    } finally {
      setLoading(false);
    }
  }, [fn]);

  useEffect(() => { load(); }, []);

  const items = data?.items ?? [];
  const stats = data?.stats;

  const handleDelete = async (id: string | number) => {
    try {
      await fnDelete({ data: { id: String(id) } });
      toast.success("Normalizacja usunięta");
      load();
    } catch {
      toast.error("Nie udało się usunąć");
    }
  };

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between pb-3">
        <CardTitle className="text-base">
          🔤 Cache normalizacji modeli
          {stats && (
            <span className="text-xs text-muted-foreground ml-2 font-normal">
              {stats.total ?? items.length} wpisów
              {stats.by_make && ` · ${Object.keys(stats.by_make).join(", ")}`}
            </span>
          )}
        </CardTitle>
        <Button variant="outline" size="sm" onClick={load} disabled={loading}>
          {loading ? <Spin /> : <RefreshCw className="h-3.5 w-3.5" />}
          <span className="ml-1.5">Refresh</span>
        </Button>
      </CardHeader>
      <CardContent>
        {loading && items.length === 0 ? (
          <div className="flex justify-center py-6"><Spin /></div>
        ) : items.length === 0 ? (
          <EmptyState text="Brak normalizacji" />
        ) : (
          <div className="max-h-[500px] overflow-auto rounded border">
            <Table>
              <TableHeader className="sticky top-0 bg-card z-10">
                <TableRow>
                  <TableHead>Make</TableHead>
                  <TableHead>Klient pisze</TableHead>
                  <TableHead>Copart/IAAI</TableHead>
                  <TableHead>Reason (Claude)</TableHead>
                  <TableHead className="text-right">Verified</TableHead>
                  <TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
                {items.map((n: any) => (
                  <TableRow key={n.id}>
                    <TableCell className="text-xs">{n.make}</TableCell>
                    <TableCell className="font-mono text-xs">{n.original_text}</TableCell>
                    <TableCell className="font-semibold text-xs">{n.normalized_model}</TableCell>
                    <TableCell className="text-xs text-muted-foreground max-w-[200px] truncate">{n.reason || "—"}</TableCell>
                    <TableCell className="text-right text-xs">×{n.verified_count ?? 0}</TableCell>
                    <TableCell>
                      <Button size="sm" variant="ghost" className="h-7 w-7 p-0" onClick={() => handleDelete(n.id)}>
                        🗑️
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ── Main Page ──

function DatabasePage() {
  return (
    <div className="min-h-screen bg-background">
      <header className="sticky top-0 z-30 border-b bg-background/95 backdrop-blur">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-4 py-3">
          <div className="flex items-center gap-3">
            <Link
              to="/"
              className="inline-flex items-center gap-1.5 rounded-md border border-border bg-background px-3 py-1.5 text-xs font-medium hover:bg-accent"
            >
              <ArrowLeft className="h-3.5 w-3.5" /> Panel
            </Link>
            <h1 className="text-lg font-semibold flex items-center gap-2">
              <Database className="h-5 w-5" /> Baza danych
            </h1>
          </div>
          <ThemeToggle />
        </div>
      </header>

      <main className="mx-auto max-w-7xl space-y-6 px-4 py-6">
        <OverviewSection />
        <RecordsSection />
        <JobsSection />
        <LlmCacheSection />
        <HtmlCacheSection />
        <NormalizationsSection />
      </main>
    </div>
  );
}
