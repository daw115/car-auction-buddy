import { createFileRoute, Link } from "@tanstack/react-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  persistScrapeJob,
  clearPersistedScrapeJob,
  readPersistedScrapeJob,
  SCRAPE_JOB_STORAGE_KEY,
  type ValidatedScrapeJob,
} from "@/lib/scrape-job-storage";
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
  // listActiveScraperJobs przeniesiony do /jobs
  clearScrapeCache,
  getJobLogs,
  runLotReports,
  getReportBundle,
  logRetryEvent,
  checkHealth,
  getLlmCacheStats,
  clearLlmCache,
  parseClientMessage,
  batchSearch,
} from "@/functions/api.functions";
// BackendRecordsPanel / SearchAuditPanel / RecordDetailView -> /records
// ConnectionStatusPanel -> /jobs
import { addToWatchlist } from "@/functions/watchlist.functions";

import type { CarLot, ClientCriteria, AnalyzedLot, AIAnalysis } from "@/lib/types";
import { getCurrentSiteUser, SITE_USERS } from "@/lib/site-user";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Checkbox } from "@/components/ui/checkbox";
import { LogsPanel } from "@/components/LogsPanel";
import { BidfaxBadge } from "@/components/BidfaxBadge";
import { ThemeToggle } from "@/components/theme-toggle";
import { ResumeJobBanner } from "@/components/ResumeJobBanner";
// LiveJobLogs używany teraz tylko w panels/jobs-panel.tsx
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { Progress } from "@/components/ui/progress";
import { Card } from "@/components/ui/card";

import { Alert, AlertDescription } from "@/components/ui/alert";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
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
  FlaskConical,
  ExternalLink,
  Wifi,
  WifiOff,
  Clock,
  HardDrive,
} from "lucide-react";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "Panel operatora — USA Car Finder" },
      {
        name: "description",
        content:
          "Uruchamiaj scrapery aukcji Copart i IAAI, analizuj wyniki AI, generuj raporty PDF i zarządzaj klientami z jednego panelu operatora.",
      },
      { property: "og:title", content: "Panel operatora — USA Car Finder" },
      {
        property: "og:description",
        content:
          "Uruchamiaj scrapery aukcji Copart i IAAI, analizuj wyniki AI i generuj raporty PDF z jednego panelu.",
      },
      { property: "og:url", content: "https://car-auction-buddy.lovable.app/" },
    ],
    links: [{ rel: "canonical", href: "https://car-auction-buddy.lovable.app/" }],
  }),
  component: Panel,
});

type ClientRow = { id: string; name: string; contact: string | null; notes: string | null; created_at: string };
type AiMeta = { provider: string; model: string; usedFallback: boolean; fallbackMode: string; usage: { input_tokens: number; output_tokens: number } };
type ArtifactsMeta = {
  report_html?: { size: number; generated_at: string };
  mail_html?: { size: number; generated_at: string };
  ai_input?: { size: number; generated_at: string };
  ai_prompt?: { size: number; generated_at: string };
  analysis?: { lots_count: number; generated_at: string };
  ai_meta?: AiMeta;
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
  budget_usd: null,
  max_odometer_mi: null,
  fuel_type: null,
  excluded_damage_types: ["Flood", "Fire"],
  max_results: 15,
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

import type { ScraperReportUrls } from "@/components/panels/batch-job-card";

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
  reportUrls?: ScraperReportUrls;
};

type AnalysisPhase = "queued" | "analyzing" | "rendering" | "saving" | "done" | "failed" | "cancelled";

