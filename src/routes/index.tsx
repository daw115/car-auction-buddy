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

// recommendationBadge -> @/components/panels/analysis-results

import type { ScraperReportUrls } from "@/components/panels/batch-job-card";
import {
  ScraperProgress,
  AnalysisProgress,
  formatDuration,
  humanizeError,
  isScraper404,
  type ScrapeJobState,
  type AnalysisJobState,
  type AnalysisPhase,
} from "@/components/panels/progress-panels";
import { Field, DownloadBtn } from "@/components/panels/form-helpers";
import { ListingsTable } from "@/components/panels/listings-table";
import { ScraperReportsSection } from "@/components/panels/scraper-reports-section";
import { CriteriaForm } from "@/components/panels/criteria-form";
import { AnalysisResults } from "@/components/panels/analysis-results";
import { ClientsAside } from "@/components/panels/clients-aside";

// ActiveJobsPanel / ActiveJobRow / phaseLine / PHASE_LABELS / ActiveJob
// zostały przeniesione do src/components/panels/jobs-panel.tsx (route /jobs).


// ---------- Batch search types + card ----------
// BatchJobCard + BatchJobEntry przeniesione do src/components/panels/batch-job-card.tsx
import { type BatchJobEntry } from "@/components/panels/batch-job-card";
import { ClientMessageCard, type ParsedCarsResult } from "@/components/panels/client-message-card";
import { BatchJobsPanel } from "@/components/panels/batch-jobs-panel";



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
  // fnUpdateConfig usunięty wraz z SettingsSheet (pełne ustawienia są na /settings)
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
    <div className="text-foreground">
      {/* Sub-header usunięty — ustawienia masz na /settings, status połączeń na /jobs */}



      <main className="grid grid-cols-1 gap-4 p-4 sm:p-6 lg:grid-cols-[300px_minmax(0,1fr)]">
        {/* ---- Clients column ---- */}
        <ClientsAside
          clients={clients}
          activeClientId={activeClientId}
          newName={newName}
          newContact={newContact}
          newNotes={newNotes}
          busy={busy}
          setNewName={setNewName}
          setNewContact={setNewContact}
          setNewNotes={setNewNotes}
          addClient={addClient}
          refreshClients={refreshClients}
          setActiveClientId={setActiveClientId}
          removeClient={removeClient}
        />

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

            <ClientMessageCard
              clientMessage={clientMessage}
              setClientMessage={setClientMessage}
              parsing={parsing}
              lastParseResult={lastParseResult}
              parsedCars={parsedCars}
              onParse={handleParseMessage}
              onBatchSearch={handleBatchSearch}
            />

            {/* Batch jobs panel */}
            <BatchJobsPanel
              batchJobs={batchJobs}
              onClear={() => setBatchJobs([])}
              onPollUpdate={handleBatchJobUpdate}
            />


            <CriteriaForm criteria={criteria} setCriteria={setCriteria} />

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

          {analysis && analysis.length > 0 && (
            <AnalysisResults analysis={analysis} aiMeta={aiMeta} onWatch={watchLot} />
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

          </>
        </section>
      </main>
    </div>
  );
}

// Field, DownloadBtn -> @/components/panels/form-helpers
// ScraperReportsSection -> @/components/panels/scraper-reports-section
// ListingsTable -> @/components/panels/listings-table
// EnvStatus / SettingsSheet / ToggleRow usunięte — pełne ustawienia są na /settings.
// ConnectionStatusPanel przeniesiony do src/components/panels/connection-status-panel.tsx (route /jobs).


