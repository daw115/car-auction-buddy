import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const PRIVATE_FUNCTION_MODULES = [
  "ai-providers.functions.ts",
  "backend.functions.ts",
  "default-criteria.functions.ts",
  "external.functions.ts",
  "pipeline-filters.functions.ts",
  "queue.functions.ts",
  "watchlist.functions.ts",
];

const PRIVATE_RAW_ROUTES = [
  "src/routes/api/config.ts",
  "src/routes/api/records.ts",
  "src/routes/api/reports/pdf.ts",
  "src/routes/api/scraper-logs.stream.ts",
];

describe("site session protection inventory", () => {
  it.each(PRIVATE_FUNCTION_MODULES)("protects every server function in %s", (filename) => {
    const source = readFileSync(resolve("src/functions", filename), "utf8");
    const definitions = source.match(/createServerFn\(\{ method: "(?:GET|POST)" \}\)/g) ?? [];
    const protectedDefinitions =
      source.match(
        /createServerFn\(\{ method: "(?:GET|POST)" \}\)\s*\.middleware\(\[siteSessionMiddleware\]\)/g,
      ) ?? [];
    expect(definitions.length).toBeGreaterThan(0);
    expect(protectedDefinitions).toHaveLength(definitions.length);
  });

  it.each(PRIVATE_RAW_ROUTES)("guards private raw route %s", (filename) => {
    const source = readFileSync(resolve(filename), "utf8");
    expect(source).toContain("siteSessionGuard");
    expect(source).toContain("if (unauthorized) return unauthorized");
  });

  it("keeps only bootstrap authentication server functions public", () => {
    const source = readFileSync(resolve("src/functions/site-auth.functions.ts"), "utf8");
    const exportedFunctions =
      source.match(/export const siteUser(?:HasPassword|Login|SetPassword|Session|Logout)/g) ?? [];
    expect(exportedFunctions).toHaveLength(5);
    expect(source).not.toContain("FALLBACK_MASTER_PASSWORD");
  });

  // These handlers are public by design — they are what an unauthenticated
  // visitor calls to get in. That makes SITE_MASTER_PASSWORD the only thing
  // standing between the internet and the app, so every handler that checks it
  // must also be rate limited and must compare in constant time.
  // siteUserDeletePassword shipped without either and could be brute-forced
  // without ever tripping a counter.
  it("rate limits and constant-time compares every master-password handler", () => {
    const source = readFileSync(resolve("src/functions/site-auth.functions.ts"), "utf8");
    const blocks = source.split(/^export const /m).slice(1);
    const gated = blocks.filter((b) => b.includes("SITE_MASTER_PASSWORD"));

    expect(gated.length).toBeGreaterThan(0);
    for (const block of gated) {
      const name = block.slice(0, block.indexOf(" "));
      expect(block, `${name} must check the lockout before comparing`).toContain(
        "checkLoginRateLimit(",
      );
      expect(block, `${name} must count a wrong master password`).toContain(
        "registerFailedAttempt(",
      );
      expect(block, `${name} must not compare the master password with !==`).not.toMatch(
        /!==\s*expectedMaster/,
      );
    }
  });
});