type AnalysisJobState = {
  phase: AnalysisPhase;
  lastPhase?: AnalysisPhase;
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

/** Map raw error messages to user-friendly Polish descriptions. */
/** Check whether a raw error message looks like a scraper 404 */
function isScraper404(raw: string): boolean {
  const l = raw.toLowerCase();
  return (l.includes("404") && (l.includes("scraper") || l.includes("not found")));
}

function humanizeError(raw: string): string {
  const lower = raw.toLowerCase();
  if (isScraper404(raw))
    return "Endpoint scrapera nie został znaleziony (HTTP 404). Serwer scrapera działa, ale żądany adres URL nie istnieje.";
  if (lower.includes("timeout") || lower.includes("timed out")) return "Przekroczono limit czasu oczekiwania na odpowiedź serwera.";
  if (lower.includes("network") || lower.includes("fetch failed") || lower.includes("econnrefused")) return "Błąd połączenia sieciowego — serwer scrapera może być niedostępny.";
  if (lower.includes("rate limit") || lower.includes("429")) return "Zbyt wiele zapytań — serwer ograniczył dostęp. Spróbuj ponownie za chwilę.";
  if (lower.includes("401") || lower.includes("unauthorized")) return "Brak autoryzacji — sprawdź token API scrapera.";
  if (lower.includes("403") || lower.includes("forbidden")) return "Dostęp zabroniony — sprawdź uprawnienia.";
  if (lower.includes("500") || lower.includes("internal server error")) return "Wewnętrzny błąd serwera scrapera.";
  if (lower.includes("502") || lower.includes("bad gateway")) return "Błąd bramy — serwer scrapera nie odpowiada prawidłowo.";
  if (lower.includes("503") || lower.includes("service unavailable")) return "Serwis scrapera tymczasowo niedostępny.";
  if (lower.includes("anthropic") || lower.includes("claude")) return "Błąd usługi AI (Anthropic) — spróbuj ponownie.";
  if (lower.includes("overloaded")) return "Serwis AI jest przeciążony — spróbuj ponownie za chwilę.";
  if (lower.includes("no results") || lower.includes("0 lotów") || lower.includes("empty")) return "Wyszukiwanie nie zwróciło wyników. Spróbuj zmienić kryteria.";
  return raw;
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
          {isScraper404(job.errorMessage) && (
            <div className="rounded bg-destructive/5 border border-destructive/20 px-2.5 py-2 text-[11px] text-foreground space-y-1.5 mt-1">
              <div className="font-semibold text-destructive">Jak naprawić?</div>
              <ol className="list-decimal list-inside space-y-1 text-muted-foreground">
                <li>Sprawdź, czy serwer scrapera jest uruchomiony i dostępny pod adresem ustawionym w <span className="font-mono text-foreground">SCRAPER_BASE_URL</span>.</li>
                <li>Otwórz <span className="font-mono text-foreground">/health</span> na serwerze scrapera — powinien zwrócić JSON ze statusem <span className="font-mono text-foreground">"ok"</span>.</li>
                <li>Upewnij się, że endpoint <span className="font-mono text-foreground">POST /search</span> istnieje (np. <span className="font-mono text-foreground">http://twój-scraper/search</span>).</li>
                <li>Jeśli scraper działa lokalnie, wyeksponuj go publicznie (np. <span className="font-mono text-foreground">ngrok http 8000</span>) i zaktualizuj <span className="font-mono text-foreground">SCRAPER_BASE_URL</span> w ustawieniach.</li>
                <li>Po zmianie URL scrapera przejdź do <a href="/settings" className="underline text-primary hover:text-primary/80">Ustawień</a> i zweryfikuj połączenie przyciskiem „Test".</li>
              </ol>
            </div>
          )}
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
      {/* Phase pipeline badges — show progress through phases, highlight failure point */}
      <div className="flex flex-wrap items-center gap-1">
        {(() => {
          if (job.phase === "failed") {
            const failedAt = job.lastPhase ?? "analyzing";
            const failIdx = analysisPhases.indexOf(failedAt);
            return analysisPhases.map((p, i) => {
              const isFail = i === failIdx || (failIdx < 0 && i === 0);
              const reached = failIdx >= 0 && i < failIdx;
              return (
                <span
                  key={p}
                  className={`inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-medium ${
                    isFail
                      ? "bg-destructive/20 text-destructive ring-1 ring-destructive/30"
                      : reached
                        ? "bg-muted text-muted-foreground line-through"
                        : "bg-muted/50 text-muted-foreground/50"
                  }`}
                >
                  {phaseLabels[p] ?? p}
                </span>
              );
            });
          }
          return analysisPhases.map((p) => (
            <PhaseBadge key={p} phase={phaseLabels[p] ?? p} active={p === job.phase} />
          ));
        })()}
      </div>
      {job.phase === "failed" && (
        <div className="rounded border border-destructive/30 bg-destructive/5 px-2 py-1.5 text-xs space-y-1">
          <div className="text-[11px] text-destructive flex items-center gap-1">
            <AlertCircle className="h-3 w-3 shrink-0" />
            Zatrzymano na etapie: <span className="font-medium">{phaseLabels[job.lastPhase ?? "analyzing"]}</span>
          </div>
          {job.errorMessage && (
            <>
              <div className="font-medium text-destructive">
                {humanizeError(job.errorMessage)}
              </div>
              {job.errorMessage !== humanizeError(job.errorMessage) && (
                <details className="text-[11px] text-muted-foreground">
                  <summary className="cursor-pointer hover:text-foreground">Szczegóły techniczne</summary>
                  <pre className="font-mono text-foreground break-words whitespace-pre-wrap mt-1">{job.errorMessage}</pre>
                </details>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}

// ActiveJobsPanel / ActiveJobRow / phaseLine / PHASE_LABELS / ActiveJob
// zostały przeniesione do src/components/panels/jobs-panel.tsx (route /jobs).


// ---------- Batch search types + card ----------
// BatchJobCard + BatchJobEntry przeniesione do src/components/panels/batch-job-card.tsx
import { BatchJobCard, type BatchJobEntry } from "@/components/panels/batch-job-card";

type ParsedCarsResult = {
  criteria_list: ClientCriteria[];
  summary: string;
  warnings: string[];
};


// Backend Records / Search Audit / Record Detail — przeniesione do panels/records-panel.tsx



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
  const fnParseMessage = useServerFn(parseClientMessage);
  const fnBatchSearch = useServerFn(batchSearch);

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
    field: "report_html" | "ai_input" | "ai_prompt" | "analysis",
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
        analysis: { name: `analysis-${recordId.slice(0, 8)}.json`, mime: "application/json" },
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
  const [disableAuctionFilter, setDisableAuctionFilter] = useState<boolean>(false);
  const [clientMessage, setClientMessage] = useState("");
  const [parsing, setParsing] = useState(false);
  const [lastParseResult, setLastParseResult] = useState<{ summary: string; warnings: string[] } | null>(null);
  const [parsedCars, setParsedCars] = useState<ParsedCarsResult | null>(null);
  const [batchJobs, setBatchJobs] = useState<BatchJobEntry[]>([]);
  const [listings, setListings] = useState<CarLot[]>([]);
  const [listingsRaw, setListingsRaw] = useState<string>("");
  
  // openedBackendRecordId przeniesiony na /records

  const [analysis, setAnalysis] = useState<AnalyzedLot[] | null>(null);
  const [aiMeta, setAiMeta] = useState<AiMeta | null>(null);
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
  const [scrapeJob, setScrapeJob] = useState<ScrapeJobState | null>(null);

  // Pending resume state — set on mount if localStorage has an active job
  const [pendingResume, setPendingResume] = useState<ValidatedScrapeJob | null>(null);
  const [resumeValidationErrors, setResumeValidationErrors] = useState<string[]>([]);

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

  const TERMINAL_STATUSES = ["done", "completed", "finished", "success", "complete", "failed", "error", "cancelled", "not_found"];

  // Background poller: ticks elapsed + polls backend every 2s, pauses on terminal state
  useEffect(() => {
    if (!scrapeJob) return;
    if (TERMINAL_STATUSES.includes(scrapeJob.status)) return;

    const ctx = scrapeContextRef.current;
    let polling = false;

    // Pełen flow: scrape (Copart 7-10 lotów + IAAI 25-30 lotów) + AI analiza +
    // 5×LLM raporty parallel (Gemini/Anthropic) = realistycznie 8-15 min.
    // 5 min było za mało, podnosimy do 20 min.
    const POLL_TIMEOUT_MS = 20 * 60 * 1000;

    const t = setInterval(async () => {
      // Always tick elapsed
      const elapsed = Date.now() - (scrapeJob?.startedAt ?? Date.now());
      setScrapeJob((s) => (s ? { ...s, elapsedMs: Date.now() - s.startedAt } : s));

      // Timeout after 20 min
      if (elapsed > POLL_TIMEOUT_MS) {
        setScrapeJob((s) =>
          s ? { ...s, status: "failed", errorMessage: "Timeout – brak odpowiedzi po 20 min", elapsedMs: Date.now() - s.startedAt } : s,
        );
        scrapeContextRef.current = null;
        clearPersistedScrapeJob();
        setBusy(null);
        toast.error("Timeout scrapera (20 min)");
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
          client_report_url?: string;
          polecane_index_url?: string;
          client_reports_html?: string[];
          broker_reports_html?: string[];
          artifact_urls?: { client_report?: string; analysis_json?: string; ai_prompt?: string; ai_input?: string; polecane_index?: string };
          report_endpoints?: { client_html?: string; broker_html?: string; client_llm?: string; broker_llm?: string; offer_email_html?: string; pdf?: string };
          // Python adapter zwraca już gotową analizę AI (POLECAM/RYZYKO/ODRZUĆ + score)
          // Dzięki temu TS NIE musi dublować callAI() przez runAnalysis (~50% mniej tokenów).
          analyzed_lots?: Array<{ lot: CarLot; analysis: AIAnalysis; is_top_recommendation?: boolean; auto_reports?: { client_hybrid_url?: string; broker_hybrid_url?: string } }>;
        };
        // Phase labels for toast notifications
        const PHASE_TOAST_LABELS: Record<string, string> = {
          queued: "Job w kolejce…",
          running: "Scraper pracuje…",
          scraping_list: "Pobieranie listy aukcji…",
          scraping_details: "Pobieranie szczegółów lotów…",
          enriching: "Wzbogacanie danych…",
          parsing: "Parsowanie wyników…",
        };

        // Notify on phase transitions (for resumed jobs or any active polling)
        const currentPhase = p.phase ?? p.status;
        if (wasResumedRef.current && currentPhase && currentPhase !== lastNotifiedPhaseRef.current) {
          const label = PHASE_TOAST_LABELS[currentPhase];
          if (label) {
            const progressSuffix = typeof p.current === "number" && typeof p.total === "number"
              ? ` (${p.current}/${p.total})`
              : typeof p.progress === "number"
                ? ` (${Math.round(p.progress * 100)}%)`
                : "";
            toast.info(`${label}${progressSuffix}`);
          } else if (lastNotifiedPhaseRef.current === null) {
            // First successful poll after resume — confirm connection
            toast.info("Połączono z jobem scrapera — śledzę postęp…");
          }
          lastNotifiedPhaseRef.current = currentPhase;
        }

        const DONE = ["done", "completed", "finished", "success", "complete"];
        if (DONE.includes(p.status) || (typeof p.progress === "number" && p.progress >= 1.0)) {
          const result = Array.isArray(p.listings) ? p.listings : [];
          setScrapeJob((s) =>
            s ? {
              ...s, status: "done", progress: 1, elapsedMs: Date.now() - s.startedAt,
              reportUrls: {
                client_report_url: p.client_report_url,
                polecane_index_url: p.polecane_index_url,
                client_reports_html: p.client_reports_html,
                broker_reports_html: p.broker_reports_html,
                artifact_urls: p.artifact_urls,
                report_endpoints: p.report_endpoints,
              },
            } : s,
          );
          setListings(result);
          setListingsRaw(JSON.stringify(result, null, 2));
          // Jeśli Python zwrócił już gotową analizę (POLECAM/RYZYKO/ODRZUĆ + score),
          // wstaw ją od razu — bez konieczności wywołania runAnalysis (oszczędność tokenów).
          if (Array.isArray(p.analyzed_lots) && p.analyzed_lots.length > 0) {
            setAnalysis(p.analyzed_lots as AnalyzedLot[]);
            const polecam = p.analyzed_lots.filter((a) => a.analysis?.recommendation === "POLECAM").length;
            toast.success(`Scraper + AI gotowe: ${result.length} lotów, ${polecam} polecanych`);
          } else {
            toast.success(`Scraper zakończył pracę — zwrócono ${result.length} lotów`);
          }
          setBusy(null);
          scrapeContextRef.current = null;
          clearPersistedScrapeJob();
          wasResumedRef.current = false;
          lastNotifiedPhaseRef.current = null;
        } else if (p.status === "not_found") {
          const errMsg = p.error ?? "Job nie istnieje na serwerze scrapera.";
          setScrapeJob((s) =>
            s
              ? { ...s, status: "failed", elapsedMs: Date.now() - s.startedAt, errorMessage: errMsg, errorStep: "not_found" }
              : s,
          );
          toast.error("Zapisany job scrapera już nie istnieje — wyczyszczono dane lokalne.");
          setBusy(null);
          scrapeContextRef.current = null;
          clearPersistedScrapeJob();
          wasResumedRef.current = false;
          lastNotifiedPhaseRef.current = null;
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
          wasResumedRef.current = false;
          lastNotifiedPhaseRef.current = null;
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
  // Track whether the current job was resumed (needs confirmation before cancel)
  const wasResumedRef = useRef(false);
  // Track last phase notified via toast (to avoid duplicate toasts)
  const lastNotifiedPhaseRef = useRef<string | null>(null);
  const [showCancelConfirm, setShowCancelConfirm] = useState(false);

  // On mount: detect active scrape job in localStorage and offer resume
  useEffect(() => {
    const { job, validationErrors } = readPersistedScrapeJob();
    if (validationErrors.length > 0) {
      setResumeValidationErrors(validationErrors);
      toast.error("Zapisane kryteria scrapera są nieprawidłowe — dane wyczyszczone.");
    } else if (job) {
      setPendingResume(job);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function resumeScrapeJob() {
    if (!pendingResume) return;
    const saved = pendingResume;
    setPendingResume(null);
    scrapeContextRef.current = { jobId: saved.jobId, cacheKey: saved.cacheKey, criteria: saved.criteria };
    setScrapeJob({ status: "running", jobId: saved.jobId, startedAt: saved.startedAt, elapsedMs: Date.now() - saved.startedAt });
    setCriteria((c) => ({ ...c, ...saved.criteria }));
    setBusy("scraper");
    cancelRequestedRef.current = false;
    wasResumedRef.current = true;
    lastNotifiedPhaseRef.current = null;
    toast.info("Wznowiono śledzenie — łączenie z serwerem scrapera…");
  }

  function dismissResume() {
    setPendingResume(null);
    clearPersistedScrapeJob();
  }

  /** Guard cancel with confirmation dialog when the job was resumed */
  function requestCancelScrape() {
    if (wasResumedRef.current) {
      setShowCancelConfirm(true);
    } else {
      cancelScrape();
    }
  }

  function confirmCancelScrape() {
    setShowCancelConfirm(false);
    cancelScrape();
  }

  async function cancelScrape() {
    wasResumedRef.current = false;
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
          criteria: { ...criteria, searched_by: getCurrentSiteUser() },
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

  async function handleParseMessage() {
    if (!clientMessage.trim()) {
      toast.error("Wpisz wiadomość od klienta");
      return;
    }
    setParsing(true);
    setLastParseResult(null);
    setParsedCars(null);
    try {
      const result = await fnParseMessage({ data: { message: clientMessage } });
      // If backend returns criteria_list (multi-car), store for batch search
      if (result.criteria_list && result.criteria_list.length > 1) {
        setParsedCars({
          criteria_list: result.criteria_list,
          summary: result.summary,
          warnings: result.warnings,
        });
        // Also fill first car into the form
        setCriteria({ ...DEFAULT_CRITERIA, ...result.criteria_list[0] });
      } else {
        setCriteria({ ...DEFAULT_CRITERIA, ...result.criteria });
      }
      setLastParseResult({ summary: result.summary, warnings: result.warnings });
      toast.success(result.summary, { duration: 6000 });
      result.warnings.forEach((w) => toast.warning(w, { duration: 8000 }));
    } catch (e) {
      toast.error(`Błąd parsowania: ${(e as Error).message}`);
    } finally {
      setParsing(false);
    }
  }

  async function handleBatchSearch() {
    if (!parsedCars) return;

    try {
      const r = await fnBatchSearch({
        data: {
          searches: parsedCars.criteria_list.map((c) => ({ criteria: c as unknown as Record<string, unknown> })),
        },
      });

      setBatchJobs(
        r.jobs.map((j) => ({
          jobId: j.job_id,
          label: j.label,
          criteria:
            parsedCars.criteria_list.find(
              (c) => `${c.make} ${c.model || ""}`.trim().toLowerCase() === j.label.toLowerCase(),
            ) ?? parsedCars.criteria_list[0],
          status: j.idempotent ? "running" as const : "queued" as const,
        })),
      );

      setParsedCars(null);
      toast.success(`Zakolejkowano ${r.queued_count} wyszukiwań`);
    } catch (e) {
      toast.error(`Błąd batch search: ${(e as Error).message}`);
    }
  }

  const handleBatchJobUpdate = useCallback((jobId: string, update: Partial<BatchJobEntry>) => {
    setBatchJobs((prev) =>
      prev.map((j) => (j.jobId === jobId ? { ...j, ...update } : j)),
    );
  }, []);

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
        data: { criteria, clientId: activeClientId ?? undefined, recordId: activeRecordId ?? undefined, disable_auction_filter: disableAuctionFilter },
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
      toast.error(humanizeError(msg), {
        description: isScraper404(msg) ? "Sprawdź panel błędu poniżej — znajdziesz tam instrukcję naprawy." : undefined,
        duration: isScraper404(msg) ? 8000 : 4000,
      });
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
        ai_meta?: { provider: string; model: string; usedFallback: boolean; fallbackMode: string; usage: { input_tokens: number; output_tokens: number } };
      };
      setAiInput(r.ai_input);
      setAiPrompt(r.ai_prompt);
      setAnalysis(r.analysis);
      setAiMeta(r.ai_meta ?? null);

      // Auto-generuj raport HTML + mail
      let generatedReportHtml = "";
      let generatedMailHtml = "";
      if (r.analysis.length > 0) {
        setAnalysisJob((s) => s ? { ...s, phase: "rendering", elapsedMs: Date.now() - startedAt } : s);
        try {
          const rep = (await fnRenderReport({
            data: {
              clientName: activeClient?.name ?? "Klient",
              analyzed: r.analysis,
              searchedBy: getCurrentSiteUser(),
            },
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
      if (r.ai_meta) {
        artifactsMeta.ai_meta = r.ai_meta;
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
              criteria: { ...criteria, searched_by: getCurrentSiteUser() },
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
      setAnalysisJob((s) => s ? { ...s, phase: "failed", lastPhase: s.phase !== "failed" ? s.phase : s.lastPhase, elapsedMs: Date.now() - startedAt, errorMessage: msg } : s);

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
              criteria: { ...criteria, searched_by: getCurrentSiteUser() },
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
          searchedBy: getCurrentSiteUser(),
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
          criteria: { ...criteria, searched_by: getCurrentSiteUser() },
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
        artifacts_meta: ArtifactsMeta | null;
      };
      setActiveRecordId(row.id);
      if (row.client_id) setActiveClientId(row.client_id);
      setCriteria({ ...DEFAULT_CRITERIA, ...row.criteria });
      setListings(row.listings ?? []);
      setListingsRaw(JSON.stringify(row.listings ?? [], null, 2));
      setAiInput(row.ai_input);
      setAiPrompt(row.ai_prompt ?? "");
      setAnalysis(row.analysis);
      setAiMeta((row.artifacts_meta as ArtifactsMeta | null)?.ai_meta ?? null);
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

    // Load record to check retry limit before proceeding
    const row = (await fnLoadRecord({ data: { id: recordId } })) as unknown as {
      retry_count: number;
      max_retries: number;
      analysis_error?: string | null;
    };

    if (row.retry_count >= row.max_retries) {
      toast.error(
        `Wyczerpano limit ${row.max_retries} prób ponowienia.${row.analysis_error ? ` Ostatni błąd: ${row.analysis_error}` : ""}`,
      );
      return;
    }

    currentRetryRef.current = row.retry_count;
    await openRecord(recordId);
    // Log retry event with preserved criteria
    try {
      await fnLogRetryEvent({
        data: {
          recordId,
          clientId: activeClientId ?? undefined,
          criteria: criteria as unknown as Record<string, unknown>,
          retryCount: row.retry_count,
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
    setAiMeta(null);
    setAiInput(null);
    setAiPrompt("");
    setReportHtml("");
    setMailHtml("");
    setAnalysisJob(null);
  }

  return (
    <div className="text-foreground -m-4 sm:-m-6">
      {/* Sub-header: status środowiska + ustawienia (nawigacja jest w sidebarze) */}
      <div className="sticky top-14 z-20 border-b border-border bg-background/95 backdrop-blur">
        <div className="flex flex-wrap items-center justify-between gap-2 px-4 py-2 sm:px-6">
          <div className="flex items-center gap-2 min-w-0">
            <h2 className="text-sm font-semibold text-foreground truncate">
              Panel operatora · Copart + IAAI · analiza AI
            </h2>
          </div>
          <div className="flex items-center gap-2">
            <EnvStatus env={env} />
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
      </div>

      {/* Aktywne joby — pełna lista na /jobs, tu tylko pill w topbarze */}

      <main className="grid grid-cols-1 gap-4 p-4 sm:p-6 lg:grid-cols-[300px_minmax(0,1fr)]">
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
          {/* Rekordy + audyt na /records, status połączeń na /jobs */}
        </aside>

        {/* ---- Workspace ---- */}
        <section className="min-w-0 space-y-4">
          <>

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

            <Card className="p-4 mb-4 border-primary/30 bg-primary/5">
              <div className="flex items-center gap-2 mb-3">
                <span className="text-lg">📝</span>
                <h3 className="font-semibold">Wiadomość od klienta</h3>
                <span className="text-xs text-muted-foreground">
                  AI wyciągnie filtry (make, model, rocznik, budżet, przebieg, etc.)
                </span>
              </div>
              <Textarea
                placeholder='np. "Szukam BMW M5 z 2018-2020, najlepiej East Coast, budżet 30k USD, do 60 tys mil"'
                value={clientMessage}
                onChange={(e) => setClientMessage(e.target.value)}
                rows={3}
                className="mb-3"
              />
              <div className="flex items-center gap-3">
                <Button onClick={handleParseMessage} disabled={parsing || !clientMessage.trim()}>
                  {parsing ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : <span className="mr-1">🤖</span>}
                  {parsing ? "Parsuję..." : "Parsuj filtry"}
                </Button>
              </div>
              {lastParseResult && (
                <div className="mt-3 p-3 rounded-md bg-muted/50">
                  <div className="text-sm mb-2 italic">{lastParseResult.summary}</div>
                  {lastParseResult.warnings.length > 0 && (
                    <div className="mt-2 p-2 bg-amber-500/10 border border-amber-500/40 rounded">
                      <div className="text-xs font-semibold mb-1">⚠️ Normalizacja modeli:</div>
                      {lastParseResult.warnings.map((w, i) => (
                        <div key={i} className="text-xs text-amber-700 dark:text-amber-400">• {w}</div>
                      ))}
                      <div className="text-xs text-muted-foreground mt-1 italic">
                        Backend automatycznie znormalizował model do nazwy używanej przez Copart/IAAI
                        (np. M440i → 4 Series). Cache zapisuje mapping żeby kolejne te same modele
                        nie wymagały re-parsingu.
                      </div>
                    </div>
                  )}
                  {parsedCars && parsedCars.criteria_list.length > 1 && (
                    <div className="mt-3 space-y-2">
                      <div className="text-xs text-muted-foreground">
                        Wykryto <span className="font-bold text-foreground">{parsedCars.criteria_list.length}</span> aut:{" "}
                        {parsedCars.criteria_list.map((c, i) => (
                          <Badge key={i} variant="outline" className="mr-1 text-[10px]">
                            {c.make} {c.model || ""} {c.year_from ? `${c.year_from}` : ""}{c.year_to ? `-${c.year_to}` : ""}
                          </Badge>
                        ))}
                      </div>
                      <Button onClick={handleBatchSearch} size="sm">
                        <Search className="h-4 w-4 mr-1" />
                        Wyszukaj wszystkie ({parsedCars.criteria_list.length})
                      </Button>
                    </div>
                  )}
                </div>
              )}
            </Card>

            {/* Batch jobs panel */}
            {batchJobs.length > 0 && (
              <Card className="p-4 mb-4 border-primary/30">
                <div className="flex items-center justify-between mb-3">
                  <div className="flex items-center gap-2">
                    <span className="text-lg">📦</span>
                    <h3 className="font-semibold">Batch wyszukiwanie</h3>
                    <Badge variant="outline" className="text-[10px]">
                      {batchJobs.filter((j) => j.status === "done").length}/{batchJobs.length} gotowe
                    </Badge>
                  </div>
                  {batchJobs.every((j) => j.status === "done" || j.status === "error" || j.status === "cancelled") && (
                    <Button size="sm" variant="ghost" onClick={() => setBatchJobs([])}>
                      <X className="h-3.5 w-3.5 mr-1" /> Zamknij
                    </Button>
                  )}
                </div>
                <div className="grid gap-2 sm:grid-cols-2">
                  {batchJobs.map((job) => (
                    <BatchJobCard key={job.jobId} job={job} onPollUpdate={handleBatchJobUpdate} />
                  ))}
                </div>
              </Card>
            )}

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
              <Field label="Budżet USD">
                <Input
                  type="number"
                  placeholder="(opcjonalne)"
                  value={criteria.budget_usd ?? ""}
                  onChange={(e) => setCriteria({ ...criteria, budget_usd: e.target.value ? +e.target.value : null })}
                />
              </Field>
              <Field label="Max przebieg (mil)">
                <Input
                  type="number"
                  placeholder="(opcjonalne)"
                  value={criteria.max_odometer_mi ?? ""}
                  onChange={(e) =>
                    setCriteria({ ...criteria, max_odometer_mi: e.target.value ? +e.target.value : null })
                  }
                />
              </Field>
              <Field label="Rodzaj paliwa (opcjonalnie)">
                <Select
                  value={criteria.fuel_type ?? "any"}
                  onValueChange={(v) =>
                    setCriteria({
                      ...criteria,
                      fuel_type: v === "any" ? null : (v as "Gas" | "Hybrid" | "Diesel" | "Electric"),
                    })
                  }
                >
                  <SelectTrigger>
                    <SelectValue placeholder="(dowolny)" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="any">(dowolny)</SelectItem>
                    <SelectItem value="Gas">Gas</SelectItem>
                    <SelectItem value="Hybrid">Hybrid</SelectItem>
                    <SelectItem value="Diesel">Diesel</SelectItem>
                    <SelectItem value="Electric">Electric</SelectItem>
                  </SelectContent>
                </Select>
              </Field>

              <Field label="Max wyników (maks. 15)">
                <Input
                  type="number"
                  min={1}
                  max={15}
                  placeholder="Maks. 15"
                  value={criteria.max_results ?? 15}
                  onChange={(e) => {
                    const raw = +e.target.value;
                    if (!raw) return setCriteria({ ...criteria, max_results: 15 });
                    const clamped = Math.min(Math.max(raw, 1), 15);
                    setCriteria({ ...criteria, max_results: clamped });
                  }}
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
              <div className="flex items-center gap-3">
                <label
                  className="flex items-center gap-2 text-xs text-muted-foreground cursor-pointer select-none"
                  title="Domyślnie pokazujemy aukcje kończące się w ciągu 12–120h. Włącz, aby znaleźć też aukcje dalej w przyszłości oraz loty bez ustalonej daty aukcji."
                >
                  <Checkbox
                    checked={disableAuctionFilter}
                    onCheckedChange={(v) => setDisableAuctionFilter(v === true)}
                  />
                  Pokaż też aukcje przyszłe (poza oknem 12–120h)
                </label>

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
            </div>
            <ResumeJobBanner
              pendingResume={pendingResume}
              validationErrors={resumeValidationErrors}
              onResume={resumeScrapeJob}
              onDismiss={dismissResume}
              onClearErrors={() => setResumeValidationErrors([])}
            />
            {scrapeJob && (
              <ScraperProgress
                job={scrapeJob}
                onCancel={requestCancelScrape}
                onDownloadLogs={downloadJobLogs}
                onRerun={callScraper}
                rerunDisabled={busy === "scraper"}
              />
            )}
            <AlertDialog open={showCancelConfirm} onOpenChange={setShowCancelConfirm}>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>Anulować wznowiony job?</AlertDialogTitle>
                  <AlertDialogDescription>
                    Ten job został wznowiony po przeładowaniu strony. Anulowanie przerwie trwający proces scrapowania — tej operacji nie można cofnąć.
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel>Nie, kontynuuj</AlertDialogCancel>
                  <AlertDialogAction onClick={confirmCancelScrape} className="bg-destructive text-destructive-foreground hover:bg-destructive/90">
                    Tak, anuluj
                  </AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
            <Textarea
              className="font-mono text-xs"
              rows={6}
              placeholder='Wklej tutaj JSON z lotami: [{"source":"copart","lot_id":"123","year":2020,...}]'
              value={listingsRaw}
              onChange={(e) => setListingsRaw(e.target.value)}
            />
            {listings.length > 0 && (
              <ListingsTable
                listings={listings}
              />
            )}

            {scrapeJob?.status === "done" && scrapeJob.reportUrls && (
              <ScraperReportsSection
                reportUrls={scrapeJob.reportUrls}
                listings={listings}
                criteria={criteria}
              />
            )}

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

          {analysis && analysis.length > 0 && (() => {
            const showcase = analysis.filter((a) => a.is_top_recommendation);
            const rest = analysis.filter((a) => !a.is_top_recommendation);
            const showcaseCount = showcase.length;

            function auctionBadge(dateStr?: string | null) {
              if (!dateStr) return null;
              const diff = Math.ceil((new Date(dateStr).getTime() - Date.now()) / 86400000);
              if (diff <= 0) return null;
              const label = diff === 1 ? "⏰ jutro" : diff <= 3 ? `⏰ za ${diff} dni` : null;
              if (!label) return null;
              return <Badge variant="outline" className="text-[10px] ml-1">{label}</Badge>;
            }

            function LotCard({ a }: { a: AnalyzedLot }) {
              return (
                <div className="rounded-md border p-3">
                  <div className="mb-2 flex items-start justify-between">
                    <div>
                      <div className="font-semibold">
                        {a.lot.year} {a.lot.make} {a.lot.model}
                      </div>
                      <div className="text-xs text-muted-foreground">
                        {a.lot.source?.toUpperCase()} · Lot {a.lot.lot_id} · {a.lot.location_state ?? "—"}
                        {a.lot.auction_date && <span className="ml-1">· Aukcja: {new Date(a.lot.auction_date).toLocaleDateString("pl-PL")}</span>}
                        {auctionBadge(a.lot.auction_date)}
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
                    <div className="flex gap-2">
                      {a.auto_reports?.client_hybrid_url && (
                        <Button size="sm" variant="outline" asChild>
                          <a href={a.auto_reports.client_hybrid_url} target="_blank" rel="noopener">
                            📄 Klient
                          </a>
                        </Button>
                      )}
                      {a.auto_reports?.broker_hybrid_url && (
                        <Button size="sm" variant="outline" asChild>
                          <a href={a.auto_reports.broker_hybrid_url} target="_blank" rel="noopener">
                            📋 Broker
                          </a>
                        </Button>
                      )}
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
              );
            }

            return (
              <>
                {showcaseCount > 0 && (
                  <Card className="p-4">
                    <div className="mb-3 flex items-center justify-between">
                      <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
                        🎯 Showcase — auto-raporty ({showcaseCount})
                      </h3>
                      <Badge>🤖 Auto-raporty: {showcaseCount} wygenerowanych</Badge>
                    </div>
                    <div className="space-y-3">
                      {showcase
                        .sort((a, b) => {
                          const da = a.lot.auction_date ? new Date(a.lot.auction_date).getTime() : Infinity;
                          const db = b.lot.auction_date ? new Date(b.lot.auction_date).getTime() : Infinity;
                          return da - db;
                        })
                        .map((a) => <LotCard key={a.lot.lot_id} a={a} />)}
                    </div>
                  </Card>
                )}

                {rest.length > 0 && (
                  <Card className="p-4">
                    <details>
                      <summary className="cursor-pointer text-sm font-semibold uppercase tracking-wide text-muted-foreground">
                        📋 Pełna lista ({rest.length} pozostałych)
                      </summary>
                      <div className="mt-3 space-y-3">
                        {rest.map((a) => <LotCard key={a.lot.lot_id} a={a} />)}
                      </div>
                    </details>
                  </Card>
                )}

                {showcaseCount === 0 && (
                  <Card className="p-4">
                    <div className="mb-3 flex items-center justify-between">
                      <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
                        Wyniki analizy AI ({analysis.length})
                      </h3>
                      {aiMeta && (
                        <div className="flex items-center gap-2 text-xs">
                          <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 font-medium ${
                            aiMeta.provider === "gemini"
                              ? "bg-blue-500/15 text-blue-700 dark:text-blue-400"
                              : "bg-amber-500/15 text-amber-700 dark:text-amber-400"
                          }`}>
                            {aiMeta.provider === "gemini" ? "Gemini" : "Anthropic"}
                            {aiMeta.usedFallback && " (fallback)"}
                          </span>
                          <span className="text-muted-foreground" title={`Model: ${aiMeta.model}`}>
                            {aiMeta.model}
                          </span>
                          <span className="text-muted-foreground">
                            {aiMeta.usage.input_tokens + aiMeta.usage.output_tokens} tok
                          </span>
                        </div>
                      )}
                    </div>
                    <div className="space-y-3">
                      {analysis.map((a) => <LotCard key={a.lot.lot_id} a={a} />)}
                    </div>
                  </Card>
                )}
              </>
            );
          })()}

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

          </>
        </section>
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

function ScraperReportsSection({
  reportUrls,
  listings,
  criteria,
}: {
  reportUrls: ScraperReportUrls;
  listings: CarLot[];
  criteria: ClientCriteria;
}) {
  const [loadingEndpoint, setLoadingEndpoint] = useState<string | null>(null);

  const hasAny =
    reportUrls.client_report_url ||
    reportUrls.polecane_index_url ||
    (reportUrls.client_reports_html?.length ?? 0) > 0 ||
    (reportUrls.broker_reports_html?.length ?? 0) > 0 ||
    reportUrls.artifact_urls?.analysis_json ||
    reportUrls.artifact_urls?.broker_bundle ||
    reportUrls.artifact_urls?.client_bundle ||
    reportUrls.artifact_urls?.client_short_bundle ||
    reportUrls.report_endpoints?.client_html ||
    reportUrls.report_endpoints?.broker_html;

  if (!hasAny) return null;

  async function openHtmlReport(endpoint: string, label: string) {
    setLoadingEndpoint(label);
    try {
      const res = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ criteria, listings }),
      });
      if (!res.ok) {
        const errText = await res.text().catch(() => "");
        throw new Error(`HTTP ${res.status}: ${errText.slice(0, 200)}`);
      }
      const html = await res.text();
      const blob = new Blob([html], { type: "text/html;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      window.open(url, "_blank");
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch (e) {
      toast.error(`Błąd generowania raportu: ${(e as Error).message}`);
    } finally {
      setLoadingEndpoint(null);
    }
  }

  return (
    <Card className="mt-4 p-4">
      <div className="flex items-center gap-2 mb-3">
        <FileText className="h-4 w-4 text-primary" />
        <span className="font-semibold text-sm">Raporty z analizy AI (Python)</span>
      </div>
      <div className="flex flex-wrap gap-2">
        {reportUrls.polecane_index_url && (
          <Button variant="default" size="sm"
            onClick={() => window.open(reportUrls.polecane_index_url, "_blank")}>
            <ExternalLink className="h-3.5 w-3.5" />
            🎯 Polecane oferty (klient + broker)
          </Button>
        )}
        {(reportUrls.client_reports_html?.length ?? 0) > 0 && reportUrls.client_reports_html!.map((url, i) => (
          <Button key={`client-${i}`} variant="outline" size="sm"
            onClick={() => window.open(url, "_blank")}>
            <ExternalLink className="h-3.5 w-3.5" />
            📄 Klient #{i + 1}
          </Button>
        ))}
        {(reportUrls.broker_reports_html?.length ?? 0) > 0 && reportUrls.broker_reports_html!.map((url, i) => (
          <Button key={`broker-${i}`} variant="outline" size="sm"
            onClick={() => window.open(url, "_blank")}>
            <ExternalLink className="h-3.5 w-3.5" />
            📊 Broker #{i + 1}
          </Button>
        ))}
        {reportUrls.client_report_url && (
          <Button variant="outline" size="sm"
            onClick={() => window.open(reportUrls.client_report_url, "_blank")}>
            <Download className="h-3.5 w-3.5" />
            Pobierz raport klienta (Markdown)
          </Button>
        )}
        {reportUrls.artifact_urls?.analysis_json && (
          <Button variant="outline" size="sm"
            onClick={() => window.open(reportUrls.artifact_urls!.analysis_json, "_blank")}>
            <Download className="h-3.5 w-3.5" />
            Pobierz pełną analizę (JSON)
          </Button>
        )}
        {reportUrls.artifact_urls?.broker_bundle && (
          <Button variant="default" size="sm"
            onClick={() => window.open(reportUrls.artifact_urls!.broker_bundle, "_blank")}>
            <ExternalLink className="h-3.5 w-3.5" />
            📋 Zbiorczy raport brokerski (audyt wszystkich pojazdów)
          </Button>
        )}
        {reportUrls.artifact_urls?.client_bundle && (
          <Button variant="outline" size="sm"
            onClick={() => window.open(reportUrls.artifact_urls!.client_bundle, "_blank")}>
            <ExternalLink className="h-3.5 w-3.5" />
            📄 Zbiorczy klient
          </Button>
        )}
        {reportUrls.artifact_urls?.client_short_bundle && (
          <Button variant="outline" size="sm"
            onClick={() => window.open(reportUrls.artifact_urls!.client_short_bundle, "_blank")}>
            <ExternalLink className="h-3.5 w-3.5" />
            ⚡ Zbiorczy krótki klient
          </Button>
        )}
        {reportUrls.report_endpoints?.client_html && (
          <Button variant="outline" size="sm"
            disabled={loadingEndpoint === "client"}
            onClick={() => openHtmlReport(reportUrls.report_endpoints!.client_html!, "client")}>
            {loadingEndpoint === "client" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <ExternalLink className="h-3.5 w-3.5" />}
            Generuj raport HTML klienta
          </Button>
        )}
        {reportUrls.report_endpoints?.broker_html && (
          <Button variant="outline" size="sm"
            disabled={loadingEndpoint === "broker"}
            onClick={() => openHtmlReport(reportUrls.report_endpoints!.broker_html!, "broker")}>
            {loadingEndpoint === "broker" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <ExternalLink className="h-3.5 w-3.5" />}
            Generuj raport HTML brokera
          </Button>
        )}
      </div>
    </Card>
  );
}

function ListingsTable({
  listings,
  selectedIds,
  onToggle,
  onToggleAll,
}: {
  listings: CarLot[];
  selectedIds?: Set<string>;
  onToggle?: (lotId: string) => void;
  onToggleAll?: () => void;
}) {
  const selectionMode = !!selectedIds && !!onToggle;
  const allSelected = selectionMode && listings.length > 0 && listings.every((l) => selectedIds!.has(l.lot_id));
  return (
    <div className="mt-3 max-h-[260px] overflow-auto rounded border">
      <table className="w-full text-xs">
        <thead className="sticky top-0 bg-muted">
          <tr className="text-left">
            {selectionMode && (
              <th className="w-8 px-2 py-1.5">
                <input
                  type="checkbox"
                  checked={allSelected}
                  onChange={() => onToggleAll?.()}
                  title={allSelected ? "Odznacz wszystkie" : "Zaznacz wszystkie"}
                />
              </th>
            )}
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
          {listings.map((l) => {
            const checked = selectionMode && selectedIds!.has(l.lot_id);
            return (
              <tr
                key={`${l.source}-${l.lot_id}`}
                className={`border-t ${checked ? "bg-primary/5" : ""}`}
              >
                {selectionMode && (
                  <td className="px-2 py-1">
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={() => onToggle!(l.lot_id)}
                    />
                  </td>
                )}
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
            );
          })}
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
                <option value="anthropic">Anthropic Claude</option>
                <option value="gemini">Google Gemini</option>
                <option value="auto">Auto (wykryj wg kluczy)</option>
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

// ConnectionStatusPanel przeniesiony do src/components/panels/connection-status-panel.tsx (route /jobs).
