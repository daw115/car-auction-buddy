import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const PRIVATE_FUNCTION_MODULES = [
  "api.functions.ts",
  "external.functions.ts",
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
});
