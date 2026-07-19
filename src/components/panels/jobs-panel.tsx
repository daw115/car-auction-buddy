import { useServerFn } from "@tanstack/react-start";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";

import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { LiveJobLogs } from "@/components/LiveJobLogs";
import { backendListJobs, backendCancelJob } from "@/functions/backend.functions";
import { isAuctionSource } from "@/lib/auction-sources";

// ---- Active Jobs types ----
export type ActiveJob = {
  id: string;
  label: string;
  status: "queued" | "running" | "done" | "error" | "cancelled" | "interrupted";
  phase?: string | null;
  phase_info?: Record<string, any>;
  phases?: Array<{
    name: string;
    status: string;
    info?: Record<string, any>;
    started_at: string;
    finished_at?: string | null;
  }>;
  criteria?: Record<string, any>;
  created_at: string;
  finished_at?: string | null;
  listings_count?: number;
  analysis_notice?: string | null;
};

const PHASE_LABELS: Record<string, string> = {
  copart: "Copart",
  iaai: "IAAI",
  manheim: "Manheim",
  filter: "Filtrowanie",
  enrich: "Wzbogacanie",
  ai_analyze: "Analiza AI",
  reports_generate: "Generowanie raportów",
  queued: "W kolejce",
};

function phaseLine(p: { name: string; status: string; info?: Record<string, any> }): string {
  const i = p.info || {};
  const label = PHASE_LABELS[p.name] || p.name;
  if (isAuctionSource(p.name)) {
    if (i.count !== undefined) return `${label}: ${i.count} lotów`;
    if (i.make) return `${label}: szukam ${i.make} ${i.model || ""}`;
  }
  if (p.name === "filter" && i.output !== undefined) return `${label}: ${i.input} → ${i.output} lotów`;
  if (p.name === "ai_analyze") {
    if (i.ranked) return `${label}: ${i.ranked} ocenione`;
    if (i.lots) return `${label}: ${i.lots} lotów...`;
  }
  if (p.name === "reports_generate") {
    if (i.generated) return `${label}: ${i.generated}/${i.total} gotowych`;
    if (i.current) return `${label}: ${i.current}/${i.total}: ${i.lot || ""}`;
  }
  return label;
}

export function ActiveJobsPanel({ emptyState }: { emptyState?: React.ReactNode } = {}) {
  const fnListActive = useServerFn(backendListJobs);
  const fnCancel = useServerFn(backendCancelJob);

  const { data: activeJobs } = useQuery({
    queryKey: ["active-jobs"],
    queryFn: () => fnListActive({ data: { activeOnly: true } }),
    refetchInterval: 2000,
  });

  const jobs = activeJobs?.jobs ?? [];

  if (jobs.length === 0) {
    if (emptyState !== undefined) return <>{emptyState}</>;
    return null;
  }

  const handleCancel = async (id: string) => {
    try {
      await fnCancel({ data: { jobId: id } });
      toast.success("Job anulowany");
    } catch (e) {
      toast.error(`Anulowanie nie powiodło się: ${(e as Error).message}`);
    }
  };

  return (
    <Card className="p-3 bg-blue-500/5 border-blue-500/30">
      <h3 className="font-semibold mb-3">
        🔄 Aktywne zadania ({jobs.length})
      </h3>
      <div className="space-y-3">
        {jobs.map((job) => (
          <ActiveJobRow key={job.id} job={job as ActiveJob} onCancel={handleCancel} />
        ))}
      </div>
    </Card>
  );
}

function ActiveJobRow({ job, onCancel }: { job: ActiveJob; onCancel: (id: string) => void }) {
  const isRunning = job.status === "running";

  return (
    <div className={`p-2 rounded border ${
      job.status === "running" ? "bg-blue-500/10 border-blue-500/40" :
      job.status === "queued"  ? "bg-muted/30 border-border" :
      job.status === "done"    ? "bg-green-500/5 border-green-500/30" :
      job.status === "error"   ? "bg-destructive/5 border-destructive/30" :
      "bg-muted/30 border-border"
    }`}>
      <div className="flex items-center justify-between mb-1">
        <span className="font-semibold text-sm">{job.label}</span>
        <div className="flex items-center gap-2">
          <Badge variant={job.status === "running" ? "default" : "outline"}>
            {job.status === "queued" ? "⏳ w kolejce" :
             job.status === "running" ? "🔄 w toku" :
             job.status === "done" ? "✅ gotowe" :
             job.status === "error" ? "❌ błąd" : job.status}
          </Badge>
          {(isRunning || job.status === "queued") && (
            <Button size="sm" variant="ghost" className="h-6 px-2"
                    onClick={() => onCancel(job.id)}>⛔</Button>
          )}
        </div>
      </div>

      {job.phases && job.phases.length > 0 && (
        <div className="space-y-0.5 mt-1 text-xs font-mono text-muted-foreground">
          {job.phases.map((p, i) => (
            <div key={i} className="flex items-center gap-2">
              <span>{
                p.status === "done" ? "✅" :
                p.status === "running" ? "🔄" :
                p.status === "blocked" ? "🚫" :
                p.status === "error" ? "❌" :
                p.status === "skipped" ? "⏭" : "⏳"
              }</span>
              <span>{phaseLine(p)}</span>
            </div>
          ))}
        </div>
      )}

      {(!job.phases || job.phases.length === 0) && job.phase && (
        <div className="text-[11px] text-muted-foreground">
          Faza: <span className="font-medium text-foreground">{job.phase}</span>
        </div>
      )}

      {job.listings_count != null && (
        <div className="text-[11px] text-muted-foreground">
          Znaleziono: <span className="font-medium text-foreground">{job.listings_count}</span> lotów
        </div>
      )}

      {job.status === "done" && job.listings_count != null && job.listings_count <= 2 && (
        <div className="mt-2 p-2 bg-amber-500/10 border border-amber-500/40 rounded text-xs">
          <div className="font-semibold text-amber-700 dark:text-amber-400">⚠️ Mało wyników ({job.listings_count} lotów)</div>
          <div className="text-muted-foreground whitespace-pre-line mt-1">
            {job.analysis_notice || "Sprawdź czy nazwa modelu jest poprawna."}
          </div>
        </div>
      )}

      {["running", "scraping", "scraping_list", "scraping_details", "enriching", "parsing", "ai_analyzing", "generating_reports", "in_progress"].includes(job.status) && (
        <LiveJobLogs jobId={String(job.id)} active={true} />
      )}
    </div>
  );
}
