// Pretty colored console logger for the server (dev-friendly).
// Uses ANSI escape codes — works in Vite dev terminal and Worker logs.
// In production (NODE_ENV=production) colors and verbose request logs are suppressed
// unless DEBUG_SERVER=1 is set.

const isProd = process.env.NODE_ENV === "production";
const forceVerbose = process.env.DEBUG_SERVER === "1";
export const VERBOSE = !isProd || forceVerbose;

const C = {
  reset: "\x1b[0m",
  dim: "\x1b[2m",
  bold: "\x1b[1m",
  gray: "\x1b[90m",
  red: "\x1b[31m",
  green: "\x1b[32m",
  yellow: "\x1b[33m",
  blue: "\x1b[34m",
  magenta: "\x1b[35m",
  cyan: "\x1b[36m",
  white: "\x1b[37m",
};

function ts(): string {
  const d = new Date();
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  const ss = String(d.getSeconds()).padStart(2, "0");
  const ms = String(d.getMilliseconds()).padStart(3, "0");
  return `${hh}:${mm}:${ss}.${ms}`;
}

function levelTag(level: "info" | "warn" | "error" | "debug" | "http") {
  switch (level) {
    case "info":
      return `${C.cyan}INFO${C.reset} `;
    case "warn":
      return `${C.yellow}WARN${C.reset} `;
    case "error":
      return `${C.red}ERR! ${C.reset}`;
    case "debug":
      return `${C.magenta}DEBG${C.reset} `;
    case "http":
      return `${C.blue}HTTP${C.reset} `;
  }
}

export function devLog(
  level: "info" | "warn" | "error" | "debug" | "http",
  scope: string,
  message: string,
  extra?: Record<string, unknown>,
) {
  if (!VERBOSE && level === "debug") return;
  const time = `${C.gray}${ts()}${C.reset}`;
  const tag = levelTag(level);
  const scopeStr = `${C.bold}${scope}${C.reset}`;
  const line = `${time} ${tag} ${scopeStr} ${C.dim}›${C.reset} ${message}`;
  // Use the matching console method so log levels are preserved.
  const fn =
    level === "error" ? console.error : level === "warn" ? console.warn : console.log;
  if (extra && Object.keys(extra).length > 0) {
    fn(line, extra);
  } else {
    fn(line);
  }
  // Mirror to in-memory stream for the dev logs panel.
  try {
    // Lazy import to avoid potential circular issues.
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const { publishLog } = require("./log-stream.server") as typeof import("./log-stream.server");
    publishLog({ level, scope, message, extra: extra ?? null });
  } catch {
    // ignore
  }
}

function statusColor(status: number): string {
  if (status >= 500) return C.red;
  if (status >= 400) return C.yellow;
  if (status >= 300) return C.cyan;
  return C.green;
}

function methodColor(method: string): string {
  switch (method.toUpperCase()) {
    case "GET":
      return C.green;
    case "POST":
      return C.blue;
    case "PUT":
    case "PATCH":
      return C.yellow;
    case "DELETE":
      return C.red;
    default:
      return C.magenta;
  }
}

function fmtDuration(ms: number): string {
  const color = ms > 1000 ? C.red : ms > 300 ? C.yellow : C.gray;
  return `${color}${ms.toFixed(1)}ms${C.reset}`;
}

export function logHttp(opts: {
  method: string;
  path: string;
  status: number;
  durationMs: number;
  scope?: string;
}) {
  const m = `${methodColor(opts.method)}${opts.method.padEnd(6)}${C.reset}`;
  const s = `${statusColor(opts.status)}${opts.status}${C.reset}`;
  const time = `${C.gray}${ts()}${C.reset}`;
  const tag = levelTag("http");
  const scope = opts.scope ?? "http";
  // eslint-disable-next-line no-console
  console.log(
    `${time} ${tag} ${C.bold}${scope}${C.reset} ${m} ${s} ${opts.path} ${C.dim}·${C.reset} ${fmtDuration(opts.durationMs)}`,
  );
}
