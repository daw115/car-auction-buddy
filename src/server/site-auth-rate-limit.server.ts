import { createHash } from "node:crypto";
import { getRequest, getRequestIP } from "@tanstack/react-start/server";
import { supabaseAdmin } from "@/integrations/supabase/client.server";
import type { SiteUser } from "@/lib/site-user";

const OPERATION = "site_auth";

export function getSiteAuthRateLimitKey(user: SiteUser): string {
  const request = getRequest();
  const ip = request.headers.get("cf-connecting-ip") ?? getRequestIP() ?? "unknown";
  return createHash("sha256").update(`${ip}:${user}`).digest("hex");
}

export function normalizeSiteAuthRetryAfter(value: unknown): number {
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0) {
    throw new Error("Rate limit RPC returned an invalid retry interval");
  }
  return Math.ceil(value);
}

async function writeEvent(key: string, step: "login_failure" | "login_success"): Promise<void> {
  const { error } = await supabaseAdmin.from("operation_logs").insert({
    operation: OPERATION,
    step,
    level: step === "login_failure" ? "warn" : "info",
    message: step === "login_failure" ? "Failed site login" : "Successful site login",
    details: { rate_key: key },
  });
  if (error) throw new Error(`Rate limit audit write failed: ${error.message}`);
}

export async function registerSiteAuthFailure(key: string): Promise<void> {
  await writeEvent(key, "login_failure");
}

export async function resetSiteAuthFailures(key: string): Promise<void> {
  const { error } = await supabaseAdmin.rpc("reset_site_auth_attempts", { p_rate_key: key });
  if (error) throw new Error(`Rate limit reset failed: ${error.message}`);
  await writeEvent(key, "login_success");
}

export async function assertSiteAuthRateLimit(key: string): Promise<void> {
  // The RPC locks one database row and consumes the attempt before password
  // verification, so parallel requests cannot all pass the same stale check.
  const { data, error } = await supabaseAdmin.rpc("consume_site_auth_attempt", {
    p_rate_key: key,
  });
  if (error) throw new Error(`Rate limit check failed: ${error.message}`);

  const retryAfterSeconds = normalizeSiteAuthRetryAfter(data);
  if (retryAfterSeconds > 0) {
    throw new Response("Too many login attempts", {
      status: 429,
      headers: { "Retry-After": String(retryAfterSeconds) },
    });
  }
}
