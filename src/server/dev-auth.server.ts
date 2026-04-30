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

  const provided = fromCookie || fromQuery;
  if (!provided) return { ok: false, status: 401, reason: "Missing token" };
  if (provided !== expected) return { ok: false, status: 401, reason: "Invalid token" };
  return { ok: true };
}

export function buildAuthCookie(token: string): string {
  // 7 days, httpOnly, lax. Secure when not on localhost-style request.
  const maxAge = 60 * 60 * 24 * 7;
  return `${COOKIE_NAME}=${encodeURIComponent(token)}; Path=/; Max-Age=${maxAge}; HttpOnly; SameSite=Lax; Secure`;
}

export function clearAuthCookie(): string {
  return `${COOKIE_NAME}=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax; Secure`;
}

export const DEV_AUTH_COOKIE_NAME = COOKIE_NAME;
