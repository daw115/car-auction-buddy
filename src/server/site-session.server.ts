import { createHmac, timingSafeEqual } from "node:crypto";
import { deleteCookie, getCookie, setCookie } from "@tanstack/react-start/server";
import { SITE_USERS, type SiteUser } from "@/lib/site-user";

const SESSION_COOKIE = "car_auction_session";
const SESSION_VERSION = 1;
const DEFAULT_TTL_SECONDS = 60 * 60;
const MIN_SECRET_LENGTH = 32;

type SiteSessionPayload = {
  v: typeof SESSION_VERSION;
  sub: SiteUser;
  iat: number;
  exp: number;
};

function getSessionSecret(): string {
  const secret = process.env.SITE_SESSION_SECRET;
  if (!secret || secret.length < MIN_SECRET_LENGTH) {
    throw new Error(
      `SITE_SESSION_SECRET must be configured with at least ${MIN_SECRET_LENGTH} characters.`,
    );
  }
  return secret;
}

function getSessionTtlSeconds(): number {
  const parsed = Number.parseInt(process.env.SITE_SESSION_TTL_SECONDS ?? "", 10);
  if (!Number.isFinite(parsed)) return DEFAULT_TTL_SECONDS;
  return Math.min(Math.max(parsed, 5 * 60), 24 * 60 * 60);
}

function isSiteUser(value: unknown): value is SiteUser {
  return typeof value === "string" && (SITE_USERS as readonly string[]).includes(value);
}

function sign(encodedPayload: string, secret: string): Buffer {
  return createHmac("sha256", secret).update(encodedPayload).digest();
}

export function createSiteSessionToken(
  user: SiteUser,
  secret: string,
  nowMs = Date.now(),
  ttlSeconds = DEFAULT_TTL_SECONDS,
): string {
  if (secret.length < MIN_SECRET_LENGTH) {
    throw new Error(`Session secret must have at least ${MIN_SECRET_LENGTH} characters.`);
  }
  const issuedAt = Math.floor(nowMs / 1000);
  const payload: SiteSessionPayload = {
    v: SESSION_VERSION,
    sub: user,
    iat: issuedAt,
    exp: issuedAt + ttlSeconds,
  };
  const encodedPayload = Buffer.from(JSON.stringify(payload)).toString("base64url");
  return `${encodedPayload}.${sign(encodedPayload, secret).toString("base64url")}`;
}

export function verifySiteSessionToken(
  token: string,
  secret: string,
  nowMs = Date.now(),
): SiteSessionPayload | null {
  if (secret.length < MIN_SECRET_LENGTH) return null;
  const parts = token.split(".");
  if (parts.length !== 2) return null;
  const [encodedPayload, encodedSignature] = parts;
  if (!encodedPayload || !encodedSignature) return null;

  try {
    const suppliedSignature = Buffer.from(encodedSignature, "base64url");
    const expectedSignature = sign(encodedPayload, secret);
    if (
      suppliedSignature.length !== expectedSignature.length ||
      !timingSafeEqual(suppliedSignature, expectedSignature)
    ) {
      return null;
    }

    const payload = JSON.parse(
      Buffer.from(encodedPayload, "base64url").toString("utf8"),
    ) as Partial<SiteSessionPayload>;
    const now = Math.floor(nowMs / 1000);
    if (
      payload.v !== SESSION_VERSION ||
      !isSiteUser(payload.sub) ||
      !Number.isInteger(payload.iat) ||
      !Number.isInteger(payload.exp) ||
      payload.iat! > now + 60 ||
      payload.exp! <= now ||
      payload.exp! <= payload.iat!
    ) {
      return null;
    }
    return payload as SiteSessionPayload;
  } catch {
    return null;
  }
}

function cookieOptions(maxAge?: number) {
  return {
    httpOnly: true,
    secure: process.env.NODE_ENV !== "development",
    sameSite: "lax" as const,
    path: "/",
    ...(maxAge === undefined ? {} : { maxAge }),
  };
}

export function setSiteSession(user: SiteUser): void {
  const ttlSeconds = getSessionTtlSeconds();
  const token = createSiteSessionToken(user, getSessionSecret(), Date.now(), ttlSeconds);
  setCookie(SESSION_COOKIE, token, cookieOptions(ttlSeconds));
}

export function clearSiteSession(): void {
  deleteCookie(SESSION_COOKIE, cookieOptions(0));
}

export function getSiteSession(): SiteSessionPayload | null {
  const token = getCookie(SESSION_COOKIE);
  if (!token) return null;
  return verifySiteSessionToken(token, getSessionSecret());
}

export function requireSiteSession(): SiteSessionPayload {
  let session: SiteSessionPayload | null;
  try {
    session = getSiteSession();
  } catch (error) {
    console.error("[site-session] configuration error", error);
    throw new Response("Session authentication is not configured", { status: 500 });
  }
  if (!session) {
    throw new Response("Unauthorized", { status: 401 });
  }
  return session;
}

export async function siteSessionGuard(): Promise<Response | null> {
  try {
    requireSiteSession();
    return null;
  } catch (error) {
    if (error instanceof Response) return error;
    console.error("[site-session] unexpected authentication error", error);
    return new Response("Internal Server Error", { status: 500 });
  }
}
