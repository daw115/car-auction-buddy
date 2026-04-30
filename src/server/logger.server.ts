// Server-only logger that persists structured operation events to operation_logs.
// IMPORTANT: never include secrets, API keys, or full prompts/payloads in `details`.
// Sanitize before passing in.

import { supabaseAdmin } from "@/integrations/supabase/client.server";
import { devLog } from "./dev-logger.server";

export type LogLevel = "info" | "warn" | "error" | "debug";

export type LogContext = {
  operation: string; // e.g. "scrape", "ai_analysis"
  clientId?: string | null;
  recordId?: string | null;
};

export type LogEntry = {
  step?: string;
  level?: LogLevel;
  message: string;
  details?: Record<string, unknown> | null;
  durationMs?: number | null;
};

const SECRET_KEY_PATTERNS = [
  /api[_-]?key/i,
  /secret/i,
  /token/i,
  /authorization/i,
  /password/i,
  /bearer/i,
];

function isSecretKey(key: string): boolean {
  return SECRET_KEY_PATTERNS.some((re) => re.test(key));
}

function truncate(s: string, max = 500): string {
  return s.length > max ? `${s.slice(0, max)}…(+${s.length - max})` : s;
}

/** Recursively redact secret-like keys and truncate long strings. */
export function sanitizeDetails(input: unknown, depth = 0): unknown {
  if (input == null) return input;
  if (depth > 4) return "[depth-limit]";
  if (typeof input === "string") return truncate(input, 500);
  if (typeof input === "number" || typeof input === "boolean") return input;
  if (Array.isArray(input)) {
    return input.slice(0, 20).map((v) => sanitizeDetails(v, depth + 1));
  }
  if (typeof input === "object") {
    const out: Record<string, unknown> = {};
    let count = 0;
    for (const [k, v] of Object.entries(input as Record<string, unknown>)) {
      if (count++ >= 30) {
        out["…"] = "[truncated]";
        break;
      }
      if (isSecretKey(k)) {
        out[k] = "[redacted]";
      } else {
        out[k] = sanitizeDetails(v, depth + 1);
      }
    }
    return out;
  }
  return String(input);
}

export async function writeLog(ctx: LogContext, entry: LogEntry): Promise<void> {
  const level = entry.level ?? "info";
  // Mirror to console with color first — DB write may be async/slow.
  const scope = `${ctx.operation}${entry.step ? `:${entry.step}` : ""}`;
  const extra: Record<string, unknown> = {};
  if (ctx.clientId) extra.clientId = ctx.clientId;
  if (ctx.recordId) extra.recordId = ctx.recordId;
  if (entry.durationMs != null) extra.durationMs = entry.durationMs;
  if (entry.details) Object.assign(extra, { details: sanitizeDetails(entry.details) });
  devLog(level, scope, entry.message, extra);

  try {
    const row = {
      client_id: ctx.clientId ?? null,
      record_id: ctx.recordId ?? null,
      operation: ctx.operation,
      step: entry.step ?? null,
      level,
      message: truncate(entry.message, 1000),
      details: entry.details ? sanitizeDetails(entry.details) : null,
      duration_ms: entry.durationMs ?? null,
    };
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const { error } = await supabaseAdmin.from("operation_logs").insert([row as any]);
    if (error) console.error("[logger] failed to insert:", error.message);
  } catch (e) {
    console.error("[logger] exception:", e);
  }
}

/** Convenience helpers bound to a context. */
export function makeLogger(ctx: LogContext) {
  return {
    info: (step: string, message: string, details?: Record<string, unknown>, durationMs?: number) =>
      writeLog(ctx, { step, level: "info", message, details: details ?? null, durationMs: durationMs ?? null }),
    warn: (step: string, message: string, details?: Record<string, unknown>) =>
      writeLog(ctx, { step, level: "warn", message, details: details ?? null }),
    error: (step: string, message: string, details?: Record<string, unknown>) =>
      writeLog(ctx, { step, level: "error", message, details: details ?? null }),
    debug: (step: string, message: string, details?: Record<string, unknown>) =>
      writeLog(ctx, { step, level: "debug", message, details: details ?? null }),
  };
}
