import { useEffect, useRef } from "react";
import { useServerFn } from "@tanstack/react-start";
import { AlertCircle, CheckCircle2, Clock, Loader2 } from "lucide-react";

import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { pollScraperJob } from "@/functions/api.functions";
import type { ClientCriteria } from "@/lib/types";

export type ScraperReportUrls = {
  client_report_url?: string;
  polecane_index_url?: string;
  client_reports_html?: string[];
  broker_reports_html?: string[];
  artifact_urls?: {
    client_report?: string;
    analysis_json?: string;
    ai_prompt?: string;
    ai_input?: string;
    polecane_index?: string;
    broker_bundle?: string;
    client_bundle?: string;
    client_short_bundle?: string;
  };
  report_endpoints?: {
    client_html?: string;
    broker_html?: string;
    client_llm?: string;
    broker_llm?: string;
    offer_email_html?: string;
    pdf?: string;
  };
};

export type BatchJobEntry = {
  jobId: string;
  label: string;
  criteria: ClientCriteria;
  status: "queued" | "running" | "done" | "error" | "cancelled";
  phase?: string | null;
  phases?: Array<{
    name: string;
    status: string;
    info?: Record<string, any>;
    started_at: string;
    finished_at?: string | null;
  }>;
  listings_count?: number;
  errorMessage?: string;
  reportUrls?: ScraperReportUrls;
};

function formatDuration(ms: number): string {
  const s = Math.max(0, Math.floor(ms / 1000));
  const m = Math.floor(s / 60);
  const r = s % 60;
  return m > 0 ? `${m}m ${r}s` : `${r}s`;
}

export function BatchJobCard({
  job,
  onPollUpdate,
}: {
  job: BatchJobEntry;
  onPollUpdate: (jobId: string, update: Partial<BatchJobEntry>) => void;
}) {
  const fnPoll = useServerFn(pollScraperJob);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (job.status === "done" || job.status === "error" || job.status === "cancelled") return;

    const poll = async () => {
      try {
        const r = (await fnPoll({ data: { jobId: job.jobId } })) as any;
        const update: Partial<BatchJobEntry> = {
          status: r.status ?? job.status,
          phase: r.phase ?? null,
          phases: r.phases ?? undefined,
          listings_count: r.listings_count ?? undefined,
          reportUrls: r.report_urls ?? r.reportUrls ?? undefined,
        };
        if (r.error) update.errorMessage = r.error;
        onPollUpdate(job.jobId, update);

        if (r.status === "done" || r.status === "error" || r.status === "cancelled") {
          if (pollRef.current) clearInterval(pollRef.current);
        }
      } catch {
        // silent — retry on next tick
      }
    };

    poll();
    pollRef.current = setInterval(poll, 2000);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job.jobId, job.status]);

  const statusColor =
    {
      queued: "bg-muted text-muted-foreground",
      running: "bg-primary/10 text-primary border-primary/30",
      done: "bg-[oklch(0.50_0.15_145)]/10 text-[oklch(0.50_0.15_145)]",
      error: "bg-destructive/10 text-destructive",
      cancelled: "bg-muted text-muted-foreground",
    }[job.status] ?? "bg-muted text-muted-foreground";

  return (
    <Card className={`p-3 space-y-2 border ${job.status === "running" ? "border-primary/30" : ""}`}>
      <div className="flex items-center justify-between text-xs">
        <div className="flex items-center gap-2 min-w-0">
          {job.status === "running" && <Loader2 className="h-3.5 w-3.5 animate-spin shrink-0 text-primary" />}
          {job.status === "done" && <CheckCircle2 className="h-3.5 w-3.5 text-[oklch(0.50_0.15_145)]" />}
          {job.status === "error" && <AlertCircle className="h-3.5 w-3.5 text-destructive" />}
          {job.status === "queued" && <Clock className="h-3.5 w-3.5 text-muted-foreground" />}
          <span className="font-medium truncate">{job.label}</span>
          <Badge variant="outline" className={`text-[10px] ${statusColor}`}>
            {job.status}
          </Badge>
        </div>
      </div>

      {job.phases && job.phases.length > 0 && (
        <div className="flex flex-wrap items-center gap-1">
          {job.phases.map((p, i) => {
            const isActive = p.status === "running";
            const isDone = p.status === "done" || p.status === "completed";
            const isFailed = p.status === "error" || p.status === "failed";
            const icon =
              {
                scraping_list: "📋",
                scraping_details: "🔍",
                enriching: "🔧",
                analyzing: "🤖",
                generating_reports: "📝",
                done: "✅",
                error: "❌",
              }[p.name] ?? "⏳";
            return (
              <span
                key={`${p.name}-${i}`}
                className={`inline-flex items-center gap-0.5 rounded px-1.5 py-0.5 text-[10px] font-medium ${
                  isFailed
                    ? "bg-destructive/20 text-destructive ring-1 ring-destructive/30"
                    : isActive
                      ? "bg-primary/20 text-primary ring-1 ring-primary/30 animate-pulse"
                      : isDone
                        ? "bg-muted text-muted-foreground"
                        : "bg-muted/50 text-muted-foreground/50"
                }`}
              >
                <span>{icon}</span>
                <span>{p.name.replace(/_/g, " ")}</span>
                {isDone && p.finished_at && p.started_at && (
                  <span className="text-muted-foreground/70">
                    ({formatDuration(new Date(p.finished_at).getTime() - new Date(p.started_at).getTime())})
                  </span>
                )}
              </span>
            );
          })}
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

      {job.errorMessage && (
        <div className="text-[11px] text-destructive truncate">{job.errorMessage}</div>
      )}
    </Card>
  );
}
