import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { normalizeSiteAuthRetryAfter } from "./site-auth-rate-limit.server";

describe("site auth rate limiting", () => {
  it("serializes attempt consumption in the database and restricts the RPC", () => {
    const migration = readFileSync(
      resolve("supabase/migrations/20260715234000_lock_down_private_tables.sql"),
      "utf8",
    );
    expect(migration).toContain("CREATE OR REPLACE FUNCTION public.consume_site_auth_attempt");
    expect(migration).toContain("FOR UPDATE;");
    expect(migration).toContain(
      "REVOKE ALL ON FUNCTION public.consume_site_auth_attempt(text) FROM PUBLIC, anon, authenticated",
    );
    expect(migration).toContain(
      "GRANT EXECUTE ON FUNCTION public.consume_site_auth_attempt(text) TO service_role",
    );
  });

  it("treats zero as an allowed consumed attempt", () => {
    expect(normalizeSiteAuthRetryAfter(0)).toBe(0);
  });

  it("rounds a positive retry interval up to full seconds", () => {
    expect(normalizeSiteAuthRetryAfter(12.1)).toBe(13);
  });

  it.each([null, undefined, "10", Number.NaN, -1])(
    "fails closed for an invalid RPC result: %s",
    (value) => {
      expect(() => normalizeSiteAuthRetryAfter(value)).toThrow("invalid retry interval");
    },
  );
});
