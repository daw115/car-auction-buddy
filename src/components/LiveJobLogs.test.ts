import { describe, it, expect } from "vitest";
import { isNoiseLine, getLineClass, noiseReason } from "./LiveJobLogs";

describe("LiveJobLogs noise filter", () => {
  describe("isNoiseLine — filters request-spam", () => {
    const spam = [
      'INFO: 192.168.1.1 - "GET /api/jobs/abc123/status HTTP/1.1" 200',
      'INFO: 10.0.0.1 - "GET /api/records/45 HTTP/1.1" 200',
      'INFO: - "GET /api/records HTTP/1.1" 200',
      'INFO: - "GET /health HTTP/1.1" 200',
      'INFO: - "GET /api/health HTTP/1.1" 200',
      'INFO: - "GET /api/html-cache/lookup HTTP/1.1" 200',
      'INFO: - "GET /api/llm-cache/x HTTP/1.1" 200',
      'INFO: - "GET /api/model-normalizations HTTP/1.1" 200',
      'INFO: - "GET /api/db/stats HTTP/1.1" 200',
      'INFO: - "GET /api/feedback HTTP/1.1" 200',
      "GET /api/jobs/abc?foo=bar",
    ];

    it.each(spam)("filters: %s", (line) => {
      expect(isNoiseLine(line)).toBe(true);
      expect(noiseReason(line)).toMatch(/^request-spam \(/);
    });
  });

  describe("isNoiseLine — keeps real scraper progress", () => {
    const keep = [
      "[Otomoto] Wzbogacono lot 12345",
      "[AI/Bidfax] Analiza ukończona dla VIN ABC",
      "2026-05-12 12:00:00 INFO Filtr DOM: 4 loty po filtracji",
      "ERROR: Gemini 429 rate limit, fallback to Claude",
      "WARNING: scrape timeout",
      "Broadcast event delivered to 3 clients",
      "Auto-bundle complete: 15 reports",
      "POST /api/scrape/start HTTP/1.1 200",
      "GET /api/logs/stream HTTP/1.1 200",
      "INFO scraping_list phase started",
      "[pre_rank] scoring 42 lots",
      "GET /api/jobs-list HTTP/1.1 200",
      "GET /api/healthcheck HTTP/1.1 200",
      "GET /api/records-export HTTP/1.1 200",
    ];

    it.each(keep)("keeps: %s", (line) => {
      expect(isNoiseLine(line)).toBe(false);
      expect(noiseReason(line)).toBeNull();
    });
  });

  describe("noiseReason — explains why a line was filtered", () => {
    it("includes the matched path segment", () => {
      expect(noiseReason('GET /api/jobs/abc HTTP/1.1')).toBe(
        "request-spam (/api/jobs)",
      );
      expect(noiseReason("GET /health HTTP/1.1")).toBe("request-spam (/health)");
      expect(noiseReason("GET /api/html-cache/lookup HTTP/1.1")).toBe(
        "request-spam (/api/html-cache)",
      );
    });
  });

  describe("getLineClass — semantic colouring", () => {
    it("colours errors red", () => {
      expect(getLineClass("ERROR: crash in scraper")).toBe("text-red-400");
      expect(getLineClass("something FAILED")).toBe("text-red-400");
    });
    it("colours warnings yellow", () => {
      expect(getLineClass("WARNING: slow")).toBe("text-yellow-400");
      expect(getLineClass("Gemini 429 rate-limit")).toBe("text-yellow-400");
      expect(getLineClass("using fallback model")).toBe("text-yellow-400");
    });
    it("colours success green", () => {
      expect(getLineClass("Wzbogacono lot 1")).toBe("text-emerald-400");
      expect(getLineClass("Broadcast event delivered")).toBe("text-emerald-400");
      expect(getLineClass("Filtr DOM: ok")).toBe("text-emerald-400");
      expect(getLineClass("Auto-bundle ready")).toBe("text-emerald-400");
    });
    it("colours AI/Bidfax/Otomoto blue", () => {
      expect(getLineClass("[AI/Bidfax] hit")).toBe("text-blue-400");
      expect(getLineClass("[Otomoto] enriched")).toBe("text-blue-400");
      expect(getLineClass("[pre_rank] scoring")).toBe("text-blue-400");
    });
    it("defaults to zinc for plain lines", () => {
      expect(getLineClass("INFO scraping_list phase")).toBe("text-zinc-300");
    });
  });
});
