import { useEffect, useRef, useState } from "react";

interface Props {
  jobId: string;
  active: boolean;
}

const NOISE_RE =
  /GET \/(?:api\/(?:jobs|records|health|html-cache|llm-cache|model-normalizations|db|feedback)|health)(?=[/?\s"]|$)/;

function getLineClass(line: string): string {
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
  const scrollRef = useRef<HTMLDivElement>(null);
  const userScrolledUpRef = useRef(false);

  useEffect(() => {
    if (!active) return;
    let retries = 0;
    let es: EventSource | null = null;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;
    let cancelled = false;

    const connect = () => {
      if (cancelled) return;
      es = new EventSource("/api/scraper-logs/stream");

      es.addEventListener("open", () => {
        setConnected(true);
        retries = 0;
      });

      es.addEventListener("line", (e) => {
        const data = (e as MessageEvent).data as string;
        if (NOISE_RE.test(data)) return;
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
          retryTimer = setTimeout(connect, 3000);
        }
      };
    };

    connect();
    return () => {
      cancelled = true;
      if (retryTimer) clearTimeout(retryTimer);
      es?.close();
      setConnected(false);
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

  return (
    <div className="bg-zinc-950 text-zinc-200 rounded-lg p-3 mt-3">
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs uppercase tracking-wider opacity-70">
          📜 Live logs · job {jobId.slice(0, 8)}
        </span>
        <span className="flex items-center gap-1.5 text-[10px] opacity-70">
          <span
            className={`w-2 h-2 rounded-full ${
              connected ? "bg-emerald-500 animate-pulse" : "bg-zinc-600"
            }`}
          />
          {connected ? "streaming" : "rozłączone"}
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
