import { createFileRoute, Link } from "@tanstack/react-router";
import { useEffect, useMemo, useState, useCallback, useRef } from "react";
import { useServerFn } from "@tanstack/react-start";
import { toast } from "sonner";
import {
  listClients,
  createClient,
  deleteClient,
  listRecords,
  loadRecord,
  saveRecord,
  deleteRecord,
  getConfig,
  updateConfig,
  runAnalysis,
  renderReport,
  runScraperSearch,
  startScraperSearch,
  pollScraperJob,
  cancelScraperJob,
  clearScrapeCache,
  getJobLogs,
  runLotReports,
  getReportBundle,
  logRetryEvent,
} from "@/server/api.functions";
import { addToWatchlist } from "@/server/watchlist.functions";
import type { CarLot, ClientCriteria, AnalyzedLot } from "@/lib/types";
import { LogsPanel } from "@/components/LogsPanel";
import { ThemeToggle } from "@/components/theme-toggle";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { Progress } from "@/components/ui/progress";
import { Card } from "@/components/ui/card";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import {
  Loader2,
  Plus,
  Trash2,
  RefreshCw,
  Settings,
  KeyRound,
  Search,
  Brain,
  FileText,
  Download,
  Save,
  AlertCircle,
  X,
  CheckCircle2,
  Calculator,
  BarChart3,
  Eye,
  RotateCcw,
} from "lucide-react";

export const Route = createFileRoute("/")({
  component: Panel,
});

type ClientRow = { id: string; name: string; contact: string | null; notes: string | null; created_at: string };
type ArtifactsMeta = {
  report_html?: { size: number; generated_at: string };
  mail_html?: { size: number; generated_at: string };
  ai_input?: { size: number; generated_at: string };
  ai_prompt?: { size: number; generated_at: string };
  analysis?: { lots_count: number; generated_at: string };
};
type RecordSummary = {
  id: string;
  client_id: string | null;
  title: string | null;
  status: string;
  created_at: string;
  updated_at: string;
  analysis_status: string | null;
  analysis_started_at: string | null;
  analysis_completed_at: string | null;
  artifacts_meta: ArtifactsMeta | null;
  analysis_error: string | null;
  retry_count: number;
  max_retries: number;
  next_retry_at: string | null;
  last_error_at: string | null;
};
type ConfigEnv = {
  ANTHROPIC_API_KEY: boolean;
  ANTHROPIC_MODEL: string;
  ANTHROPIC_BASE_URL: string;
  SCRAPER_BASE_URL: boolean;
  SCRAPER_API_TOKEN: boolean;
};
type ConfigRow = {
  use_mock_data: boolean;
  ai_analysis_mode: string;
  filter_seller_insurance_only: boolean;
  min_auction_window_hours: number;
  max_auction_window_hours: number;
  collect_all_prefiltered_results: boolean;
  open_all_prefiltered_details: boolean;
};

const DEFAULT_CRITERIA: ClientCriteria = {
  make: "",
  model: "",
  year_from: 2015,
  year_to: 2024,
  budget_usd: 20000,
  max_odometer_mi: 120000,
  excluded_damage_types: ["Flood", "Fire"],
  max_results: 30,
  sources: ["copart", "iaai"],
};

