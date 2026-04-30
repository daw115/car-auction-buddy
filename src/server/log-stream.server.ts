// In-memory ring buffer for recent server logs + pub/sub for SSE streaming.
// Dev-only convenience. Holds last N entries; subscribers receive new ones live.

export type LogStreamEntry = {
  id: number;
  ts: string; // ISO
  level: "info" | "warn" | "error" | "debug" | "http";
  scope: string;
  message: string;
  extra?: Record<string, unknown> | null;
};

const MAX_BUFFER = 500;
const buffer: LogStreamEntry[] = [];
let nextId = 1;
const subscribers = new Set<(e: LogStreamEntry) => void>();

export function publishLog(entry: Omit<LogStreamEntry, "id" | "ts">) {
  const full: LogStreamEntry = {
    id: nextId++,
    ts: new Date().toISOString(),
    ...entry,
  };
  buffer.push(full);
  if (buffer.length > MAX_BUFFER) buffer.splice(0, buffer.length - MAX_BUFFER);
  for (const cb of subscribers) {
    try {
      cb(full);
    } catch {
      // ignore broken subscribers
    }
  }
}

export function getRecentLogs(sinceId = 0): LogStreamEntry[] {
  return sinceId > 0 ? buffer.filter((e) => e.id > sinceId) : buffer.slice();
}

export function subscribe(cb: (e: LogStreamEntry) => void): () => void {
  subscribers.add(cb);
  return () => {
    subscribers.delete(cb);
  };
}
