import { useEffect, useMemo, useRef, useState } from "react";

interface Props {
  jobId: string;
  active: boolean;
}

export const NOISE_RE =
  /GET \/(?:api\/(?:jobs|records|health|html-cache|llm-cache|model-normalizations|db|feedback)|health)(?=[/?\s"]|$)/;

export function isNoiseLine(line: string): boolean {
  return NOISE_RE.test(line);
}

/**
 * Returns the reason a line was filtered out, or null if it passes.
 * Used by the debug panel to show *why* a line was hidden.
 */
export function noiseReason(line: string): string | null {
  const m = line.match(NOISE_RE);
  if (!m) return null;
  // m[0] looks like "GET /api/jobs" or "GET /health"
  return `request-spam (${m[0].replace(/^GET /, "")})`;
}

export function getLineClass(line: string): string {
  if (/\b(error|ERROR|FAILED|crash)\b/i.test(line)) return "text-red-400";
  if (/\b(WARNING|WARN|fallback)\b/.test(line) || /Gemini 429/.test(line))
    return "text-yellow-400";
  if (/Wzbogacono|Broadcast.*delivered|Filtr DOM:|Auto-bundle/.test(line))
    return "text-emerald-400";
  if (/\[AI\/Bidfax\]|\[Otomoto\]|\[pre_rank\]/.test(line)) return "text-blue-400";
  return "text-zinc-300";
}

const DEBUG_STORAGE_KEY = "live-job-logs-debug";

type LogEntry = {
  data: string;
  filtered: boolean;
  reason: string | null;
};

export function LiveJobLogs({ jobId, active }: Props) {
  const [entries, setEntries] = useState<LogEntry[]>([]);
  const [connected, setConnected] = useState(false);
  const [retryAttempt, setRetryAttempt] = useState(0);
  const [debug, setDebug] = useState<boolean>(() => {
    if (typeof window === "undefined") return false;
    return window.localStorage.getItem(DEBUG_STORAGE_KEY) === "1";
  });
  const entriesRef = useRef<LogEntry[]>([]);
  const scrollRef = useRef<HTMLDivElement>(null);
  const userScrolledUpRef = useRef(false);

  useEffect(() => {
    entriesRef.current = entries;
  }, [entries]);

  useEffect(() => {
    if (typeof window !== "undefined") {
      window.localStorage.setItem(DEBUG_STORAGE_KEY, debug ? "1" : "0");
    }
  }, [debug]);

  useEffect(() => {
    if (!active) return;
    let retries = 0;
    let es: EventSource | null = null;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;
    let cancelled = false;
    let snapshotRemaining = 0;

    const connect = (isReconnect: boolean) => {
      if (cancelled) return;
      es = new EventSource("/api/scraper-logs/stream");
      snapshotRemaining =
        isReconnect && entriesRef.current.length > 0 ? 60 : 0;

      es.addEventListener("open", () => {
        setConnected(true);
        setRetryAttempt(0);
        retries = 0;
      });

      es.addEventListener("line", (e) => {
        const data = (e as MessageEvent).data as string;
        const reason = noiseReason(data);
        const filtered = reason !== null;

        if (snapshotRemaining > 0) {
          snapshotRemaining--;
          // Dedupe snapshot replay against last 100 visible entries
          const recent = entriesRef.current.slice(-100);
          if (recent.some((r) => r.data === data)) return;
        }

        setEntries((prev) => {
          const next = [...prev, { data, filtered, reason }];
          return next.length > 500 ? next.slice(-500) : next;
        });
      });

      es.onerror = () => {
        setConnected(false);
        es?.close();
        es = null;
        if (cancelled) return;
        if (retries < 5) {
          retries++;
          setRetryAttempt(retries);
          const delay = Math.min(3000 * 2 ** (retries - 1), 15000);
          retryTimer = setTimeout(() => connect(true), delay);
        }
      };
    };

    connect(false);
    return () => {
      cancelled = true;
      if (retryTimer) clearTimeout(retryTimer);
      es?.close();
      setConnected(false);
      setRetryAttempt(0);
    };
  }, [active]);

  const visible = useMemo(
    () => (debug ? entries : entries.filter((e) => !e.filtered)),
    [entries, debug],
  );
  const hiddenCount = useMemo(
    () => entries.filter((e) => e.filtered).length,
    [entries],
  );

  useEffect(() => {
    if (!userScrolledUpRef.current && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [visible]);

  const handleScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 20;
    userScrolledUpRef.current = !atBottom;
  };

  const statusLabel = connected
    ? "streaming"
    : retryAttempt > 0
      ? `łączę ponownie (${retryAttempt}/5)`
      : "rozłączone";

  return (
    <div className="bg-zinc-950 text-zinc-200 rounded-lg p-3 mt-3">
      <div className="flex items-center justify-between mb-2 gap-2">
        <span className="text-xs uppercase tracking-wider opacity-70">
          📜 Live logs · job {jobId.slice(0, 8)}
        </span>
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => setDebug((d) => !d)}
            className={`text-[10px] px-2 py-0.5 rounded border transition-colors ${
              debug
                ? "bg-amber-500/20 border-amber-500/50 text-amber-300"
                : "bg-zinc-800 border-zinc-700 text-zinc-400 hover:text-zinc-200"
            }`}
            title="Pokaż również odrzucone linie z powodem filtrowania"
          >
            🐞 debug{debug && hiddenCount > 0 ? ` (${hiddenCount})` : ""}
          </button>
          <span className="flex items-center gap-1.5 text-[10px] opacity-70">
            <span
              className={`w-2 h-2 rounded-full ${
                connected
                  ? "bg-emerald-500 animate-pulse"
                  : retryAttempt > 0
                    ? "bg-yellow-500 animate-pulse"
                    : "bg-zinc-600"
              }`}
            />
            {statusLabel}
          </span>
        </div>
      </div>
      <div
        ref={scrollRef}
        onScroll={handleScroll}
        className="font-mono text-xs max-h-72 overflow-y-auto whitespace-pre-wrap leading-relaxed"
      >
        {visible.length === 0 ? (
          <div className="opacity-50 italic">Czekam na pierwszy log...</div>
        ) : (
          visible.map((entry, i) =>
            entry.filtered ? (
              <div
                key={i}
                className="text-zinc-600 italic flex gap-2 items-start"
                title={entry.reason ?? undefined}
              >
                <span className="shrink-0 text-amber-500/70 not-italic">
                  [filtered:{entry.reason}]
                </span>
                <span className="line-through opacity-70">{entry.data}</span>
              </div>
            ) : (
              <div key={i} className={getLineClass(entry.data)}>
                {entry.data}
              </div>
            ),
          )
        )}
      </div>
      {!debug && hiddenCount > 0 && (
        <div className="mt-1 text-[10px] text-zinc-500">
          {hiddenCount} linii ukrytych przez filtr (włącz debug, aby zobaczyć)
        </div>
      )}
    </div>
  );
}
