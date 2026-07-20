import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { isCleanupRequestAuthorized } from "./cleanup-logs";

const SECRET = "a-dedicated-cleanup-secret-with-at-least-32-characters";

describe("cleanup logs hook authorization", () => {
  it("exposes only a POST handler", () => {
    const source = readFileSync(new URL("./cleanup-logs.ts", import.meta.url), "utf8");
    expect(source).toMatch(/handlers:\s*{\s*POST:/);
    expect(source).not.toMatch(/\bGET\s*:/);
  });

  it("accepts the exact bearer secret", () => {
    const request = new Request("https://example.test/api/public/hooks/cleanup-logs", {
      method: "POST",
      headers: { Authorization: `Bearer ${SECRET}` },
    });
    expect(isCleanupRequestAuthorized(request, SECRET)).toBe(true);
  });

  it.each([undefined, "Basic abc", "Bearer wrong-secret", `Bearer ${SECRET}x`])(
    "rejects an invalid authorization header: %s",
    (authorization) => {
      const headers = authorization ? { Authorization: authorization } : undefined;
      const request = new Request("https://example.test/api/public/hooks/cleanup-logs", {
        method: "POST",
        headers,
      });
      expect(isCleanupRequestAuthorized(request, SECRET)).toBe(false);
    },
  );

  it("rejects a weakly configured cleanup secret", () => {
    const request = new Request("https://example.test/api/public/hooks/cleanup-logs", {
      method: "POST",
      headers: { Authorization: "Bearer short" },
    });
    expect(isCleanupRequestAuthorized(request, "short")).toBe(false);
  });
});