function downloadFile(filename: string, content: string, mime: string) {
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function recommendationBadge(r: string) {
  if (r === "POLECAM") return "bg-[oklch(0.92_0.08_145)] text-[oklch(0.30_0.10_145)]";
  if (r === "RYZYKO") return "bg-[oklch(0.92_0.10_85)] text-[oklch(0.35_0.12_85)]";
  return "bg-[oklch(0.92_0.10_25)] text-[oklch(0.35_0.15_25)]";
}

type ScrapeJobState = {
  status: string;
  jobId?: string;
  startedAt: number;
  progress?: number;
  elapsedMs: number;
  errorMessage?: string;
  errorStep?: string;
  step?: string;
  phase?: string;
  message?: string;
  current?: number;
  total?: number;
};

type AnalysisPhase = "queued" | "analyzing" | "rendering" | "saving" | "done" | "failed" | "cancelled";

type AnalysisJobState = {
  phase: AnalysisPhase;
  startedAt: number;
  elapsedMs: number;
  lotsCount?: number;
  errorMessage?: string;
};

function formatDuration(ms: number): string {
  const s = Math.max(0, Math.floor(ms / 1000));
  const m = Math.floor(s / 60);
  const r = s % 60;
  return m > 0 ? `${m}m ${r}s` : `${r}s`;
}

// Shared color map for phase/step badges — used by ScraperProgress, AnalysisProgress and LogsPanel
const PHASE_BADGE_COLORS: Record<string, string> = {
  // scraper phases
  queued:            "bg-muted text-muted-foreground",
  starting:          "bg-[oklch(0.92_0.06_250)] text-[oklch(0.35_0.12_250)]",
  initializing:      "bg-[oklch(0.92_0.06_250)] text-[oklch(0.35_0.12_250)]",
  running:           "bg-[oklch(0.90_0.08_250)] text-[oklch(0.30_0.14_250)]",
  scraping:          "bg-[oklch(0.90_0.08_280)] text-[oklch(0.30_0.14_280)]",
  scraping_list:     "bg-[oklch(0.90_0.08_280)] text-[oklch(0.30_0.14_280)]",
  scraping_details:  "bg-[oklch(0.88_0.10_280)] text-[oklch(0.28_0.16_280)]",
  enriching:         "bg-[oklch(0.90_0.08_60)] text-[oklch(0.32_0.12_60)]",
  parsing:           "bg-[oklch(0.90_0.08_200)] text-[oklch(0.32_0.12_200)]",
  // analysis phases
  analyzing:         "bg-[oklch(0.88_0.10_280)] text-[oklch(0.28_0.16_280)]",
  rendering:         "bg-[oklch(0.90_0.08_60)] text-[oklch(0.32_0.12_60)]",
  saving:            "bg-[oklch(0.90_0.08_200)] text-[oklch(0.32_0.12_200)]",
  // terminal
  done:              "bg-[oklch(0.92_0.08_145)] text-[oklch(0.30_0.10_145)]",
  completed:         "bg-[oklch(0.92_0.08_145)] text-[oklch(0.30_0.10_145)]",
  finished:          "bg-[oklch(0.92_0.08_145)] text-[oklch(0.30_0.10_145)]",
  failed:            "bg-destructive/15 text-destructive",
  error:             "bg-destructive/15 text-destructive",
  cancelled:         "bg-muted text-muted-foreground",
};

function PhaseBadge({ phase, active }: { phase: string; active: boolean }) {
  const color = PHASE_BADGE_COLORS[phase] ?? "bg-muted text-muted-foreground";
  return (
    <span
      className={`inline-flex items-center rounded px-1.5 py-0.5 text-[10px] ${color} ${
        active ? "font-bold ring-1 ring-current/30" : "font-normal opacity-70"
      }`}
    >
      {phase}
    </span>
  );
}

function ScraperProgress({
  job,
  onCancel,
  onDownloadLogs,
  onRerun,
  rerunDisabled,
}: {
  job: ScrapeJobState;
  onCancel?: () => void;
  onDownloadLogs?: (jobId: string, format: "json" | "csv") => void;
  onRerun?: () => void;
  rerunDisabled?: boolean;
}) {
  const ASSUMED_TOTAL_MS = 90_000;
  const isDone = job.status === "done";
  const isFailed = job.status === "failed" || job.status === "error";
  const isCancelled = job.status === "cancelled";
  const isFinal = isDone || isFailed || isCancelled;
  const pct =
    typeof job.progress === "number"
      ? Math.min(100, Math.max(0, Math.round(job.progress * 100)))
      : isDone
        ? 100
        : Math.min(95, Math.round((job.elapsedMs / ASSUMED_TOTAL_MS) * 100));

  // Compute fractional progress from explicit progress OR current/total
  const effectiveProgress =
    typeof job.progress === "number" && job.progress > 0
      ? job.progress
      : typeof job.current === "number" && typeof job.total === "number" && job.total > 0
        ? job.current / job.total
        : null;

  const etaMs =
    isFinal
      ? 0
      : effectiveProgress !== null && effectiveProgress > 0
        ? Math.max(0, job.elapsedMs / effectiveProgress - job.elapsedMs)
        : Math.max(0, ASSUMED_TOTAL_MS - job.elapsedMs);

  const statusLabel: Record<string, string> = {
    queued: "W kolejce",
    starting: "Uruchamianie",
    initializing: "Inicjalizacja",
    running: "Pobieranie ofert",
    scraping: "Scrapowanie listy",
    scraping_list: "Scrapowanie listy",
    scraping_details: "Pobieranie szczegółów ofert",
    enriching: "Wzbogacanie danych",
    parsing: "Parsowanie wyników",
    done: "Zakończono",
    completed: "Zakończono",
    finished: "Zakończono",
    failed: "Błąd",
    error: "Błąd",
    cancelled: "Anulowano",
  };

  const phaseLabel: Record<string, string> = {
    list: "Lista wyników",
    details: "Szczegóły ofert",
    enrich: "Wzbogacanie",
    parse: "Parsowanie",
    save: "Zapis",
  };

  // Compose a human-readable subtitle from phase / step / message / counter.
  const subtitleParts: string[] = [];
  if (job.phase) subtitleParts.push(phaseLabel[job.phase] ?? job.phase);
  if (job.step && job.step !== job.phase) subtitleParts.push(job.step);
  if (typeof job.current === "number" && typeof job.total === "number" && job.total > 0) {
    subtitleParts.push(`${job.current} z ${job.total}`);
  }
  const subtitle = job.message?.trim() || subtitleParts.join(" · ");

  const variant = isFailed
    ? "bg-destructive/10 border-destructive/30"
    : isCancelled
      ? "bg-muted border-border"
      : isDone
        ? "bg-[oklch(0.95_0.05_145)] border-[oklch(0.80_0.10_145)]"
        : "bg-muted border-border";

  return (
    <div className={`rounded-md border px-3 py-2 space-y-2 ${variant}`}>
      <div className="flex items-center justify-between text-xs gap-2">
        <div className="flex items-center gap-2 min-w-0">
          {!isFinal && <Loader2 className="h-3.5 w-3.5 animate-spin shrink-0" />}
          {isFailed && <AlertCircle className="h-3.5 w-3.5 text-destructive shrink-0" />}
          <span className="font-medium truncate">
            {statusLabel[job.status] ?? job.status}
          </span>
          {job.jobId && (
            <span className="font-mono text-muted-foreground">#{job.jobId.slice(0, 8)}</span>
          )}
        </div>
        <div className="flex items-center gap-3 text-muted-foreground shrink-0">
          <span>Czas: {formatDuration(job.elapsedMs)}</span>
          {!isFinal && (
            <span title={effectiveProgress !== null ? `Na podstawie postępu ${Math.round(effectiveProgress * 100)}%` : "Szacunkowe (brak danych o postępie)"}>
              ETA: ~{formatDuration(etaMs)}
            </span>
          )}
          <span className="font-medium text-foreground">{pct}%</span>
          {!isFinal && onCancel && (
            <Button
              size="sm"
              variant="outline"
              className="h-6 px-2 text-xs"
              onClick={() => { if (confirm("Czy na pewno chcesz anulować ten job?")) onCancel(); }}
            >
              <X className="h-3 w-3 mr-1" />
              Anuluj
            </Button>
          )}
          {job.jobId && onDownloadLogs && (
            <>
              <Button
                size="sm"
                variant="outline"
                className="h-6 px-2 text-xs"
                onClick={() => onDownloadLogs(job.jobId!, "json")}
                title="Pobierz logi jako JSON"
              >
                <Download className="h-3 w-3 mr-1" />
                JSON
              </Button>
              <Button
                size="sm"
                variant="outline"
                className="h-6 px-2 text-xs"
                onClick={() => onDownloadLogs(job.jobId!, "csv")}
                title="Pobierz logi jako CSV"
              >
                <Download className="h-3 w-3 mr-1" />
                CSV
              </Button>
            </>
          )}
          {isFinal && onRerun && (
            <Button
              size="sm"
              variant="outline"
              className="h-6 px-2 text-xs"
              onClick={onRerun}
              disabled={rerunDisabled}
              title="Uruchom nowy job z tymi samymi kryteriami klienta"
            >
              <RotateCcw className="h-3 w-3 mr-1" />
              Uruchom ponownie
            </Button>
          )}
        </div>
      </div>
      <Progress value={pct} className="h-1.5" />
      {/* Phase pipeline badges — show last reached phase on failure */}
      {(() => {
        const scraperPhases = ["queued", "running", "scraping_list", "scraping_details", "enriching", "parsing", "done"];
        const currentPhaseKey = job.status;
        const currentIdx = scraperPhases.indexOf(currentPhaseKey);

        if (isFailed) {
          // Show pipeline with the last reached phase highlighted in red
          const lastPhase = job.phase ?? job.step ?? job.status;
          const lastIdx = scraperPhases.indexOf(lastPhase);
          return (
            <div className="space-y-1.5">
              <div className="flex flex-wrap items-center gap-1">
                {scraperPhases.map((p, i) => {
                  const reached = lastIdx >= 0 ? i <= lastIdx : false;
                  const failedAt = lastIdx >= 0 && i === lastIdx;
                  return (
                    <span
                      key={p}
                      className={`inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-medium ${
                        failedAt
                          ? "bg-destructive/20 text-destructive ring-1 ring-destructive/30"
                          : reached
                            ? "bg-muted text-muted-foreground line-through"
                            : "bg-muted/50 text-muted-foreground/50"
                      }`}
                    >
                      {statusLabel[p] ?? p}
                    </span>
                  );
                })}
              </div>
              <div className="text-[11px] text-destructive flex items-center gap-1">
                <AlertCircle className="h-3 w-3 shrink-0" />
                Zatrzymano na etapie: <span className="font-medium">{statusLabel[lastPhase] ?? phaseLabel[lastPhase] ?? lastPhase}</span>
              </div>
            </div>
          );
        }

        if (!isCancelled) {
          return (
            <div className="flex flex-wrap items-center gap-1">
              {scraperPhases.map((p, i) => (
                <PhaseBadge key={p} phase={statusLabel[p] ?? p} active={i === currentIdx || (isDone && p === "done")} />
              ))}
            </div>
          );
        }
        return null;
      })()}
      {!isFinal && subtitle && (
        <div className="text-[11px] text-muted-foreground leading-snug">
          {subtitle}
        </div>
      )}
      {isFailed && job.errorMessage && (
        <div className="rounded border border-destructive/30 bg-destructive/5 px-2 py-1.5 text-xs space-y-1">
          <div className="font-medium text-destructive">
            {humanizeError(job.errorMessage)}
          </div>
          {job.errorMessage !== humanizeError(job.errorMessage) && (
            <details className="text-[11px] text-muted-foreground">
              <summary className="cursor-pointer hover:text-foreground">Szczegóły techniczne</summary>
              <pre className="font-mono text-foreground break-words whitespace-pre-wrap mt-1">{job.errorMessage}</pre>
            </details>
          )}
        </div>
      )}
    </div>
  );
}

function AnalysisProgress({ job }: { job: AnalysisJobState }) {
  const isFinal = job.phase === "done" || job.phase === "failed" || job.phase === "cancelled";

  const analysisPhases: AnalysisPhase[] = ["queued", "analyzing", "rendering", "saving", "done"];
  const phaseLabels: Record<AnalysisPhase, string> = {
    queued: "W kolejce",
    analyzing: "Analiza AI",
    rendering: "Raport HTML",
    saving: "Zapis do bazy",
    done: "Zakończono",
    failed: "Błąd",
    cancelled: "Anulowano",
  };

  const phaseProgress: Record<AnalysisPhase, number> = {
    queued: 5,
    analyzing: 40,
    rendering: 75,
    saving: 90,
    done: 100,
    failed: 0,
    cancelled: 0,
  };

  const pct = phaseProgress[job.phase] ?? 0;

  const variant = job.phase === "failed"
    ? "bg-destructive/10 border-destructive/30"
    : job.phase === "cancelled"
      ? "bg-muted border-border"
      : job.phase === "done"
        ? "bg-[oklch(0.95_0.05_145)] border-[oklch(0.80_0.10_145)]"
        : "bg-muted border-border";

  return (
    <div className={`rounded-md border px-3 py-2 space-y-2 ${variant}`}>
      <div className="flex items-center justify-between text-xs gap-2">
        <div className="flex items-center gap-2 min-w-0">
          {!isFinal && <Loader2 className="h-3.5 w-3.5 animate-spin shrink-0" />}
          {job.phase === "failed" && <AlertCircle className="h-3.5 w-3.5 text-destructive shrink-0" />}
          {job.phase === "cancelled" && <X className="h-3.5 w-3.5 text-muted-foreground shrink-0" />}
          {job.phase === "done" && <CheckCircle2 className="h-3.5 w-3.5 text-[oklch(0.50_0.15_145)] shrink-0" />}
          <span className="font-medium truncate">
            {phaseLabels[job.phase]}
          </span>
          {job.lotsCount != null && (
            <span className="text-muted-foreground">({job.lotsCount} lotów)</span>
          )}
        </div>
        <div className="flex items-center gap-3 text-muted-foreground shrink-0">
          <span>Czas: {formatDuration(job.elapsedMs)}</span>
          {!isFinal && <span className="font-medium text-foreground">{pct}%</span>}
        </div>
      </div>
      <Progress value={pct} className="h-1.5" />
      {/* Phase pipeline badges */}
      <div className="flex flex-wrap items-center gap-1">
        {(job.phase === "failed"
          ? [job.phase as AnalysisPhase]
          : analysisPhases
        ).map((p) => (
          <PhaseBadge key={p} phase={phaseLabels[p] ?? p} active={p === job.phase} />
        ))}
      </div>
      {job.phase === "failed" && job.errorMessage && (
        <div className="rounded border border-destructive/30 bg-destructive/5 px-2 py-1.5 text-xs">
          <div className="font-medium text-destructive mb-0.5">Szczegóły błędu:</div>
          <div className="font-mono text-foreground break-words whitespace-pre-wrap">
            {job.errorMessage}
          </div>
        </div>
      )}
    </div>
  );
}

function Panel() {
  // ---- server fn handles
  const fnListClients = useServerFn(listClients);
  const fnCreateClient = useServerFn(createClient);
  const fnDeleteClient = useServerFn(deleteClient);
  const fnListRecords = useServerFn(listRecords);
  const fnLoadRecord = useServerFn(loadRecord);
  const fnSaveRecord = useServerFn(saveRecord);
  const fnDeleteRecord = useServerFn(deleteRecord);
  const fnGetConfig = useServerFn(getConfig);
  const fnUpdateConfig = useServerFn(updateConfig);
  const fnRunAnalysis = useServerFn(runAnalysis);
  const fnRenderReport = useServerFn(renderReport);
  const fnRunScraper = useServerFn(runScraperSearch);
  const fnStartScraper = useServerFn(startScraperSearch);
  const fnPollScraper = useServerFn(pollScraperJob);
  const fnCancelScraper = useServerFn(cancelScraperJob);
  const fnGetJobLogs = useServerFn(getJobLogs);
  const fnClearCache = useServerFn(clearScrapeCache);
  const fnLogRetryEvent = useServerFn(logRetryEvent);

  async function clearCacheAll() {
    if (!confirm("Wyczyścić cały cache wyników wyszukiwań?")) return;
    try {
      await fnClearCache({ data: {} });
      toast.success("Cache wyczyszczony");
    } catch (e) {
      toast.error(`Błąd: ${(e as Error).message}`);
    }
  }
  const fnRunLotReports = useServerFn(runLotReports);
  const fnGetReportBundle = useServerFn(getReportBundle);
  const fnAddWatch = useServerFn(addToWatchlist);

  async function downloadReportBundle(recordId: string) {
    try {
      const r = (await fnGetReportBundle({ data: { recordId } })) as {
        filename: string;
        base64: string;
        size: number;
      };
      const bin = atob(r.base64);
      const bytes = new Uint8Array(bin.length);
      for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
      const url = URL.createObjectURL(new Blob([bytes], { type: "application/zip" }));
      const a = document.createElement("a");
      a.href = url;
      a.download = r.filename;
      a.click();
      URL.revokeObjectURL(url);
      toast.success(`Pobrano ${r.filename} (${(r.size / 1024).toFixed(1)} KB)`);
    } catch (e) {
      toast.error(`Pobranie raportu nie powiodło się: ${(e as Error).message}`);
    }
  }

  async function downloadRecordArtifact(
    recordId: string,
    field: "report_html" | "ai_input" | "ai_prompt",
  ) {
    try {
      const row = (await fnLoadRecord({ data: { id: recordId } })) as Record<string, unknown>;
      const value = row[field];
      if (!value) {
        toast.error("Ten artefakt nie jest jeszcze dostępny dla tego rekordu.");
        return;
      }
      const filenameMap: Record<string, { name: string; mime: string }> = {
        report_html: { name: `report-${recordId.slice(0, 8)}.html`, mime: "text/html" },
        ai_input: { name: `ai-input-${recordId.slice(0, 8)}.json`, mime: "application/json" },
        ai_prompt: { name: `ai-prompt-${recordId.slice(0, 8)}.txt`, mime: "text/plain" },
      };
      const { name, mime } = filenameMap[field];
      const content = typeof value === "string" ? value : JSON.stringify(value, null, 2);
      downloadFile(name, content, mime);
      toast.success(`Pobrano ${name}`);
    } catch (e) {
      toast.error(`Pobranie nie powiodło się: ${(e as Error).message}`);
    }
  }

  async function downloadRecordStatusJson(recordId: string) {
    try {
      const row = (await fnLoadRecord({ data: { id: recordId } })) as Record<string, unknown>;
      const statusPayload = {
        id: row.id,
        title: row.title,
        status: row.status,
        analysis_status: row.analysis_status,
        analysis_error: row.analysis_error,
        analysis_started_at: row.analysis_started_at,
        analysis_completed_at: row.analysis_completed_at,
        retry_count: row.retry_count,
        max_retries: row.max_retries,
        next_retry_at: row.next_retry_at,
        last_error_at: row.last_error_at,
        artifacts_meta: row.artifacts_meta,
        created_at: row.created_at,
        updated_at: row.updated_at,
      };
      const name = `status-${recordId.slice(0, 8)}.json`;
      downloadFile(name, JSON.stringify(statusPayload, null, 2), "application/json");
      toast.success(`Pobrano ${name}`);
    } catch (e) {
      toast.error(`Pobranie nie powiodło się: ${(e as Error).message}`);
    }
  }

  const watchLot = async (a: AnalyzedLot) => {
    try {
      await fnAddWatch({
        data: {
          client_id: activeClientId ?? null,
          source: a.lot.source ?? null,
          lot_id: a.lot.lot_id ?? null,
          url: (a.lot as any).url ?? null,
          title: `${a.lot.year ?? ""} ${a.lot.make ?? ""} ${a.lot.model ?? ""}`.trim(),
          make: a.lot.make ?? null,
          model: a.lot.model ?? null,
          year: a.lot.year ?? null,
          vin: (a.lot as any).vin ?? null,
          current_bid_usd: a.lot.current_bid_usd ?? null,
          buy_now_usd: (a.lot as any).buy_now_usd ?? null,
          score: a.analysis.score,
          category: a.analysis.recommendation,
          notes: a.analysis.client_description_pl ?? null,
          snapshot: a as any,
        },
      });
      toast.success("Dodano do watchlist");
    } catch (e: any) {
      toast.error(e?.message ?? "Błąd dodawania");
    }
  };

  // ---- state
  const [clients, setClients] = useState<ClientRow[]>([]);
  const [records, setRecords] = useState<RecordSummary[]>([]);
  const [config, setConfig] = useState<ConfigRow | null>(null);
  const [env, setEnv] = useState<ConfigEnv | null>(null);

  const [activeClientId, setActiveClientId] = useState<string | null>(null);
  const [activeRecordId, setActiveRecordId] = useState<string | null>(null);

  const [criteria, setCriteria] = useState<ClientCriteria>(DEFAULT_CRITERIA);
  const [listings, setListings] = useState<CarLot[]>([]);
  const [listingsRaw, setListingsRaw] = useState<string>("");
  const [analysis, setAnalysis] = useState<AnalyzedLot[] | null>(null);
  const [aiInput, setAiInput] = useState<unknown>(null);
  const [aiPrompt, setAiPrompt] = useState<string>("");
  const [reportHtml, setReportHtml] = useState<string>("");
  const [mailHtml, setMailHtml] = useState<string>("");

  const [busy, setBusy] = useState<string | null>(null);

  // Retry state for analysis
  const currentRetryRef = useRef(0);
  const maxRetriesRef = useRef(3);
  const autoRetryTimerRef = useRef<number | null>(null);

  // Scraper job progress — with localStorage persistence for page reload recovery
  const SCRAPE_JOB_STORAGE_KEY = "car-finder:active-scrape-job";
  const [scrapeJob, setScrapeJob] = useState<ScrapeJobState | null>(null);

  function persistScrapeJob(jobId: string, cacheKey: string, criteria: ClientCriteria) {
    try {
      localStorage.setItem(SCRAPE_JOB_STORAGE_KEY, JSON.stringify({ jobId, cacheKey, criteria, startedAt: Date.now() }));
    } catch { /* quota exceeded etc. */ }
  }

  function clearPersistedScrapeJob() {
    try { localStorage.removeItem(SCRAPE_JOB_STORAGE_KEY); } catch { /* noop */ }
  }

  // AI analysis progress
  const [analysisJob, setAnalysisJob] = useState<AnalysisJobState | null>(null);

  // Tick elapsed every 1s while analysis is active
  useEffect(() => {
    if (!analysisJob || analysisJob.phase === "done" || analysisJob.phase === "failed") return;
    const t = setInterval(() => {
      setAnalysisJob((s) => (s ? { ...s, elapsedMs: Date.now() - s.startedAt } : s));
    }, 1000);
    return () => clearInterval(t);
  }, [analysisJob?.phase, analysisJob?.startedAt]);

  // Context for the background poller
  const scrapeContextRef = useRef<{
    jobId: string;
    cacheKey: string;
    criteria: ClientCriteria;
  } | null>(null);

  const TERMINAL_STATUSES = ["done", "completed", "finished", "success", "complete", "failed", "error", "cancelled"];

  // Background poller: ticks elapsed + polls backend every 2s, pauses on terminal state
  useEffect(() => {
    if (!scrapeJob) return;
    if (TERMINAL_STATUSES.includes(scrapeJob.status)) return;

    const ctx = scrapeContextRef.current;
    let polling = false;

    const POLL_TIMEOUT_MS = 5 * 60 * 1000;

    const t = setInterval(async () => {
      // Always tick elapsed
      const elapsed = Date.now() - (scrapeJob?.startedAt ?? Date.now());
      setScrapeJob((s) => (s ? { ...s, elapsedMs: Date.now() - s.startedAt } : s));

      // Timeout after 5 min
      if (elapsed > POLL_TIMEOUT_MS) {
        setScrapeJob((s) =>
          s ? { ...s, status: "failed", errorMessage: "Timeout – brak odpowiedzi po 5 min", elapsedMs: Date.now() - s.startedAt } : s,
        );
        scrapeContextRef.current = null;
        clearPersistedScrapeJob();
        setBusy(null);
        toast.error("Timeout scrapera (5 min)");
        return;
      }

      // Poll backend if we have a jobId and not already mid-request
      if (!ctx?.jobId || polling || cancelRequestedRef.current) return;
      polling = true;
      try {
        const p = (await fnPollScraper({ data: { jobId: ctx.jobId, cacheKey: ctx.cacheKey, criteria: ctx.criteria } })) as {
          status: string;
          listings?: CarLot[];
          error?: string;
          progress?: number;
          step?: string;
          phase?: string;
          message?: string;
          current?: number;
          total?: number;
        };

        const DONE = ["done", "completed", "finished", "success", "complete"];
        if (DONE.includes(p.status) || (typeof p.progress === "number" && p.progress >= 1.0)) {
          const result = Array.isArray(p.listings) ? p.listings : [];
          setScrapeJob((s) =>
            s ? { ...s, status: "done", progress: 1, elapsedMs: Date.now() - s.startedAt } : s,
          );
          setListings(result);
          setListingsRaw(JSON.stringify(result, null, 2));
          toast.success(`Scraper zwrócił ${result.length} lotów`);
          setBusy(null);
           scrapeContextRef.current = null;
           clearPersistedScrapeJob();
        } else if (["error", "failed"].includes(p.status)) {
          const errMsg = p.error ?? "Job failed (brak szczegółów z backendu)";
          setScrapeJob((s) =>
            s
              ? { ...s, status: "failed", elapsedMs: Date.now() - s.startedAt, errorMessage: errMsg, errorStep: p.status }
              : s,
          );
          toast.error(errMsg);
          setBusy(null);
           scrapeContextRef.current = null;
           clearPersistedScrapeJob();
        } else {
          setScrapeJob((s) =>
            s
              ? {
                  ...s,
                  status: p.status,
                  progress: p.progress,
                  step: p.step,
                  phase: p.phase,
                  message: p.message,
                  current: p.current,
                  total: p.total,
                  elapsedMs: Date.now() - s.startedAt,
                }
              : s,
          );
        }
      } catch {
        // transient error — keep polling
      } finally {
        polling = false;
      }
    }, 2000);

    return () => clearInterval(t);
  }, [scrapeJob?.status, scrapeJob?.startedAt]);

  // Cancellation flag for the current scrape loop
  const cancelRequestedRef = useRef(false);

  // Restore active scrape job from localStorage on mount
  useEffect(() => {
    try {
      const raw = localStorage.getItem(SCRAPE_JOB_STORAGE_KEY);
      if (!raw) return;
      const saved = JSON.parse(raw) as { jobId: string; cacheKey: string; criteria: ClientCriteria; startedAt: number };
      if (!saved.jobId) { clearPersistedScrapeJob(); return; }
      // Resume polling by restoring context + UI state
      scrapeContextRef.current = { jobId: saved.jobId, cacheKey: saved.cacheKey, criteria: saved.criteria };
      setScrapeJob({ status: "running", jobId: saved.jobId, startedAt: saved.startedAt, elapsedMs: Date.now() - saved.startedAt });
      setCriteria((c) => ({ ...c, ...saved.criteria }));
      setBusy("scraper");
      cancelRequestedRef.current = false;
      toast.info("Wznowiono śledzenie aktywnego joba scrapera");
    } catch { clearPersistedScrapeJob(); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function cancelScrape() {
    if (!scrapeJob?.jobId) {
      cancelRequestedRef.current = true;
      scrapeContextRef.current = null;
      clearPersistedScrapeJob();
      setScrapeJob((s) => (s ? { ...s, status: "cancelled" } : s));
      setBusy(null);
      await persistCancelledStatus();
      toast.message("Anulowano lokalnie");
      return;
    }
    cancelRequestedRef.current = true;
    try {
      await fnCancelScraper({
        data: {
          jobId: scrapeJob.jobId,
          clientId: activeClientId ?? undefined,
          recordId: activeRecordId ?? undefined,
        },
      });
      scrapeContextRef.current = null;
      clearPersistedScrapeJob();
      setScrapeJob((s) => (s ? { ...s, status: "cancelled" } : s));
      setBusy(null);
      await persistCancelledStatus();
      toast.success("Wyszukiwanie anulowane");
    } catch (e) {
      toast.error(`Błąd anulowania: ${(e as Error).message}`);
    }
  }

  async function persistCancelledStatus() {
    if (!activeClient && !activeRecordId) return;
    try {
      const now = new Date().toISOString();
      const row = (await fnSaveRecord({
        data: {
          id: activeRecordId ?? undefined,
          client_id: activeClient?.id ?? activeClientId ?? undefined,
          title: `${criteria.make} ${criteria.model || ""}`.trim(),
          status: "draft",
          criteria,
          listings,
          analysis_status: "cancelled",
          analysis_completed_at: now,
          analysis_error: "Anulowano przez użytkownika",
          retry_count: 0,
          next_retry_at: null,
          last_error_at: now,
        },
      })) as unknown as { id: string };
      if (!activeRecordId) setActiveRecordId(row.id);
      if (activeClient) await refreshRecords(activeClient.id);
    } catch { /* best-effort */ }
  }

  async function downloadJobLogs(jobId: string, format: "json" | "csv" = "json") {
    const t = toast.loading("Pobieranie logów...");
    try {
      const r = (await fnGetJobLogs({ data: { jobId } })) as {
        jobId: string;
        logs: Array<{
          id: string;
          created_at: string;
          level: string;
          step: string | null;
          message: string;
          details: unknown;
          source: "local" | "scraper";
        }>;
        local_error: string | null;
        scraper_error: string | null;
      };

      let blob: Blob;
      let filename: string;

      if (format === "csv") {
        const header = "timestamp,level,step,source,message,details";
        const escCsv = (v: string) => `"${(v ?? "").replace(/"/g, '""')}"`;
        const rows = r.logs.map((l) =>
          [l.created_at, l.level, l.step ?? "", l.source, escCsv(l.message), escCsv(typeof l.details === "string" ? l.details : JSON.stringify(l.details ?? ""))].join(","),
        );
        blob = new Blob([header + "\n" + rows.join("\n")], { type: "text/csv" });
        filename = `scraper-job-${jobId}-logs.csv`;
      } else {
        blob = new Blob([JSON.stringify(r, null, 2)], { type: "application/json" });
        filename = `scraper-job-${jobId}-logs.json`;
      }

      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      toast.success(`Pobrano ${r.logs.length} wpisów logów (${format.toUpperCase()})`, { id: t });
    } catch (e) {
      toast.error(`Błąd: ${(e as Error).message}`, { id: t });
    }
  }
  const [newName, setNewName] = useState("");
  const [newContact, setNewContact] = useState("");
  const [newNotes, setNewNotes] = useState("");

  // ---- loaders
  const refreshClients = useCallback(async () => {
    try {
      const c = (await fnListClients()) as ClientRow[];
      setClients(c);
    } catch (e) {
      toast.error(`Klienci: ${(e as Error).message}`);
    }
  }, [fnListClients]);

  const refreshRecords = useCallback(
    async (clientId?: string | null) => {
      try {
        const r = (await fnListRecords({ data: { clientId: clientId ?? undefined } })) as RecordSummary[];
        setRecords(r);
      } catch (e) {
        toast.error(`Rekordy: ${(e as Error).message}`);
      }
    },
    [fnListRecords],
  );

  const refreshConfig = useCallback(async () => {
    try {
      const r = (await fnGetConfig()) as { config: ConfigRow; env: ConfigEnv };
      setConfig(r.config);
      setEnv(r.env);
    } catch (e) {
      toast.error(`Konfiguracja: ${(e as Error).message}`);
    }
  }, [fnGetConfig]);

  useEffect(() => {
    void refreshClients();
    void refreshRecords(null);
    void refreshConfig();
  }, [refreshClients, refreshRecords, refreshConfig]);

  useEffect(() => {
    void refreshRecords(activeClientId);
  }, [activeClientId, refreshRecords]);

  const activeClient = useMemo(
    () => clients.find((c) => c.id === activeClientId) ?? null,
    [clients, activeClientId],
  );

  // ---- actions
  async function addClient() {
    if (!newName.trim()) {
      toast.error("Nazwa klienta jest wymagana");
      return;
    }
    setBusy("client");
    try {
      const row = (await fnCreateClient({
        data: { name: newName.trim(), contact: newContact.trim() || null, notes: newNotes.trim() || null },
      })) as ClientRow;
      setClients((cs) => [row, ...cs]);
      setActiveClientId(row.id);
      setNewName("");
      setNewContact("");
      setNewNotes("");
      toast.success("Klient dodany");
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function removeClient(id: string) {
    if (!confirm("Usunąć klienta i wszystkie jego rekordy?")) return;
    try {
      await fnDeleteClient({ data: { id } });
      setClients((cs) => cs.filter((c) => c.id !== id));
      if (activeClientId === id) setActiveClientId(null);
      toast.success("Usunięto");
    } catch (e) {
      toast.error((e as Error).message);
    }
  }

  function parseListingsFromText() {
    const text = listingsRaw.trim();
    if (!text) {
      setListings([]);
      return;
    }
    try {
      const parsed = JSON.parse(text);
      if (!Array.isArray(parsed)) throw new Error("JSON musi być tablicą obiektów lotów.");
      setListings(parsed as CarLot[]);
      toast.success(`Wczytano ${parsed.length} lotów z JSON`);
    } catch (e) {
      toast.error(`Błąd JSON: ${(e as Error).message}`);
    }
  }

  async function callScraper() {
    if (!env?.SCRAPER_BASE_URL) {
      toast.error("SCRAPER_BASE_URL nie jest ustawiony.");
      return;
    }
    if (!criteria.make.trim()) {
      toast.error("Marka jest wymagana.");
      return;
    }
    setBusy("scraper");
    cancelRequestedRef.current = false;
    const startedAt = Date.now();
    setScrapeJob({ status: "queued", startedAt, elapsedMs: 0 });
    try {
      const start = (await fnStartScraper({
        data: { criteria, clientId: activeClientId ?? undefined, recordId: activeRecordId ?? undefined },
      })) as
        | { mode: "sync"; listings: CarLot[]; source: string; cache_hit?: boolean; cache_key?: string }
        | { mode: "job"; job_id: string; source: string; cache_key: string };

      if (start.mode === "sync") {
        setListings(start.listings);
        setListingsRaw(JSON.stringify(start.listings, null, 2));
        setScrapeJob({ status: "done", startedAt, elapsedMs: Date.now() - startedAt, progress: 1 });
        if (start.cache_hit) {
          toast.success(
            `Z cache: ${start.listings.length} lotów (bez nowego scrape)`,
          );
        } else {
          toast.success(`Scraper zwrócił ${start.listings.length} lotów`);
        }
        return;
      }

      // Async job — set context and let the background poller handle it
      const jobId = start.job_id;
      const cacheKey = start.cache_key;
      scrapeContextRef.current = { jobId, cacheKey, criteria: { ...criteria } };
      persistScrapeJob(jobId, cacheKey, criteria);
      setScrapeJob({ status: "running", jobId, startedAt, elapsedMs: 0 });
      // setBusy stays "scraper" — cleared by the poller on terminal state
    } catch (e) {
      const msg = (e as Error).message;
      setScrapeJob((s) =>
        s ? { ...s, status: "failed", errorMessage: s.errorMessage ?? msg } : s,
      );
      toast.error(msg);
      setBusy(null);
    }
  }

  async function runAi() {
    if (listings.length === 0) {
      toast.error("Brak lotów do analizy. Wczytaj wyniki scrapera lub wklej JSON.");
      return;
    }
    if (!criteria.make.trim()) {
      toast.error("Marka jest wymagana w kryteriach.");
      return;
    }
    setBusy("ai");
    const startedAt = Date.now();
    setAnalysisJob({ phase: "queued", startedAt, elapsedMs: 0, lotsCount: listings.length });
    try {
      setAnalysisJob((s) => s ? { ...s, phase: "analyzing", elapsedMs: Date.now() - startedAt } : s);
      const r = (await fnRunAnalysis({
        data: { criteria, listings, clientId: activeClientId ?? undefined, recordId: activeRecordId ?? undefined },
      })) as {
        ai_input: unknown;
        ai_prompt: string;
        analysis: AnalyzedLot[];
      };
      setAiInput(r.ai_input);
      setAiPrompt(r.ai_prompt);
      setAnalysis(r.analysis);

      // Auto-generuj raport HTML + mail
      let generatedReportHtml = "";
      let generatedMailHtml = "";
      if (r.analysis.length > 0) {
        setAnalysisJob((s) => s ? { ...s, phase: "rendering", elapsedMs: Date.now() - startedAt } : s);
        try {
          const rep = (await fnRenderReport({
            data: { clientName: activeClient?.name ?? "Klient", analyzed: r.analysis },
          })) as { report_html: string; mail_html: string };
          generatedReportHtml = rep.report_html;
          generatedMailHtml = rep.mail_html;
          setReportHtml(generatedReportHtml);
          setMailHtml(generatedMailHtml);
        } catch (err) {
          console.warn("Auto-render raportu nie powiódł się:", err);
        }
      }

      // Build artifacts metadata
      const now = new Date().toISOString();
      const artifactsMeta: ArtifactsMeta = {
        analysis: { lots_count: r.analysis.length, generated_at: now },
      };
      if (r.ai_input) {
        artifactsMeta.ai_input = { size: JSON.stringify(r.ai_input).length, generated_at: now };
      }
      if (r.ai_prompt) {
        artifactsMeta.ai_prompt = { size: r.ai_prompt.length, generated_at: now };
      }
      if (generatedReportHtml) {
        artifactsMeta.report_html = { size: generatedReportHtml.length, generated_at: now };
      }
      if (generatedMailHtml) {
        artifactsMeta.mail_html = { size: generatedMailHtml.length, generated_at: now };
      }

      // Auto-persist: zapisz rekord z analizą i artefaktami do DB
      if (activeClient) {
        setAnalysisJob((s) => s ? { ...s, phase: "saving", elapsedMs: Date.now() - startedAt } : s);
        try {
          const title = `${criteria.make} ${criteria.model || ""} ${criteria.year_from || ""}-${criteria.year_to || ""}`.trim();
          const analysisStartedIso = new Date(startedAt).toISOString();
          const row = (await fnSaveRecord({
            data: {
              id: activeRecordId ?? undefined,
              client_id: activeClient.id,
              title,
              status: "analyzed",
              criteria,
              listings,
              ai_input: r.ai_input,
              ai_prompt: r.ai_prompt || null,
              analysis: r.analysis,
              report_html: generatedReportHtml || null,
              mail_html: generatedMailHtml || null,
              analysis_status: "done",
              analysis_started_at: analysisStartedIso,
              analysis_completed_at: now,
              artifacts_meta: artifactsMeta,
              analysis_error: null,
              retry_count: 0,
              next_retry_at: null,
              last_error_at: null,
            },
          })) as unknown as { id: string };
          setActiveRecordId(row.id);
          await refreshRecords(activeClient.id);
        } catch (err) {
          console.warn("Auto-zapis rekordu nie powiódł się:", err);
          toast.error("Analiza gotowa, ale automatyczny zapis nie powiódł się. Zapisz ręcznie.");
        }
      }

      // Reset retry state on success
      currentRetryRef.current = 0;
      if (autoRetryTimerRef.current) { clearTimeout(autoRetryTimerRef.current); autoRetryTimerRef.current = null; }
      setAnalysisJob((s) => s ? { ...s, phase: "done", elapsedMs: Date.now() - startedAt } : s);
      toast.success(`Analiza zakończona: ${r.analysis.length} lotów przeanalizowanych`);
    } catch (e) {
      const msg = (e as Error).message;
      setAnalysisJob((s) => s ? { ...s, phase: "failed", elapsedMs: Date.now() - startedAt, errorMessage: msg } : s);

      // Persist error + compute retry backoff
      const currentRetry = currentRetryRef.current;
      const maxRetries = maxRetriesRef.current;
      const newRetryCount = currentRetry + 1;
      const canRetry = newRetryCount < maxRetries;
      // Exponential backoff: 10s, 30s, 90s, 270s...
      const backoffMs = canRetry ? Math.min(10_000 * Math.pow(3, currentRetry), 300_000) : null;
      const nextRetryAt = canRetry && backoffMs ? new Date(Date.now() + backoffMs).toISOString() : null;

      if (activeRecordId || activeClient) {
        try {
          const savedRow = (await fnSaveRecord({
            data: {
              id: activeRecordId ?? undefined,
              client_id: activeClient?.id ?? activeClientId ?? undefined,
              title: `${criteria.make} ${criteria.model || ""}`.trim(),
              status: "draft",
              criteria,
              listings,
              analysis_status: "failed",
              analysis_started_at: new Date(startedAt).toISOString(),
              analysis_completed_at: new Date().toISOString(),
              analysis_error: msg,
              retry_count: newRetryCount,
              max_retries: maxRetries,
              next_retry_at: nextRetryAt,
              last_error_at: new Date().toISOString(),
            },
          })) as unknown as { id: string };
          if (!activeRecordId) setActiveRecordId(savedRow.id);
          if (activeClient) await refreshRecords(activeClient.id);
        } catch {
          // best-effort
        }
      }

      if (canRetry && backoffMs) {
        const delaySec = Math.round(backoffMs / 1000);
        toast.error(`${msg} — ponowna próba za ${delaySec}s (${newRetryCount}/${maxRetries})`);
        // Schedule auto-retry & log
        autoRetryTimerRef.current = window.setTimeout(async () => {
          currentRetryRef.current = newRetryCount;
          try {
            await fnLogRetryEvent({
              data: {
                recordId: activeRecordId ?? "",
                clientId: activeClientId ?? undefined,
                criteria: criteria as unknown as Record<string, unknown>,
                retryCount: newRetryCount,
                source: "auto" as const,
              },
            });
          } catch { /* best-effort */ }
          runAi();
        }, backoffMs);
      } else {
        toast.error(canRetry ? msg : `${msg} — wyczerpano limit ${maxRetries} prób`);
      }
    } finally {
      setBusy(null);
    }
  }

  async function makeReport() {
    if (!analysis || analysis.length === 0) {
      toast.error("Najpierw uruchom analizę AI.");
      return;
    }
    setBusy("report");
    try {
      const r = (await fnRenderReport({
        data: {
          clientName: activeClient?.name ?? "Klient",
          analyzed: analysis,
        },
      })) as { report_html: string; mail_html: string };
      setReportHtml(r.report_html);
      setMailHtml(r.mail_html);
      toast.success("Raport wygenerowany");
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function makeLotReports() {
    if (listings.length === 0) {
      toast.error("Brak lotów. Wczytaj wyniki scrapera lub wklej JSON.");
      return;
    }
    if (!criteria.make.trim()) {
      toast.error("Marka jest wymagana w kryteriach.");
      return;
    }
    setBusy("lot");
    try {
      const r = (await fnRunLotReports({
        data: { criteria, listings, clientId: activeClientId ?? undefined, recordId: activeRecordId ?? undefined },
      })) as { report_html: string; mail_html: string; lots: Array<{ lot_id: string; score: number; group: string; rank_position: number | null }> };
      setReportHtml(r.report_html);
      setMailHtml(r.mail_html);
      const tops = r.lots.filter((l) => l.group === "TOP").length;
      const rejs = r.lots.filter((l) => l.group === "REJECTED").length;
      toast.success(`Raporty LOT gotowe: TOP ${tops}, odrzucone ${rejs}`);
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function persistRecord() {
    if (!activeClient) {
      toast.error("Wybierz klienta przed zapisem.");
      return;
    }
    setBusy("save");
    try {
      const title = `${criteria.make} ${criteria.model || ""} ${criteria.year_from || ""}-${criteria.year_to || ""}`.trim();
      const row = (await fnSaveRecord({
        data: {
          id: activeRecordId ?? undefined,
          client_id: activeClient.id,
          title,
          status: analysis ? "analyzed" : "draft",
          criteria,
          listings,
          ai_input: aiInput,
          ai_prompt: aiPrompt || null,
          analysis,
          report_html: reportHtml || null,
          mail_html: mailHtml || null,
        },
      })) as unknown as { id: string };
      setActiveRecordId(row.id);
      await refreshRecords(activeClient.id);
      toast.success("Rekord zapisany");
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function openRecord(id: string) {
    setBusy("load");
    try {
      const row = (await fnLoadRecord({ data: { id } })) as unknown as {
        id: string;
        client_id: string | null;
        criteria: ClientCriteria;
        listings: CarLot[];
        ai_input: unknown;
        ai_prompt: string | null;
        analysis: AnalyzedLot[] | null;
        report_html: string | null;
        mail_html: string | null;
      };
      setActiveRecordId(row.id);
      if (row.client_id) setActiveClientId(row.client_id);
      setCriteria({ ...DEFAULT_CRITERIA, ...row.criteria });
      setListings(row.listings ?? []);
      setListingsRaw(JSON.stringify(row.listings ?? [], null, 2));
      setAiInput(row.ai_input);
      setAiPrompt(row.ai_prompt ?? "");
      setAnalysis(row.analysis);
      setReportHtml(row.report_html ?? "");
      setMailHtml(row.mail_html ?? "");
      toast.success("Rekord wczytany");
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function retryAnalysis(recordId: string) {
    // Cancel any pending auto-retry
    if (autoRetryTimerRef.current) { clearTimeout(autoRetryTimerRef.current); autoRetryTimerRef.current = null; }
    currentRetryRef.current = 0;
    await openRecord(recordId);
    // Log retry event with preserved criteria
    try {
      await fnLogRetryEvent({
        data: {
          recordId,
          clientId: activeClientId ?? undefined,
          criteria: criteria as unknown as Record<string, unknown>,
          retryCount: 0,
          source: "manual" as const,
        },
      });
    } catch { /* best-effort logging */ }
    setTimeout(() => {
      runAi();
    }, 100);
  }

  async function removeRecord(id: string) {
    if (!confirm("Usunąć ten rekord?")) return;
    try {
      await fnDeleteRecord({ data: { id } });
      setRecords((rs) => rs.filter((r) => r.id !== id));
      if (activeRecordId === id) setActiveRecordId(null);
      toast.success("Usunięto");
    } catch (e) {
      toast.error((e as Error).message);
    }
  }

  function newSession() {
    setActiveRecordId(null);
    setCriteria(DEFAULT_CRITERIA);
    setListings([]);
    setListingsRaw("");
    setAnalysis(null);
    setAiInput(null);
    setAiPrompt("");
    setReportHtml("");
    setMailHtml("");
    setAnalysisJob(null);
  }

  // ---- render
  return (
    <div className="min-h-screen bg-background text-foreground">
      {/* Top bar */}
      <header className="sticky top-0 z-20 border-b border-border bg-background/95 backdrop-blur">
        <div className="flex items-center justify-between px-6 py-3">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-md bg-primary text-primary-foreground font-bold">
              UC
            </div>
            <div>
              <h1 className="text-base font-semibold leading-tight">USA Car Finder</h1>
              <p className="text-xs text-muted-foreground leading-tight">
                Panel operatora · Copart + IAAI · analiza AI
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <EnvStatus env={env} />
            <ThemeToggle />
            <Link
              to="/dashboard"
              className="inline-flex items-center gap-1.5 rounded-md border border-border bg-background px-3 py-1.5 text-xs font-medium hover:bg-accent"
            >
              <BarChart3 className="h-3.5 w-3.5" /> Dashboard
            </Link>
            <Link
              to="/watchlist"
              className="inline-flex items-center gap-1.5 rounded-md border border-border bg-background px-3 py-1.5 text-xs font-medium hover:bg-accent"
            >
              <Eye className="h-3.5 w-3.5" /> Watchlist
            </Link>
            <Link
              to="/calculator"
              className="inline-flex items-center gap-1.5 rounded-md border border-border bg-background px-3 py-1.5 text-xs font-medium hover:bg-accent"
            >
              <Calculator className="h-3.5 w-3.5" /> Kalkulator + VIN
            </Link>
            <Link
              to="/settings"
              className="inline-flex items-center gap-1.5 rounded-md border border-border bg-background px-3 py-1.5 text-xs font-medium hover:bg-accent"
            >
              <KeyRound className="h-3.5 w-3.5" /> Anthropic
            </Link>
            <SettingsSheet
              config={config}
              env={env}
              onSave={async (patch) => {
                try {
                  const r = (await fnUpdateConfig({ data: patch })) as ConfigRow;
                  setConfig(r);
                  toast.success("Konfiguracja zapisana");
                } catch (e) {
                  toast.error((e as Error).message);
                }
              }}
            />
          </div>
        </div>
      </header>

      <main className="grid grid-cols-1 gap-4 p-4 lg:grid-cols-[280px_minmax(0,1fr)_320px]">
        {/* ---- Clients column ---- */}
        <aside className="space-y-3">
          <Card className="p-3">
            <h2 className="mb-2 text-sm font-semibold">Nowy klient</h2>
            <div className="space-y-2">
              <Input
                placeholder="Imię i nazwisko / firma"
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
              />
              <Input
                placeholder="Kontakt (e-mail / telefon)"
                value={newContact}
                onChange={(e) => setNewContact(e.target.value)}
              />
              <Textarea
                placeholder="Notatki (opcjonalnie)"
                value={newNotes}
                onChange={(e) => setNewNotes(e.target.value)}
                rows={2}
              />
              <Button onClick={addClient} disabled={busy === "client"} className="w-full" size="sm">
                {busy === "client" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
                Dodaj
              </Button>
            </div>
          </Card>

          <Card className="p-3">
            <div className="mb-2 flex items-center justify-between">
              <h2 className="text-sm font-semibold">Klienci ({clients.length})</h2>
              <Button variant="ghost" size="sm" onClick={() => void refreshClients()}>
                <RefreshCw className="h-3.5 w-3.5" />
              </Button>
            </div>
            <div className="max-h-[60vh] space-y-1 overflow-y-auto">
              {clients.length === 0 && (
                <p className="px-1 py-2 text-xs text-muted-foreground">Brak klientów. Dodaj pierwszego powyżej.</p>
              )}
              {clients.map((c) => (
                <div
                  key={c.id}
                  className={`group flex items-start justify-between rounded-md border px-2 py-1.5 text-sm cursor-pointer ${
                    activeClientId === c.id
                      ? "border-primary bg-accent"
                      : "border-transparent hover:bg-muted"
                  }`}
                  onClick={() => setActiveClientId(c.id)}
                >
                  <div className="min-w-0 flex-1">
                    <div className="truncate font-medium">{c.name}</div>
                    {c.contact && <div className="truncate text-xs text-muted-foreground">{c.contact}</div>}
                  </div>
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      void removeClient(c.id);
                    }}
                    className="ml-2 opacity-0 group-hover:opacity-100"
                    title="Usuń"
                  >
                    <Trash2 className="h-3.5 w-3.5 text-muted-foreground hover:text-destructive" />
                  </button>
                </div>
              ))}
            </div>
          </Card>
        </aside>

        {/* ---- Workspace ---- */}
        <section className="min-w-0 space-y-4">
          <Card className="p-4">
            <div className="mb-3 flex items-center justify-between">
              <div>
                <h2 className="text-base font-semibold">
                  {activeClient ? `Sesja: ${activeClient.name}` : "Nowa sesja"}
                </h2>
                <p className="text-xs text-muted-foreground">
                  {activeRecordId ? `Rekord ${activeRecordId.slice(0, 8)}…` : "(nie zapisano)"}
                </p>
              </div>
              <div className="flex gap-2">
                <Button variant="outline" size="sm" onClick={newSession}>
                  Nowa sesja
                </Button>
                <Button size="sm" onClick={persistRecord} disabled={busy === "save" || !activeClient}>
                  {busy === "save" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                  Zapisz rekord
                </Button>
              </div>
            </div>

            <h3 className="mb-2 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
              Kryteria
            </h3>
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
              <Field label="Marka *">
                <Input
                  value={criteria.make}
                  onChange={(e) => setCriteria({ ...criteria, make: e.target.value })}
                  placeholder="Audi"
                />
              </Field>
              <Field label="Model">
                <Input
                  value={criteria.model ?? ""}
                  onChange={(e) => setCriteria({ ...criteria, model: e.target.value })}
                  placeholder="A5"
                />
              </Field>
              <Field label="Rocznik od">
                <Input
                  type="number"
                  value={criteria.year_from ?? ""}
                  onChange={(e) =>
                    setCriteria({ ...criteria, year_from: e.target.value ? +e.target.value : null })
                  }
                />
              </Field>
              <Field label="Rocznik do">
                <Input
                  type="number"
                  value={criteria.year_to ?? ""}
                  onChange={(e) =>
                    setCriteria({ ...criteria, year_to: e.target.value ? +e.target.value : null })
                  }
                />
              </Field>
              <Field label="Budżet USD *">
                <Input
                  type="number"
                  min={1}
                  value={criteria.budget_usd || ""}
                  onChange={(e) => setCriteria({ ...criteria, budget_usd: e.target.value ? +e.target.value : 0 })}
                  onBlur={(e) => {
                    if (!e.target.value || +e.target.value < 1) {
                      setCriteria((c) => ({ ...c, budget_usd: 15000 }));
                    }
                  }}
                />
              </Field>
              <Field label="Max przebieg (mil)">
                <Input
                  type="number"
                  value={criteria.max_odometer_mi ?? ""}
                  onChange={(e) =>
                    setCriteria({ ...criteria, max_odometer_mi: e.target.value ? +e.target.value : null })
                  }
                />
              </Field>
              <Field label="Max wyników">
                <Input
                  type="number"
                  value={criteria.max_results ?? 30}
                  onChange={(e) => setCriteria({ ...criteria, max_results: +e.target.value || 30 })}
                />
              </Field>
              <Field label="Wykluczone uszkodzenia">
                <Input
                  value={(criteria.excluded_damage_types ?? []).join(", ")}
                  onChange={(e) =>
                    setCriteria({
                      ...criteria,
                      excluded_damage_types: e.target.value
                        .split(",")
                        .map((s) => s.trim())
                        .filter(Boolean),
                    })
                  }
                  placeholder="Flood, Fire"
                />
              </Field>
            </div>

            <Separator className="my-4" />

            <div className="mb-2 flex items-center justify-between">
              <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
                Loty z aukcji ({listings.length})
              </h3>
              <div className="flex gap-2">
                <Button
                  size="sm"
                  variant="outline"
                  onClick={parseListingsFromText}
                  disabled={!listingsRaw.trim()}
                >
                  Wczytaj z JSON
                </Button>
                <Button
                  size="sm"
                  onClick={callScraper}
                  disabled={busy === "scraper" || !env?.SCRAPER_BASE_URL}
                  title={!env?.SCRAPER_BASE_URL ? "Ustaw SCRAPER_BASE_URL w sekretach" : ""}
                >
                  {busy === "scraper" ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Search className="h-4 w-4" />
                  )}
                  Wyszukaj online
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={clearCacheAll}
                  title="Wyczyść cache wyników (wymusi nowy scrape)"
                >
                  <Trash2 className="h-4 w-4" />
                  Wyczyść cache
                </Button>
              </div>
            </div>
            {scrapeJob && (
              <ScraperProgress
                job={scrapeJob}
                onCancel={cancelScrape}
                onDownloadLogs={downloadJobLogs}
                onRerun={callScraper}
                rerunDisabled={busy === "scraper"}
              />
            )}
            <Textarea
              className="font-mono text-xs"
              rows={6}
              placeholder='Wklej tutaj JSON z lotami: [{"source":"copart","lot_id":"123","year":2020,...}]'
              value={listingsRaw}
              onChange={(e) => setListingsRaw(e.target.value)}
            />
            {listings.length > 0 && <ListingsTable listings={listings} />}

            <Separator className="my-4" />

            <div className="flex flex-wrap items-center gap-2">
              <Button onClick={runAi} disabled={busy === "ai" || listings.length === 0}>
                {busy === "ai" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Brain className="h-4 w-4" />}
                {analysis && analysis.length > 0 ? "Uruchom analizę AI ponownie" : "Uruchom analizę AI"}
              </Button>
              {analysis && analysis.length > 0 && (
                <Button
                  variant="outline"
                  onClick={runAi}
                  disabled={busy === "ai" || listings.length === 0}
                  title="Ponowna analiza AI tych samych lotów (bez scrapingu)"
                >
                  {busy === "ai" ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <RefreshCw className="h-4 w-4" />
                  )}
                  Ponów analizę ({listings.length} lotów)
                </Button>
              )}
              <Button
                variant="outline"
                onClick={makeReport}
                disabled={busy === "report" || !analysis}
              >
                {busy === "report" ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <FileText className="h-4 w-4" />
                )}
                Wygeneruj raport (prosty)
              </Button>
              <Button
                onClick={makeLotReports}
                disabled={busy === "lot" || listings.length === 0}
                className="bg-primary"
              >
                {busy === "lot" ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <FileText className="h-4 w-4" />
                )}
                Generuj raporty LOT (broker + klient TOP3+2)
              </Button>
              {!env?.ANTHROPIC_API_KEY && (
                <span className="inline-flex items-center gap-1 text-xs text-destructive">
                  <AlertCircle className="h-3.5 w-3.5" />
                  Brak ANTHROPIC_API_KEY
                </span>
              )}
            </div>
            {analysisJob && <AnalysisProgress job={analysisJob} />}
          </Card>

          {analysis && analysis.length > 0 && (
            <Card className="p-4">
              <h3 className="mb-3 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
                Wyniki analizy AI ({analysis.length})
              </h3>
              <div className="space-y-3">
                {analysis.map((a) => (
                  <div key={a.lot.lot_id} className="rounded-md border p-3">
                    <div className="mb-2 flex items-start justify-between">
                      <div>
                        <div className="font-semibold">
                          {a.lot.year} {a.lot.make} {a.lot.model}
                        </div>
                        <div className="text-xs text-muted-foreground">
                          {a.lot.source?.toUpperCase()} · Lot {a.lot.lot_id} · {a.lot.location_state ?? "—"}
                        </div>
                      </div>
                      <div className="flex items-center gap-2">
                        <span className="text-lg font-bold">{a.analysis.score.toFixed(1)}</span>
                        <span
                          className={`rounded px-2 py-0.5 text-xs font-semibold ${recommendationBadge(
                            a.analysis.recommendation,
                          )}`}
                        >
                          {a.analysis.recommendation}
                        </span>
                      </div>
                    </div>
                    <p className="text-sm">{a.analysis.client_description_pl}</p>
                    {a.analysis.red_flags.length > 0 && (
                      <div className="mt-2 flex flex-wrap gap-1">
                        {a.analysis.red_flags.map((f, i) => (
                          <Badge key={i} variant="outline" className="text-xs">
                            ⚠ {f}
                          </Badge>
                        ))}
                      </div>
                    )}
                    <div className="mt-2 flex items-center justify-between">
                      <div className="text-xs text-muted-foreground">
                        Naprawa: ${a.analysis.estimated_repair_usd ?? "—"} · Łącznie: ${a.analysis.estimated_total_cost_usd ?? "—"}
                      </div>
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-7 px-2 text-xs"
                        onClick={() => watchLot(a)}
                      >
                        <Eye className="h-3 w-3 mr-1" /> Obserwuj
                      </Button>
                    </div>
                  </div>
                ))}
              </div>
            </Card>
          )}

          {reportHtml && (
            <Card className="p-4">
              <h3 className="mb-3 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
                Podgląd raportu HTML
              </h3>
              <iframe
                title="Raport"
                srcDoc={reportHtml}
                className="h-[600px] w-full rounded border"
              />
            </Card>
          )}

          {/* Downloads */}
          <Card className="p-4">
            <h3 className="mb-3 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
              Pliki do pobrania
            </h3>
            <div className="flex flex-wrap gap-2">
              <DownloadBtn
                label="ai_input.json"
                disabled={!aiInput}
                onClick={() => downloadFile("ai_input.json", JSON.stringify(aiInput, null, 2), "application/json")}
              />
              <DownloadBtn
                label="prompt.txt"
                disabled={!aiPrompt}
                onClick={() => downloadFile("prompt.txt", aiPrompt, "text/plain")}
              />
              <DownloadBtn
                label="analysis.json"
                disabled={!analysis}
                onClick={() => downloadFile("analysis.json", JSON.stringify(analysis, null, 2), "application/json")}
              />
              <DownloadBtn
                label="report.html"
                disabled={!reportHtml}
                onClick={() => downloadFile("report.html", reportHtml, "text/html")}
              />
              <DownloadBtn
                label="mail.html"
                disabled={!mailHtml}
                onClick={() => downloadFile("mail.html", mailHtml, "text/html")}
              />
              <DownloadBtn
                label="report.md"
                disabled={!analysis}
                onClick={() => {
                  const md = (analysis ?? [])
                    .map(
                      (a) =>
                        `## ${a.lot.year} ${a.lot.make} ${a.lot.model} — ${a.analysis.score.toFixed(1)}/10 ${a.analysis.recommendation}\n\n` +
                        `- Lot: ${a.lot.source}/${a.lot.lot_id}\n- Lokalizacja: ${a.lot.location_state ?? "—"}\n- Bid: $${a.lot.current_bid_usd ?? "—"}\n\n${a.analysis.client_description_pl}\n\n${a.analysis.ai_notes ?? ""}\n`,
                    )
                    .join("\n---\n\n");
                  downloadFile("report.md", md, "text/markdown");
                }}
              />
              <Button
                variant="default"
                size="sm"
                disabled={!activeRecordId || !analysis}
                onClick={() => window.open(`/api/reports/pdf?recordId=${activeRecordId}&mode=broker`, "_blank")}
                title={!activeRecordId ? "Najpierw zapisz rekord" : ""}
              >
                <Download className="h-3.5 w-3.5" /> PDF brokera
              </Button>
              <Button
                variant="default"
                size="sm"
                disabled={!activeRecordId || !analysis}
                onClick={() => window.open(`/api/reports/pdf?recordId=${activeRecordId}&mode=client`, "_blank")}
                title={!activeRecordId ? "Najpierw zapisz rekord" : ""}
              >
                <Download className="h-3.5 w-3.5" /> PDF klienta (TOP3+2)
              </Button>
            </div>
          </Card>
        </section>

        {/* ---- Records column ---- */}
        <aside>
          <Card className="p-3">
            <div className="mb-2 flex items-center justify-between">
              <h2 className="text-sm font-semibold">
                {activeClient ? `Rekordy: ${activeClient.name}` : "Wszystkie rekordy"}
              </h2>
              <Button variant="ghost" size="sm" onClick={() => void refreshRecords(activeClientId)}>
                <RefreshCw className="h-3.5 w-3.5" />
              </Button>
            </div>
            <div className="max-h-[80vh] space-y-1 overflow-y-auto">
              {records.length === 0 && (
                <p className="px-1 py-2 text-xs text-muted-foreground">Brak rekordów.</p>
              )}
              {records.map((r) => {
                const am = r.artifacts_meta;
                const analysisStatusLabel: Record<string, { text: string; color: string }> = {
                  done: { text: "Gotowe", color: "bg-[oklch(0.92_0.08_145)] text-[oklch(0.30_0.10_145)]" },
                  failed: { text: "Błąd", color: "bg-destructive/15 text-destructive" },
                  cancelled: { text: "Anulowano", color: "bg-muted text-muted-foreground" },
                  analyzing: { text: "Analizuje…", color: "bg-[oklch(0.92_0.08_250)] text-[oklch(0.30_0.10_250)]" },
                  rendering: { text: "Renderuje…", color: "bg-[oklch(0.92_0.08_250)] text-[oklch(0.30_0.10_250)]" },
                  saving: { text: "Zapisuje…", color: "bg-[oklch(0.92_0.08_250)] text-[oklch(0.30_0.10_250)]" },
                  queued: { text: "W kolejce", color: "bg-muted text-muted-foreground" },
                };
                const aStatus = r.analysis_status ? analysisStatusLabel[r.analysis_status] : null;

                return (
                  <div
                    key={r.id}
                    className={`group flex flex-col gap-1 rounded-md border px-2 py-1.5 text-sm cursor-pointer ${
                      activeRecordId === r.id ? "border-primary bg-accent" : "border-transparent hover:bg-muted"
                    }`}
                    onClick={() => void openRecord(r.id)}
                  >
                    <div className="flex items-start justify-between">
                      <div className="min-w-0 flex-1">
                        <div className="truncate font-medium">{r.title || "(bez tytułu)"}</div>
                        <div className="text-xs text-muted-foreground">
                          {new Date(r.created_at).toLocaleString("pl-PL")} · {r.status}
                        </div>
                      </div>
                      <div className="ml-2 flex items-center gap-1 opacity-0 group-hover:opacity-100">
                        <button
                          onClick={(e) => { e.stopPropagation(); void downloadRecordArtifact(r.id, "report_html"); }}
                          title="Pobierz raport HTML"
                          disabled={!am?.report_html}
                          className="disabled:opacity-30 disabled:cursor-not-allowed"
                        >
                          <FileText className="h-3.5 w-3.5 text-muted-foreground hover:text-primary" />
                        </button>
                        <button
                          onClick={(e) => { e.stopPropagation(); void downloadRecordArtifact(r.id, "ai_input"); }}
                          title="Pobierz AI input (JSON)"
                          disabled={!am?.ai_input}
                          className="disabled:opacity-30 disabled:cursor-not-allowed"
                        >
                          <BarChart3 className="h-3.5 w-3.5 text-muted-foreground hover:text-primary" />
                        </button>
                        <button
                          onClick={(e) => { e.stopPropagation(); void downloadRecordArtifact(r.id, "ai_prompt"); }}
                          title="Pobierz prompt AI (TXT)"
                          disabled={!am?.ai_prompt}
                          className="disabled:opacity-30 disabled:cursor-not-allowed"
                        >
                          <Brain className="h-3.5 w-3.5 text-muted-foreground hover:text-primary" />
                        </button>
                        <button
                          onClick={(e) => { e.stopPropagation(); void downloadRecordStatusJson(r.id); }}
                          title="Pobierz status analizy + artifacts_meta (JSON)"
                          className="disabled:opacity-30 disabled:cursor-not-allowed"
                        >
                          <Eye className="h-3.5 w-3.5 text-muted-foreground hover:text-primary" />
                        </button>
                        <button
                          onClick={(e) => { e.stopPropagation(); void downloadReportBundle(r.id); }}
                          title="Pobierz pakiet raportu (ZIP)"
                          disabled={r.status !== "analyzed"}
                          className="disabled:opacity-30 disabled:cursor-not-allowed"
                        >
                          <Download className="h-3.5 w-3.5 text-muted-foreground hover:text-primary" />
                        </button>
                        {(r.analysis_status === "failed" || r.analysis_status === "cancelled") && (
                          <button
                            onClick={(e) => { e.stopPropagation(); void retryAnalysis(r.id); }}
                            title="Ponów analizę AI"
                            className="disabled:opacity-30 disabled:cursor-not-allowed"
                            disabled={busy !== null}
                          >
                            <RotateCcw className="h-3.5 w-3.5 text-muted-foreground hover:text-primary" />
                          </button>
                        )}
                        <button
                          onClick={(e) => { e.stopPropagation(); void removeRecord(r.id); }}
                          title="Usuń"
                        >
                          <Trash2 className="h-3.5 w-3.5 text-muted-foreground hover:text-destructive" />
                        </button>
                      </div>
                    </div>
                    {/* Analysis status + artifact badges */}
                    {(aStatus || am) && (
                      <div className="flex flex-wrap items-center gap-1">
                        {aStatus && (
                          <span className={`inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-medium ${aStatus.color}`}>
                            {aStatus.text}
                          </span>
                        )}
                        {am?.report_html && (
                          <span className="inline-flex items-center rounded bg-muted px-1 py-0.5 text-[10px] text-muted-foreground" title={`HTML ${(am.report_html.size / 1024).toFixed(0)} KB`}>
                            HTML
                          </span>
                        )}
                        {am?.analysis && (
                          <span className="inline-flex items-center rounded bg-muted px-1 py-0.5 text-[10px] text-muted-foreground" title={`${am.analysis.lots_count} lotów`}>
                            AI:{am.analysis.lots_count}
                          </span>
                        )}
                        {am?.ai_input && (
                          <span className="inline-flex items-center rounded bg-muted px-1 py-0.5 text-[10px] text-muted-foreground" title={`Input ${(am.ai_input.size / 1024).toFixed(0)} KB`}>
                            IN
                          </span>
                        )}
                        {am?.ai_prompt && (
                          <span className="inline-flex items-center rounded bg-muted px-1 py-0.5 text-[10px] text-muted-foreground" title={`Prompt ${(am.ai_prompt.size / 1024).toFixed(0)} KB`}>
                            PR
                          </span>
                        )}
                        {am?.mail_html && (
                          <span className="inline-flex items-center rounded bg-muted px-1 py-0.5 text-[10px] text-muted-foreground">
                            MAIL
                          </span>
                        )}
                      </div>
                    )}
                    {r.analysis_status === "failed" && (
                      <div className="rounded bg-destructive/10 border border-destructive/20 px-2 py-1 text-[11px] text-destructive space-y-1">
                        <div className="flex items-center gap-1 font-medium">
                          <AlertCircle className="h-3 w-3 shrink-0" />
                          Błąd analizy
                          {r.retry_count > 0 && (
                            <span className="text-muted-foreground font-normal ml-1">
                              (próba {r.retry_count}/{r.max_retries})
                            </span>
                          )}
                        </div>
                        {r.analysis_error && (
                          <p className="line-clamp-3 break-all">{r.analysis_error}</p>
                        )}
                        {r.next_retry_at && new Date(r.next_retry_at) > new Date() && (
                          <p className="text-[10px] text-muted-foreground">
                            <RefreshCw className="h-2.5 w-2.5 inline mr-0.5" />
                            Następna próba: {new Date(r.next_retry_at).toLocaleTimeString("pl-PL")}
                          </p>
                        )}
                        {r.retry_count >= r.max_retries && (
                          <p className="text-[10px] font-medium">Wyczerpano limit prób</p>
                        )}
                      </div>
                    )}
                    {r.analysis_status === "cancelled" && (
                      <div className="rounded bg-muted border border-border px-2 py-1 text-[11px] text-muted-foreground space-y-1">
                        <div className="flex items-center gap-1 font-medium">
                          <X className="h-3 w-3 shrink-0" />
                          Anulowano przez użytkownika
                        </div>
                        {r.analysis_completed_at && (
                          <p className="text-[10px]">
                            {new Date(r.analysis_completed_at).toLocaleString("pl-PL")}
                          </p>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </Card>
          <LogsPanel
            clientId={activeClientId}
            recordId={activeRecordId}
            records={records}
            onOpenRecord={(id) => void openRecord(id)}
          />
        </aside>
      </main>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1">
      <Label className="text-xs">{label}</Label>
      {children}
    </div>
  );
}

function DownloadBtn({
  label,
  onClick,
  disabled,
}: {
  label: string;
  onClick: () => void;
  disabled?: boolean;
}) {
  return (
    <Button variant="outline" size="sm" onClick={onClick} disabled={disabled}>
      <Download className="h-3.5 w-3.5" /> {label}
    </Button>
  );
}

function ListingsTable({ listings }: { listings: CarLot[] }) {
  return (
    <div className="mt-3 max-h-[260px] overflow-auto rounded border">
      <table className="w-full text-xs">
        <thead className="sticky top-0 bg-muted">
          <tr className="text-left">
            <th className="px-2 py-1.5">Pojazd</th>
            <th className="px-2 py-1.5">Lot</th>
            <th className="px-2 py-1.5">Stan</th>
            <th className="px-2 py-1.5">Bid</th>
            <th className="px-2 py-1.5">Uszkodzenie</th>
            <th className="px-2 py-1.5">Tytuł</th>
            <th className="px-2 py-1.5">Sprzedawca</th>
          </tr>
        </thead>
        <tbody>
          {listings.map((l) => (
            <tr key={`${l.source}-${l.lot_id}`} className="border-t">
              <td className="px-2 py-1">
                {l.year ?? "?"} {l.make ?? ""} {l.model ?? ""}
              </td>
              <td className="px-2 py-1 text-muted-foreground">
                {l.source}/{l.lot_id}
              </td>
              <td className="px-2 py-1">{l.location_state ?? "—"}</td>
              <td className="px-2 py-1">${l.current_bid_usd ?? "—"}</td>
              <td className="px-2 py-1">{l.damage_primary ?? "—"}</td>
              <td className="px-2 py-1">{l.title_type ?? "—"}</td>
              <td className="px-2 py-1">{l.seller_type ?? "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function EnvStatus({ env }: { env: ConfigEnv | null }) {
  if (!env) return null;
  const Item = ({ ok, label }: { ok: boolean; label: string }) => (
    <span className="inline-flex items-center gap-1 text-xs">
      {ok ? (
        <CheckCircle2 className="h-3.5 w-3.5 text-[oklch(0.55_0.16_145)]" />
      ) : (
        <AlertCircle className="h-3.5 w-3.5 text-destructive" />
      )}
      {label}
    </span>
  );
  return (
    <div className="hidden items-center gap-3 rounded-md border bg-card px-3 py-1.5 md:flex">
      <Item ok={env.ANTHROPIC_API_KEY} label="AI" />
      <Item ok={env.SCRAPER_BASE_URL && env.SCRAPER_API_TOKEN} label="Scraper" />
    </div>
  );
}

function SettingsSheet({
  config,
  env,
  onSave,
}: {
  config: ConfigRow | null;
  env: ConfigEnv | null;
  onSave: (patch: Partial<ConfigRow>) => Promise<void>;
}) {
  const [draft, setDraft] = useState<ConfigRow | null>(config);
  useEffect(() => setDraft(config), [config]);
  return (
    <Sheet>
      <SheetTrigger asChild>
        <Button variant="outline" size="sm">
          <Settings className="h-4 w-4" /> Ustawienia
        </Button>
      </SheetTrigger>
      <SheetContent className="w-[400px] overflow-y-auto sm:max-w-md">
        <SheetHeader>
          <SheetTitle>Ustawienia operacyjne</SheetTitle>
        </SheetHeader>
        {draft && (
          <div className="mt-4 space-y-4">
            <ToggleRow
              label="Tryb demo (mock data)"
              value={draft.use_mock_data}
              onChange={(v) => setDraft({ ...draft, use_mock_data: v })}
            />
            <ToggleRow
              label="Filtruj tylko Seller-Type Insurance"
              value={draft.filter_seller_insurance_only}
              onChange={(v) => setDraft({ ...draft, filter_seller_insurance_only: v })}
            />
            <ToggleRow
              label="Zbieraj wszystkie wstępnie odfiltrowane wyniki"
              value={draft.collect_all_prefiltered_results}
              onChange={(v) => setDraft({ ...draft, collect_all_prefiltered_results: v })}
            />
            <ToggleRow
              label="Otwieraj wszystkie szczegóły wstępnie odfiltrowanych"
              value={draft.open_all_prefiltered_details}
              onChange={(v) => setDraft({ ...draft, open_all_prefiltered_details: v })}
            />
            <Field label="Tryb analizy AI">
              <select
                className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm"
                value={draft.ai_analysis_mode}
                onChange={(e) => setDraft({ ...draft, ai_analysis_mode: e.target.value })}
              >
                <option value="anthropic">anthropic</option>
                <option value="auto">auto</option>
                <option value="openai">openai</option>
                <option value="local">local</option>
              </select>
            </Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Min okno aukcji (h)">
                <Input
                  type="number"
                  value={draft.min_auction_window_hours}
                  onChange={(e) =>
                    setDraft({ ...draft, min_auction_window_hours: +e.target.value || 0 })
                  }
                />
              </Field>
              <Field label="Max okno aukcji (h)">
                <Input
                  type="number"
                  value={draft.max_auction_window_hours}
                  onChange={(e) =>
                    setDraft({ ...draft, max_auction_window_hours: +e.target.value || 0 })
                  }
                />
              </Field>
            </div>
            <Button
              className="w-full"
              onClick={() => void onSave(draft)}
            >
              Zapisz ustawienia
            </Button>
            <Separator />
            <div>
              <h4 className="mb-2 text-sm font-semibold">Sekrety środowiska</h4>
              <ul className="space-y-1 text-xs">
                <li>ANTHROPIC_API_KEY: {env?.ANTHROPIC_API_KEY ? "✓ ustawiony" : "✗ brak"}</li>
                <li>ANTHROPIC_MODEL: {env?.ANTHROPIC_MODEL}</li>
                <li>ANTHROPIC_BASE_URL: {env?.ANTHROPIC_BASE_URL}</li>
                <li>SCRAPER_BASE_URL: {env?.SCRAPER_BASE_URL ? "✓ ustawiony" : "✗ brak"}</li>
                <li>SCRAPER_API_TOKEN: {env?.SCRAPER_API_TOKEN ? "✓ ustawiony" : "✗ brak"}</li>
              </ul>
              <p className="mt-2 text-xs text-muted-foreground">
                Sekrety dodajesz w Lovable Cloud (Connectors → secrets). Aplikacja czyta je w server functions.
              </p>
            </div>
          </div>
        )}
      </SheetContent>
    </Sheet>
  );
}

function ToggleRow({
  label,
  value,
  onChange,
}: {
  label: string;
  value: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <div className="flex items-center justify-between gap-3">
      <Label className="text-sm">{label}</Label>
      <Switch checked={value} onCheckedChange={onChange} />
    </div>
  );
}
