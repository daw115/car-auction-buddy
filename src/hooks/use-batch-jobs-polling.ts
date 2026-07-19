import { useEffect, useMemo, useRef, useState } from "react";
import { useServerFn } from "@tanstack/react-start";
import { backendJobStatus, type BackendJobStatus } from "@/functions/backend.functions";

// Backend top-level job.status kontrakt:
//   "queued" | "running" | "done" | "error" | "cancelled" | "interrupted"
// 'interrupted' = backend zrestartował się w trakcie (np. deploy) — traktujemy
// jak błąd terminalny (osobny licznik dla UX), NIE zawieszamy pollingu.
export const TERMINAL_STATUSES = [
  "done",
  "completed", // niektóre stare payloady
  "error",
  "failed",
  "cancelled",
  "interrupted",
] as const;

export function isTerminalStatus(status?: string | null): boolean {
  return !!status && (TERMINAL_STATUSES as readonly string[]).includes(status);
}

export type BatchJobsPollingState = {
  /** map jobId -> ostatni JobStatus */
  jobs: Record<string, BackendJobStatus>;
  done: number;
  running: number;
  queued: number;
  errored: number;
  interrupted: number;
  allFinished: boolean;
};

/**
 * Pojedynczy interval odpytujący WSZYSTKIE joby jednym Promise.allSettled.
 * Zatrzymuje się gdy każdy jobId osiągnie status z TERMINAL_STATUSES.
 */
export function useBatchJobsPolling(
  jobIds: string[],
  intervalMs: number = 2500,
): BatchJobsPollingState {
  const [jobs, setJobs] = useState<Record<string, BackendJobStatus>>({});
  const jobsRef = useRef(jobs);
  jobsRef.current = jobs;

  const idsKey = jobIds.join("|");
  const statusFn = useServerFn(backendJobStatus);

  useEffect(() => {
    if (jobIds.length === 0) return;

    let cancelled = false;
    let handle: ReturnType<typeof setInterval> | null = null;

    const stop = () => {
      if (handle !== null) {
        clearInterval(handle);
        handle = null;
      }
    };

    const tick = async () => {
      if (cancelled) return;
      const currentJobs = jobsRef.current;
      const pending = jobIds.filter((id) => !isTerminalStatus(currentJobs[id]?.status));
      if (pending.length === 0) {
        stop();
        return;
      }

      const results = await Promise.allSettled(
        pending.map((id) => statusFn({ data: { jobId: id } })),
      );
      if (cancelled) return;

      setJobs((prev) => {
        const next = { ...prev };
        results.forEach((r, i) => {
          const id = pending[i];
          if (r.status === "fulfilled" && r.value) {
            next[id] = r.value;
          }
          // odrzucony fetch (network hiccup) — nie zmieniamy, spróbujemy ponownie w kolejnym ticku
        });
        jobsRef.current = next;
        return next;
      });

      // po update sprawdź czy wszystko już terminalne
      const after = jobsRef.current;
      if (jobIds.every((id) => isTerminalStatus(after[id]?.status))) {
        stop();
      }
    };

    void tick(); // natychmiast, bez czekania na pierwszy tick
    handle = setInterval(() => {
      void tick();
    }, intervalMs);

    return () => {
      cancelled = true;
      stop();
    };
  }, [idsKey, intervalMs, statusFn]); // eslint-disable-line react-hooks/exhaustive-deps

  return useMemo<BatchJobsPollingState>(() => {
    let done = 0;
    let running = 0;
    let queued = 0;
    let errored = 0;
    let interrupted = 0;
    for (const id of jobIds) {
      const s = jobs[id]?.status;
      switch (s) {
        case "done":
        case "completed":
          done++;
          break;
        case "running":
          running++;
          break;
        case "queued":
        case undefined:
          queued++;
          break;
        case "interrupted":
          interrupted++;
          break;
        case "error":
        case "failed":
        case "cancelled":
          errored++;
          break;
        default:
          running++; // nieznany status traktujemy jak w toku
      }
    }
    const allFinished =
      jobIds.length > 0 &&
      jobIds.every((id) => isTerminalStatus(jobs[id]?.status));

    return { jobs, done, running, queued, errored, interrupted, allFinished };
  }, [jobs, idsKey]); // eslint-disable-line react-hooks/exhaustive-deps
}
