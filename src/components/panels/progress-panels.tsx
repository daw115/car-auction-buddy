import { Loader2, AlertCircle, X, CheckCircle2, Download, RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";

// ---------- Shared types ----------

export type ScraperReportUrls = {
  json_url?: string | null;
  csv_url?: string | null;
  ndjson_url?: string | null;
  parquet_url?: string | null;
};

export type ScrapeJobState = {
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

export type AnalysisPhase = "queued" | "analyzing" | "rendering" | "saving" | "done" | "failed" | "cancelled";

export type AnalysisJobState = {
  phase: AnalysisPhase;
  lastPhase?: AnalysisPhase;
  startedAt: number;
  elapsedMs: number;
  lotsCount?: number;
  errorMessage?: string;
};

// ---------- Helpers ----------

export function formatDuration(ms: number): string {
  const s = Math.max(0, Math.floor(ms / 1000));
  const m = Math.floor(s / 60);
  const r = s % 60;
  return m > 0 ? `${m}m ${r}s` : `${r}s`;
}

export const PHASE_BADGE_COLORS: Record<string, string> = {
  queued:            "bg-muted text-muted-foreground",
  starting:          "bg-[oklch(0.92_0.06_250)] text-[oklch(0.35_0.12_250)]",
  initializing:      "bg-[oklch(0.92_0.06_250)] text-[oklch(0.35_0.12_250)]",
  running:           "bg-[oklch(0.90_0.08_250)] text-[oklch(0.30_0.14_250)]",
  scraping:          "bg-[oklch(0.90_0.08_280)] text-[oklch(0.30_0.14_280)]",
  scraping_list:     "bg-[oklch(0.90_0.08_280)] text-[oklch(0.30_0.14_280)]",
  scraping_details:  "bg-[oklch(0.88_0.10_280)] text-[oklch(0.28_0.16_280)]",
  enriching:         "bg-[oklch(0.90_0.08_60)] text-[oklch(0.32_0.12_60)]",
  parsing:           "bg-[oklch(0.90_0.08_200)] text-[oklch(0.32_0.12_200)]",
  analyzing:         "bg-[oklch(0.88_0.10_280)] text-[oklch(0.28_0.16_280)]",
  rendering:         "bg-[oklch(0.90_0.08_60)] text-[oklch(0.32_0.12_60)]",
  saving:            "bg-[oklch(0.90_0.08_200)] text-[oklch(0.32_0.12_200)]",
  done:              "bg-[oklch(0.92_0.08_145)] text-[oklch(0.30_0.10_145)]",
  completed:         "bg-[oklch(0.92_0.08_145)] text-[oklch(0.30_0.10_145)]",
  finished:          "bg-[oklch(0.92_0.08_145)] text-[oklch(0.30_0.10_145)]",
  failed:            "bg-destructive/15 text-destructive",
  error:             "bg-destructive/15 text-destructive",
  cancelled:         "bg-muted text-muted-foreground",
};

export function PhaseBadge({ phase, active }: { phase: string; active: boolean }) {
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

export function isScraper404(raw: string): boolean {
  const l = raw.toLowerCase();
  return (l.includes("404") && (l.includes("scraper") || l.includes("not found")));
}

export function humanizeError(raw: string): string {
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

// ---------- ScraperProgress ----------

export function ScraperProgress({
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
      {(() => {
        const scraperPhases = ["queued", "running", "scraping_list", "scraping_details", "enriching", "parsing", "done"];
        const currentPhaseKey = job.status;
        const currentIdx = scraperPhases.indexOf(currentPhaseKey);

        if (isFailed) {
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

// ---------- AnalysisProgress ----------

export function AnalysisProgress({ job }: { job: AnalysisJobState }) {
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
