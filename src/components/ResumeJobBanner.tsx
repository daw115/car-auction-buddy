import { RefreshCw, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { ValidatedScrapeJob } from "@/lib/scrape-job-storage";

/** Human-readable elapsed time in Polish */
export function formatElapsed(ms: number): string {
  const s = Math.max(0, Math.floor(ms / 1000));
  if (s < 60) return `${s}s temu`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}min temu`;
  const h = Math.floor(m / 60);
  const rm = m % 60;
  return rm > 0 ? `${h}h ${rm}min temu` : `${h}h temu`;
}

export interface ResumeJobBannerProps {
  pendingResume: ValidatedScrapeJob | null;
  validationErrors: string[];
  onResume: () => void;
  onDismiss: () => void;
  onClearErrors: () => void;
}

export function ResumeJobBanner({
  pendingResume,
  validationErrors,
  onResume,
  onDismiss,
  onClearErrors,
}: ResumeJobBannerProps) {
  if (validationErrors.length > 0 && !pendingResume) {
    return (
      <div className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs space-y-1">
        <div className="flex items-center gap-2 font-medium text-destructive">
          <X className="h-3.5 w-3.5" />
          Zapisane kryteria scrapera były nieprawidłowe — dane wyczyszczone.
        </div>
        <ul className="list-disc pl-5 text-muted-foreground">
          {validationErrors.map((e, i) => (
            <li key={i}>{e}</li>
          ))}
        </ul>
        <Button size="sm" variant="ghost" className="h-5 px-1 text-xs" onClick={onClearErrors}>
          Zamknij
        </Button>
      </div>
    );
  }

  if (!pendingResume) return null;

  return (
    <div className="rounded-md border border-primary/30 bg-primary/5 px-3 py-2 space-y-1.5">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2 text-xs">
          <RefreshCw className="h-3.5 w-3.5 text-primary" />
          <span>
            Wykryto aktywny job scrapera{" "}
            <span className="font-mono text-muted-foreground">
              #{pendingResume.jobId.slice(0, 8)}
            </span>{" "}
            sprzed przeładowania strony.
          </span>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <Button size="sm" variant="outline" className="h-6 px-2 text-xs" onClick={onDismiss}>
            <X className="h-3 w-3 mr-1" />
            Odrzuć
          </Button>
          <Button size="sm" className="h-6 px-2 text-xs" onClick={onResume}>
            <RefreshCw className="h-3 w-3 mr-1" />
            Wznów
          </Button>
        </div>
      </div>
      <div className="text-[10px] text-muted-foreground flex flex-wrap gap-x-3 gap-y-0.5 pl-5">
        <span>
          Marka: <strong>{pendingResume.criteria.make}</strong>
        </span>
        {pendingResume.criteria.model && (
          <span>
            Model: <strong>{pendingResume.criteria.model}</strong>
          </span>
        )}
        <span>
          Budżet: <strong>${pendingResume.criteria.budget_usd.toLocaleString()}</strong>
        </span>
        {pendingResume.criteria.year_from && (
          <span>
            Od: <strong>{pendingResume.criteria.year_from}</strong>
          </span>
        )}
        {pendingResume.criteria.year_to && (
          <span>
            Do: <strong>{pendingResume.criteria.year_to}</strong>
          </span>
        )}
      </div>
    </div>
  );
}
