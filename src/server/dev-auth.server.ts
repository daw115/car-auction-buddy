// Shared auth helper for /dev/* endpoints.
// Requires DEV_LOGS_TOKEN env var. Access only allowed in non-production.

const COOKIE_NAME = "dev_logs_token";

function isDevEnvironment(): boolean {
  // Cloudflare Workers / Node — treat anything not "production" as dev.
  return (process.env.NODE_ENV ?? "development") !== "production";
}

function parseCookies(header: string | null): Record<string, string> {
  const out: Record<string, string> = {};
  if (!header) return out;
  for (const part of header.split(";")) {
    const idx = part.indexOf("=");
    if (idx === -1) continue;
    const k = part.slice(0, idx).trim();
    const v = part.slice(idx + 1).trim();
    if (k) out[k] = decodeURIComponent(v);
  }
  return out;
}

export function getExpectedToken(): string | null {
  const t = process.env.DEV_LOGS_TOKEN;
  return t && t.length > 0 ? t : null;
}

export type DevAuthResult =
  | { ok: true }
  | { ok: false; status: 401 | 403 | 503; reason: string };

function timingSafeEqualStr(a: string, b: string): boolean {
  // Constant-time string compare to avoid token leakage via timing.
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) {
    diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  }
  return diff === 0;
}

export function checkDevAuth(request: Request): DevAuthResult {
  if (!isDevEnvironment()) {
    return { ok: false, status: 403, reason: "Dev panel disabled in production" };
  }
  const expected = getExpectedToken();
  if (!expected) {
    return { ok: false, status: 503, reason: "DEV_LOGS_TOKEN is not configured" };
  }

  const cookies = parseCookies(request.headers.get("cookie"));
  const fromCookie = cookies[COOKIE_NAME];
  const url = new URL(request.url);
  const fromQuery = url.searchParams.get("token");
  const authHeader = request.headers.get("authorization");
  const fromBearer = authHeader && authHeader.startsWith("Bearer ")
    ? authHeader.slice("Bearer ".length).trim()
    : null;

  const provided = fromCookie || fromBearer || fromQuery;
  if (!provided) return { ok: false, status: 401, reason: "Missing token" };
  if (!timingSafeEqualStr(provided, expected)) {
    return { ok: false, status: 401, reason: "Invalid token" };
  }
  return { ok: true };
}

// Default cookie TTL: 1h. Override via DEV_LOGS_TOKEN_TTL_SECONDS (min 60s, max 30 days).
const DEFAULT_TTL_SECONDS = 60 * 60;
const MIN_TTL_SECONDS = 60;
const MAX_TTL_SECONDS = 60 * 60 * 24 * 30;

export function getCookieTtlSeconds(): number {
  const raw = process.env.DEV_LOGS_TOKEN_TTL_SECONDS;
  if (!raw) return DEFAULT_TTL_SECONDS;
  const n = Number(raw);
  if (!Number.isFinite(n) || n <= 0) return DEFAULT_TTL_SECONDS;
  return Math.max(MIN_TTL_SECONDS, Math.min(MAX_TTL_SECONDS, Math.floor(n)));
}

export function buildAuthCookie(token: string): string {
  const maxAge = getCookieTtlSeconds();
  return `${COOKIE_NAME}=${encodeURIComponent(token)}; Path=/; Max-Age=${maxAge}; HttpOnly; SameSite=Lax; Secure`;
}

export function clearAuthCookie(): string {
  return `${COOKIE_NAME}=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax; Secure`;
}

export const DEV_AUTH_COOKIE_NAME = COOKIE_NAME;

// ---- Login attempt rate limiting (in-memory, per Worker instance) ----
// Defaults: 5 prób w oknie 15 min, lockout 15 min po przekroczeniu.
// Override via env: DEV_LOGS_MAX_ATTEMPTS, DEV_LOGS_ATTEMPT_WINDOW_SECONDS, DEV_LOGS_LOCKOUT_SECONDS.
const DEFAULT_MAX_ATTEMPTS = 5;
const DEFAULT_WINDOW_SECONDS = 15 * 60;
const DEFAULT_LOCKOUT_SECONDS = 15 * 60;

