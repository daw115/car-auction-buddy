import { createServerFn } from "@tanstack/react-start";
import { getRequest } from "@tanstack/react-start/server";
import { z } from "zod";
import { randomBytes, scryptSync, timingSafeEqual } from "crypto";
import { supabaseAdmin } from "@/integrations/supabase/client.server";
import {
  checkLoginRateLimit,
  getClientKey,
  registerFailedAttempt,
  resetAttempts,
} from "@/server/dev-auth.server";
import { clearSiteSession, getSiteSession, setSiteSession } from "@/server/site-session.server";

const SITE_USERS = ["Dawid", "Pawel"] as const;
const usernameSchema = z.enum(SITE_USERS);

// Namespaced key for the shared rate-limit store — keeps site-login counters
// separate from /dev/logs token counters (both live in the same in-memory Map).
function siteRateKey(request: Request): string {
  return `site:${getClientKey(request)}`;
}

function hashPassword(password: string, saltHex: string): string {
  const salt = Buffer.from(saltHex, "hex");
  // scrypt is built into Node crypto and works under Cloudflare Workers
  // with the nodejs_compat flag.
  return scryptSync(password, salt, 64).toString("hex");
}

function safeEqualHex(a: string, b: string): boolean {
  if (typeof a !== "string" || typeof b !== "string" || a.length !== b.length) {
    return false;
  }
  try {
    return timingSafeEqual(Buffer.from(a, "hex"), Buffer.from(b, "hex"));
  } catch {
    return false;
  }
}

export const siteUserHasPassword = createServerFn({ method: "POST" })
  .inputValidator((d) => z.object({ username: usernameSchema }).parse(d))
  .handler(async ({ data }) => {
    const { data: row, error } = await supabaseAdmin
      .from("site_user_passwords")
      .select("username")
      .eq("username", data.username)
      .maybeSingle();
    if (error) throw new Error(error.message);
    return { exists: !!row };
  });

export const siteUserLogin = createServerFn({ method: "POST" })
  .inputValidator((d) =>
    z
      .object({
        username: usernameSchema,
        password: z.string().min(1).max(200),
      })
      .parse(d),
  )
  .handler(async ({ data }) => {
    const request = getRequest();
    const rateKey = siteRateKey(request);

    // Enforce lockout BEFORE touching DB or comparing password.
    const pre = checkLoginRateLimit(rateKey);
    if (!pre.allowed) {
      return {
        ok: false as const,
        error: "rate_limited" as const,
        retryAfterSeconds: pre.retryAfterSeconds,
      };
    }

    const { data: row, error } = await supabaseAdmin
      .from("site_user_passwords")
      .select("password_hash, password_salt")
      .eq("username", data.username)
      .maybeSingle();
    if (error) throw new Error(error.message);

    const registerFailure = () => {
      const after = registerFailedAttempt(rateKey);
      if (!after.allowed) {
        return {
          ok: false as const,
          error: "rate_limited" as const,
          retryAfterSeconds: after.retryAfterSeconds,
        };
      }
      return {
        ok: false as const,
        error: "invalid" as const,
        attemptsRemaining: after.remaining,
      };
    };

    if (!row) return registerFailure();

    const storedHash = row.password_hash;
    const storedSalt = row.password_salt;

    if (storedSalt) {
      const candidate = hashPassword(data.password, storedSalt);
      if (safeEqualHex(candidate, storedHash)) {
        resetAttempts(rateKey);
        setSiteSession(data.username);
        return { ok: true as const };
      }
      return registerFailure();
    }

    // Legacy: pre-migration rows stored unsalted SHA-256 hex of the password.
    const legacy = Buffer.from(
      await crypto.subtle.digest("SHA-256", new TextEncoder().encode(data.password)),
    ).toString("hex");
    if (legacy.length === storedHash.length && safeEqualHex(legacy, storedHash)) {
      // Upgrade in place to salted scrypt.
      const newSalt = randomBytes(16).toString("hex");
      const newHash = hashPassword(data.password, newSalt);
      await supabaseAdmin
        .from("site_user_passwords")
        .update({
          password_hash: newHash,
          password_salt: newSalt,
          updated_at: new Date().toISOString(),
        })
        .eq("username", data.username);
      resetAttempts(rateKey);
      setSiteSession(data.username);
      return { ok: true as const };
    }
    return registerFailure();
  });

export const siteUserSetPassword = createServerFn({ method: "POST" })
  .inputValidator((d) =>
    z
      .object({
        username: usernameSchema,
        masterPassword: z.string().min(1).max(200),
        newPassword: z.string().min(4).max(200),
      })
      .parse(d),
  )
  .handler(async ({ data }) => {
    const request = getRequest();
    const rateKey = siteRateKey(request);

    // Enforce lockout BEFORE comparing the master password — same protection
    // as login, since this endpoint also gates on a guessable secret.
    const pre = checkLoginRateLimit(rateKey);
    if (!pre.allowed) {
      return {
        ok: false as const,
        error: "rate_limited" as const,
        retryAfterSeconds: pre.retryAfterSeconds,
      };
    }

    const expectedMaster = process.env.SITE_MASTER_PASSWORD;
    if (!expectedMaster || expectedMaster.length === 0) {
      // Explicit configuration failure — no silent fallback to a hardcoded
      // password. Ops must set SITE_MASTER_PASSWORD before bootstrap/reset.
      return { ok: false as const, error: "not_configured" as const };
    }
    if (data.masterPassword !== expectedMaster) {
      registerFailedAttempt(rateKey);
      return { ok: false as const, error: "master" as const };
    }
    const salt = randomBytes(16).toString("hex");
    const hash = hashPassword(data.newPassword, salt);
    const { error } = await supabaseAdmin.from("site_user_passwords").upsert({
      username: data.username,
      password_hash: hash,
      password_salt: salt,
      updated_at: new Date().toISOString(),
    });
    if (error) throw new Error(error.message);
    resetAttempts(rateKey);
    setSiteSession(data.username);
    return { ok: true as const };
  });

export const siteUserDeletePassword = createServerFn({ method: "POST" })
  .inputValidator((d) =>
    z
      .object({
        username: usernameSchema,
        masterPassword: z.string().min(1).max(200),
      })
      .parse(d),
  )
  .handler(async ({ data }) => {
    const expectedMaster = process.env.SITE_MASTER_PASSWORD;
    if (!expectedMaster || expectedMaster.length === 0) {
      return { ok: false as const, error: "not_configured" as const };
    }
    if (data.masterPassword !== expectedMaster) {
      return { ok: false as const, error: "master" as const };
    }
    const { error } = await supabaseAdmin
      .from("site_user_passwords")
      .delete()
      .eq("username", data.username);
    if (error) throw new Error(error.message);
    return { ok: true as const };
  });

export const siteUserSession = createServerFn({ method: "GET" }).handler(async () => {
  try {
    const session = getSiteSession();
    return session
      ? { authenticated: true as const, username: session.sub }
      : { authenticated: false as const, username: null };
  } catch (error) {
    console.error("[site-auth] session status failed", error);
    return { authenticated: false as const, username: null };
  }
});

export const siteUserLogout = createServerFn({ method: "POST" }).handler(async () => {
  clearSiteSession();
  return { ok: true as const };
});
