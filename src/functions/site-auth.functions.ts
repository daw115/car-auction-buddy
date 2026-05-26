import { createServerFn } from "@tanstack/react-start";
import { z } from "zod";
import { randomBytes, scryptSync, timingSafeEqual } from "crypto";
import { supabaseAdmin } from "@/integrations/supabase/client.server";

const SITE_USERS = ["Dawid", "Janek", "Iga", "Monte"] as const;
const usernameSchema = z.enum(SITE_USERS);

// Internal site gate "master" password used only to bootstrap a personal
// password the first time a user logs in. Kept server-side; can be overridden
// via the SITE_MASTER_PASSWORD secret.
const FALLBACK_MASTER_PASSWORD = "carbuddy2026";

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
    const { data: row, error } = await supabaseAdmin
      .from("site_user_passwords")
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      .select("password_hash, password_salt" as any)
      .eq("username", data.username)
      .maybeSingle();
    if (error) throw new Error(error.message);
    if (!row) return { ok: false as const };

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const r = row as any;
    const storedHash: string = r.password_hash;
    const storedSalt: string | null = r.password_salt ?? null;

    if (storedSalt) {
      const candidate = hashPassword(data.password, storedSalt);
      return { ok: safeEqualHex(candidate, storedHash) };
    }

    // Legacy: pre-migration rows stored unsalted SHA-256 hex of the password.
    const legacy = Buffer.from(
      await crypto.subtle.digest(
        "SHA-256",
        new TextEncoder().encode(data.password),
      ),
    ).toString("hex");
    if (legacy.length === storedHash.length && safeEqualHex(legacy, storedHash)) {
      // Upgrade in place to salted scrypt.
      const newSalt = randomBytes(16).toString("hex");
      const newHash = hashPassword(data.password, newSalt);
      await supabaseAdmin
        .from("site_user_passwords")
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        .update({ password_hash: newHash, password_salt: newSalt, updated_at: new Date().toISOString() } as any)
        .eq("username", data.username);
      return { ok: true as const };
    }
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
    const expectedMaster =
      process.env.SITE_MASTER_PASSWORD || FALLBACK_MASTER_PASSWORD;
    if (data.masterPassword !== expectedMaster) {
      return { ok: false as const, error: "master" as const };
    }
    const salt = randomBytes(16).toString("hex");
    const hash = hashPassword(data.newPassword, salt);
    const { error } = await supabaseAdmin
      .from("site_user_passwords")
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      .upsert({
        username: data.username,
        password_hash: hash,
        password_salt: salt,
        updated_at: new Date().toISOString(),
      } as any);
    if (error) throw new Error(error.message);
    return { ok: true as const };
  });