type AttemptRecord = {
  failures: number[]; // timestamps (ms) of recent failed attempts within the window
  lockedUntil: number; // epoch ms; 0 if not locked
};

const attemptStore = new Map<string, AttemptRecord>();
const MAX_STORE_SIZE = 1000;

function intFromEnv(name: string, fallback: number, min: number, max: number): number {
  const raw = process.env[name];
  if (!raw) return fallback;
  const n = Number(raw);
  if (!Number.isFinite(n) || n <= 0) return fallback;
  return Math.max(min, Math.min(max, Math.floor(n)));
}

function getLimits() {
  return {
    maxAttempts: intFromEnv("DEV_LOGS_MAX_ATTEMPTS", DEFAULT_MAX_ATTEMPTS, 1, 100),
    windowMs: intFromEnv("DEV_LOGS_ATTEMPT_WINDOW_SECONDS", DEFAULT_WINDOW_SECONDS, 10, 86400) * 1000,
    lockoutMs: intFromEnv("DEV_LOGS_LOCKOUT_SECONDS", DEFAULT_LOCKOUT_SECONDS, 10, 86400) * 1000,
  };
}

export function getClientKey(request: Request): string {
  const h = request.headers;
  const fwd = h.get("cf-connecting-ip") || h.get("x-real-ip") || h.get("x-forwarded-for");
  if (fwd) return fwd.split(",")[0]!.trim();
  return "unknown";
}

function pruneStore() {
  if (attemptStore.size <= MAX_STORE_SIZE) return;
  // Drop ~20% oldest entries.
  const entries = Array.from(attemptStore.entries());
  entries.sort((a, b) => {
    const aMax = Math.max(a[1].lockedUntil, a[1].failures.at(-1) ?? 0);
    const bMax = Math.max(b[1].lockedUntil, b[1].failures.at(-1) ?? 0);
    return aMax - bMax;
  });
  const toRemove = Math.ceil(entries.length * 0.2);
  for (let i = 0; i < toRemove; i++) attemptStore.delete(entries[i][0]);
}

export type RateLimitStatus =
  | { allowed: true; remaining: number }
  | { allowed: false; retryAfterSeconds: number };

export function checkLoginRateLimit(key: string): RateLimitStatus {
  const { maxAttempts, windowMs } = getLimits();
  const now = Date.now();
  const rec = attemptStore.get(key);
  if (!rec) return { allowed: true, remaining: maxAttempts };

  if (rec.lockedUntil > now) {
    return { allowed: false, retryAfterSeconds: Math.ceil((rec.lockedUntil - now) / 1000) };
  }
  // Drop stale failures outside window.
  rec.failures = rec.failures.filter((t) => now - t < windowMs);
  return { allowed: true, remaining: Math.max(0, maxAttempts - rec.failures.length) };
}

export function registerFailedAttempt(key: string): RateLimitStatus {
  const { maxAttempts, windowMs, lockoutMs } = getLimits();
  const now = Date.now();
  const rec = attemptStore.get(key) ?? { failures: [], lockedUntil: 0 };
  rec.failures = rec.failures.filter((t) => now - t < windowMs);
  rec.failures.push(now);
  if (rec.failures.length >= maxAttempts) {
    rec.lockedUntil = now + lockoutMs;
    rec.failures = [];
  }
  attemptStore.set(key, rec);
  pruneStore();
  if (rec.lockedUntil > now) {
    return { allowed: false, retryAfterSeconds: Math.ceil((rec.lockedUntil - now) / 1000) };
  }
  return { allowed: true, remaining: Math.max(0, maxAttempts - rec.failures.length) };
}

export function resetAttempts(key: string): void {
  attemptStore.delete(key);
}
