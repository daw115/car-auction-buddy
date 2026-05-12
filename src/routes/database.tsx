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

// ============================================================
// Lot feedback UI
// ============================================================

type FeedbackVote = "up" | "down";
type FeedbackEntry = { lot_id: string; source: string; vote: FeedbackVote; reason?: string | null };

function getRecordLots(record: any): any[] {
  // Direct shapes (legacy / local DB)
  const direct =
    record?.listings ?? record?.lots ?? record?.collected ?? null;
  if (Array.isArray(direct) && direct.length > 0) return direct;

  // External backend shape: response.all_results / top_recommendations
  // where each item is { lot, analysis, is_top_recommendation, included_in_report }.
  const resp = record?.response ?? record?.result ?? null;
  const candidates: any[] =
    (Array.isArray(resp?.all_results) && resp.all_results) ||
    (Array.isArray(resp?.top_recommendations) && resp.top_recommendations) ||
    (Array.isArray(record?.all_results) && record.all_results) ||
    (Array.isArray(record?.top_recommendations) && record.top_recommendations) ||
    [];

  return candidates.map((entry: any) => {
    const lot = entry?.lot ?? entry;
    // Merge analysis hints onto the lot for downstream rendering.
    return {
      ...lot,
      analysis: entry?.analysis ?? lot?.analysis,
      is_top_recommendation: entry?.is_top_recommendation,
      included_in_report: entry?.included_in_report,
    };
  });
}

function lotKey(lot: any): string {
  const id = String(lot?.lot_id ?? lot?.id ?? "");
  const src = String(lot?.source ?? "copart").toLowerCase();
  return `${src}::${id}`;
}

