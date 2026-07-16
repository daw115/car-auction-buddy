import { createServerFn } from "@tanstack/react-start";
import { z } from "zod";
import { randomBytes, scryptSync, timingSafeEqual } from "crypto";
import { supabaseAdmin } from "@/integrations/supabase/client.server";
import {
  assertSiteAuthRateLimit,
  getSiteAuthRateLimitKey,
  registerSiteAuthFailure,
  resetSiteAuthFailures,
} from "@/server/site-auth-rate-limit.server";
import { clearSiteSession, getSiteSession, setSiteSession } from "@/server/site-session.server";

const SITE_USERS = ["Dawid", "Janek", "Iga", "Monte"] as const;
const usernameSchema = z.enum(SITE_USERS);

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
    const rateKey = getSiteAuthRateLimitKey(data.username);
    await assertSiteAuthRateLimit(rateKey);

    const { data: row, error } = await supabaseAdmin
      .from("site_user_passwords")
      .select("password_hash, password_salt")
      .eq("username", data.username)
      .maybeSingle();
    if (error) throw new Error(error.message);
    if (!row) {
      await registerSiteAuthFailure(rateKey);
      return { ok: false as const };
    }

    const storedHash = row.password_hash;
    const storedSalt = row.password_salt;

    if (storedSalt) {
      const candidate = hashPassword(data.password, storedSalt);
      const ok = safeEqualHex(candidate, storedHash);
      if (ok) {
        await resetSiteAuthFailures(rateKey);
        setSiteSession(data.username);
      } else {
        await registerSiteAuthFailure(rateKey);
      }
      return { ok };
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
      await resetSiteAuthFailures(rateKey);
      setSiteSession(data.username);
      return { ok: true as const };
    }
    await registerSiteAuthFailure(rateKey);
    return { ok: false as const };
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
    const rateKey = getSiteAuthRateLimitKey(data.username);
    await assertSiteAuthRateLimit(rateKey);

    const expectedMaster = process.env.SITE_MASTER_PASSWORD;
    if (!expectedMaster) {
      throw new Error("SITE_MASTER_PASSWORD is not configured.");
    }
    if (data.masterPassword !== expectedMaster) {
      await registerSiteAuthFailure(rateKey);
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
    await resetSiteAuthFailures(rateKey);
    setSiteSession(data.username);
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
