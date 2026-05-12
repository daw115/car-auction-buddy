import { useEffect, useRef, useState } from "react";

interface Props {
  jobId: string;
  active: boolean;
}

export const NOISE_RE =
  /GET \/(?:api\/(?:jobs|records|health|html-cache|llm-cache|model-normalizations|db|feedback)|health)(?=[/?\s"]|$)/;

export function isNoiseLine(line: string): boolean {
  return NOISE_RE.test(line);
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

export function LiveJobLogs({ jobId, active }: Props) {
  const [lines, setLines] = useState<string[]>([]);
  const [connected, setConnected] = useState(false);
  const [retryAttempt, setRetryAttempt] = useState(0);
  const linesRef = useRef<string[]>([]);
  const scrollRef = useRef<HTMLDivElement>(null);
  const userScrolledUpRef = useRef(false);

  // Keep ref in sync so the SSE handler can dedupe against current buffer
  // without re-subscribing on every state update.
  useEffect(() => {
    linesRef.current = lines;
  }, [lines]);

  useEffect(() => {
    if (!active) return;
    let retries = 0;
    let es: EventSource | null = null;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;
    let cancelled = false;
    // After (re)connect the upstream replays a snapshot of ~50 lines.
    // We dedupe these against what we already have so the buffer doesn't
    // accumulate duplicates after every reconnect.
    let snapshotRemaining = 0;

    const connect = (isReconnect: boolean) => {
      if (cancelled) return;
      es = new EventSource("/api/scraper-logs/stream");
      // Allow up to 60 incoming lines to be deduped right after connect
      // (snapshot is 50 lines; small headroom for races).
      snapshotRemaining = isReconnect && linesRef.current.length > 0 ? 60 : 0;

      es.addEventListener("open", () => {
        setConnected(true);
        setRetryAttempt(0);
        retries = 0;
      });

      es.addEventListener("line", (e) => {
        const data = (e as MessageEvent).data as string;
        if (NOISE_RE.test(data)) return;

        if (snapshotRemaining > 0) {
          snapshotRemaining--;
          // Drop if this line already exists in our recent tail (last 100).
          const recent = linesRef.current.slice(-100);
          if (recent.includes(data)) return;
        }

        setLines((prev) => {
          const next = [...prev, data];
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
          // Exponential backoff capped at 15s: 3s, 6s, 12s, 15s, 15s
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

  useEffect(() => {
    if (!userScrolledUpRef.current && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [lines]);

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
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs uppercase tracking-wider opacity-70">
          📜 Live logs · job {jobId.slice(0, 8)}
        </span>
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
      <div
        ref={scrollRef}
        onScroll={handleScroll}
        className="font-mono text-xs max-h-72 overflow-y-auto whitespace-pre-wrap leading-relaxed"
      >
        {lines.length === 0 ? (
          <div className="opacity-50 italic">Czekam na pierwszy log...</div>
        ) : (
          lines.map((line, i) => (
            <div key={i} className={getLineClass(line)}>
              {line}
            </div>
          ))
        )}
      </div>
    </div>
  );
}