function RecordDetailView({ record, recordId }: { record: any; recordId: string }) {
  const fnGet = useServerFn(getRecordFeedback);
  const fnSubmit = useServerFn(submitLotFeedback);
  const fnDelete = useServerFn(deleteLotFeedback);

  const [feedback, setFeedback] = useState<Record<string, FeedbackEntry>>({});
  const [loading, setLoading] = useState(true);
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [downModal, setDownModal] = useState<{ lot: any; key: string } | null>(null);
  const [reason, setReason] = useState("");

  const lots = getRecordLots(record);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const r: any = await fnGet({ data: { recordId } });
        if (cancelled) return;
        const map: Record<string, FeedbackEntry> = {};
        for (const f of r?.feedback ?? []) {
          map[`${String(f.source).toLowerCase()}::${f.lot_id}`] = f;
        }
        setFeedback(map);
      } catch {
        if (!cancelled) toast.error("Nie udało się pobrać feedbacku");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [recordId, fnGet]);

  const sendVote = async (lot: any, vote: FeedbackVote, reasonText?: string) => {
    const key = lotKey(lot);
    const lot_id = String(lot?.lot_id ?? lot?.id ?? "");
    const source = (String(lot?.source ?? "copart").toLowerCase() === "iaai" ? "iaai" : "copart") as "copart" | "iaai";
    if (!lot_id) {
      toast.error("Lot bez identyfikatora");
      return;
    }
    const prev = feedback[key];
    setBusyKey(key);
    setFeedback((f) => ({ ...f, [key]: { lot_id, source, vote, reason: reasonText ?? null } }));
    try {
      await fnSubmit({ data: { recordId, lot_id, source, vote, reason: reasonText } });
      toast.success(vote === "up" ? "Polubiono ✓" : "Odrzucono z notatką ✓");
    } catch (e: any) {
      setFeedback((f) => {
        const next = { ...f };
        if (prev) next[key] = prev; else delete next[key];
        return next;
      });
      const status = e?.status;
      if (status === 404) toast.error("Błąd: lot nie znaleziony");
      else toast.error(`Błąd: ${e?.message || "nieznany"}`);
    } finally {
      setBusyKey(null);
    }
  };

  const removeVote = async (lot: any) => {
    const key = lotKey(lot);
    const lot_id = String(lot?.lot_id ?? lot?.id ?? "");
    const source = (String(lot?.source ?? "copart").toLowerCase() === "iaai" ? "iaai" : "copart") as "copart" | "iaai";
    const prev = feedback[key];
    setBusyKey(key);
    setFeedback((f) => {
      const next = { ...f };
      delete next[key];
      return next;
    });
    try {
      await fnDelete({ data: { recordId, lot_id, source } });
      toast.success("Cofnięto ocenę");
    } catch (e: any) {
      if (prev) setFeedback((f) => ({ ...f, [key]: prev }));
      toast.error(`Błąd: ${e?.message || "nieznany"}`);
    } finally {
      setBusyKey(null);
    }
  };

  const handleUp = (lot: any) => {
    const key = lotKey(lot);
    const cur = feedback[key];
    if (cur?.vote === "up") return removeVote(lot);
    return sendVote(lot, "up");
  };

  const handleDown = (lot: any) => {
    const key = lotKey(lot);
    const cur = feedback[key];
    if (cur?.vote === "down") return removeVote(lot);
    setReason("");
    setDownModal({ lot, key });
  };

  const submitDown = async () => {
    if (!downModal) return;
    const trimmed = reason.trim();
    if (trimmed.length < 5) {
      toast.error("Powód musi mieć min. 5 znaków");
      return;
    }
    if (trimmed.length > 500) {
      toast.error("Powód maks. 500 znaków");
      return;
    }
    const lot = downModal.lot;
    setDownModal(null);
    await sendVote(lot, "down", trimmed);
  };

  const upCount = Object.values(feedback).filter((f) => f.vote === "up").length;
  const downCount = Object.values(feedback).filter((f) => f.vote === "down").length;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2 text-xs">
        <Badge variant="outline">Lotów: {lots.length}</Badge>
        <Badge variant="outline" className="text-emerald-600">👍 {upCount}</Badge>
        <Badge variant="outline" className="text-red-600">👎 {downCount}</Badge>
        {record?.title && <Badge variant="secondary">{record.title}</Badge>}
      </div>

      {loading ? (
        <div className="flex justify-center py-6"><Spin /></div>
      ) : lots.length === 0 ? (
        <EmptyState text="Ten rekord nie zawiera lotów" />
      ) : (
        <div className="space-y-1.5">
          {lots.map((lot: any, idx: number) => {
            const key = lotKey(lot);
            const fb = feedback[key];
            const busy = busyKey === key;
            const id = String(lot?.lot_id ?? lot?.id ?? `#${idx}`);
            const source = String(lot?.source ?? "—");
            const title =
              lot?.title ||
              [lot?.year, lot?.make, lot?.model].filter(Boolean).join(" ") ||
              `Lot ${id}`;
            const price = lot?.current_bid_usd ?? lot?.buy_now_price_usd ?? lot?.price_usd;
            const url = lot?.url;
            return (
              <div
                key={`${key}-${idx}`}
                className="flex items-center gap-2 px-3 py-2 rounded border bg-card hover:bg-accent/30 transition-colors"
                title={fb?.reason ? `Powód: ${fb.reason}` : undefined}
              >
                <span className="text-[10px] text-muted-foreground w-6">{idx + 1}.</span>
                <div className="flex-1 min-w-0">
                  <div className="text-xs font-medium truncate">{title}</div>
                  <div className="text-[10px] text-muted-foreground flex items-center gap-2 flex-wrap">
                    <span>{source}</span>
                    <span>#{id}</span>
                    {price != null && <span>${Number(price).toLocaleString()}</span>}
                    {url && (
                      <a
                        href={url}
                        target="_blank"
                        rel="noreferrer"
                        className="underline hover:text-primary"
                        onClick={(e) => e.stopPropagation()}
                      >
                        otwórz
                      </a>
                    )}
                    {fb?.reason && (
                      <span className="italic text-red-600 dark:text-red-400 truncate max-w-[300px]">
                        „{fb.reason}"
                      </span>
                    )}
                  </div>
                </div>
                <Button
                  variant={fb?.vote === "up" ? "default" : "ghost"}
                  size="icon"
                  className={`h-7 w-7 ${fb?.vote === "up" ? "bg-emerald-600 hover:bg-emerald-700 text-white" : "text-muted-foreground hover:text-emerald-600"}`}
                  disabled={busy}
                  onClick={() => handleUp(lot)}
                  title={fb?.vote === "up" ? "Cofnij polubienie" : "Polub"}
                >
                  <ThumbsUp className="h-3.5 w-3.5" />
                </Button>
                <Button
                  variant={fb?.vote === "down" ? "default" : "ghost"}
                  size="icon"
                  className={`h-7 w-7 ${fb?.vote === "down" ? "bg-red-600 hover:bg-red-700 text-white" : "text-muted-foreground hover:text-red-600"}`}
                  disabled={busy}
                  onClick={() => handleDown(lot)}
                  title={fb?.vote === "down" ? "Cofnij odrzucenie" : "Odrzuć"}
                >
                  <ThumbsDown className="h-3.5 w-3.5" />
                </Button>
              </div>
            );
          })}
        </div>
      )}

      <Dialog open={!!downModal} onOpenChange={(o) => !o && setDownModal(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Dlaczego odrzuciłeś ten samochód?</DialogTitle>
          </DialogHeader>
          <Textarea
            placeholder="np. za stary, przebieg, uszkodzenie, cena…"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            rows={4}
            maxLength={500}
          />
          <div className="text-[10px] text-muted-foreground text-right">{reason.length}/500</div>
          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={() => setDownModal(null)}>Anuluj</Button>
            <Button
              variant="destructive"
              onClick={submitDown}
              disabled={reason.trim().length < 5}
            >
              Odrzuć i zapisz
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function AnalyzeFeedbackDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const fn = useServerFn(analyzeFeedback);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<any>(null);

  useEffect(() => {
    if (!open) return;
    setResult(null);
    setLoading(true);
    (async () => {
      try {
        const r = await fn({ data: undefined as any });
        setResult(r);
      } catch (e: any) {
        toast.error(`Analiza nie powiodła się: ${e?.message || "błąd"}`);
        onOpenChange(false);
      } finally {
        setLoading(false);
      }
    })();
  }, [open, fn, onOpenChange]);

  const rec = result?.recommendations ?? {};
  const stats = result?.stats ?? {};

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl max-h-[85vh] overflow-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Brain className="h-4 w-4" /> Analiza feedbacku
          </DialogTitle>
        </DialogHeader>

        {loading ? (
          <div className="flex flex-col items-center gap-2 py-8">
            <Spin />
            <div className="text-xs text-muted-foreground">Analizuję Twoje oceny…</div>
          </div>
        ) : result ? (
          <div className="space-y-5 text-sm">
            {result.summary && (
              <section>
                <h3 className="font-semibold mb-1">Podsumowanie</h3>
                <p className="text-muted-foreground whitespace-pre-wrap">{result.summary}</p>
              </section>
            )}

            <section>
              <h3 className="font-semibold mb-2">Rekomendowane zmiany kryteriów</h3>
              <div className="space-y-2">
                {Array.isArray(rec.preferred_makes) && rec.preferred_makes.length > 0 && (
                  <div>
                    <div className="text-xs text-muted-foreground mb-1">Preferowane marki</div>
                    <div className="flex flex-wrap gap-1">
                      {rec.preferred_makes.map((m: string) => (
                        <Badge key={m} className="bg-emerald-600 hover:bg-emerald-700 text-white">{m}</Badge>
                      ))}
                    </div>
                  </div>
                )}
                {Array.isArray(rec.avoided_damage_types) && rec.avoided_damage_types.length > 0 && (
                  <div>
                    <div className="text-xs text-muted-foreground mb-1">Unikane uszkodzenia</div>
                    <div className="flex flex-wrap gap-1">
                      {rec.avoided_damage_types.map((d: string) => (
                        <Badge key={d} className="bg-red-600 hover:bg-red-700 text-white">{d}</Badge>
                      ))}
                    </div>
                  </div>
                )}
                {rec.preferred_year_min != null && (
                  <div className="text-xs">Min rocznik: <strong>{rec.preferred_year_min}</strong></div>
                )}
                {rec.preferred_max_odometer_mi != null && (
                  <div className="text-xs">
                    Max przebieg: <strong>{Number(rec.preferred_max_odometer_mi).toLocaleString()} mi</strong>
                  </div>
                )}
                {rec.score_threshold != null && (
                  <div className="text-xs">Min score: <strong>{rec.score_threshold}</strong></div>
                )}
                {rec.additional_notes && (
                  <div className="text-xs text-muted-foreground italic">{rec.additional_notes}</div>
                )}
              </div>
            </section>

            <section>
              <h3 className="font-semibold mb-2">Statystyki</h3>
              <div className="flex flex-wrap gap-3 text-xs">
                <Badge variant="outline" className="text-emerald-600">
                  👍 {stats.up ?? 0}
                </Badge>
                <Badge variant="outline" className="text-red-600">
                  👎 {stats.down ?? 0}
                </Badge>
                {stats.avg_score_up != null && (
                  <Badge variant="outline">śr. score 👍: {Number(stats.avg_score_up).toFixed(1)}</Badge>
                )}
                {stats.avg_score_down != null && (
                  <Badge variant="outline">śr. score 👎: {Number(stats.avg_score_down).toFixed(1)}</Badge>
                )}
              </div>
            </section>

            <div className="flex justify-end gap-2 pt-2 border-t">
              <Button variant="outline" onClick={() => onOpenChange(false)}>Zamknij</Button>
              <Button
                onClick={() => {
                  try {
                    sessionStorage.setItem("scrape:prefill_recommendations", JSON.stringify(rec));
                    toast.success("Zapisano kryteria — otwórz formularz wyszukiwania");
                  } catch {
                    toast.error("Nie udało się zapisać kryteriów");
                  }
                  onOpenChange(false);
                }}
              >
                Zastosuj te kryteria w nowym wyszukiwaniu
              </Button>
            </div>
          </div>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}
