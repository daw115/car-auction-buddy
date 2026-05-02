import { describe, it, expect, beforeEach, vi } from "vitest";
import {
  SCRAPE_JOB_STORAGE_KEY,
  persistScrapeJob,
  clearPersistedScrapeJob,
  readPersistedScrapeJob,
  type PersistedScrapeJob,
} from "./scrape-job-storage";

/* ---------- localStorage mock ---------- */
const store = new Map<string, string>();

const localStorageMock: Storage = {
  getItem: vi.fn((key: string) => store.get(key) ?? null),
  setItem: vi.fn((key: string, value: string) => {
    store.set(key, value);
  }),
  removeItem: vi.fn((key: string) => {
    store.delete(key);
  }),
  clear: vi.fn(() => store.clear()),
  get length() {
    return store.size;
  },
  key: vi.fn(() => null),
};

Object.defineProperty(globalThis, "localStorage", { value: localStorageMock });

/* ---------- helpers ---------- */
function seedStorage(data: Partial<PersistedScrapeJob>) {
  store.set(SCRAPE_JOB_STORAGE_KEY, JSON.stringify(data));
}

/* ---------- suites ---------- */
describe("scrape-job-storage", () => {
  beforeEach(() => {
    store.clear();
    vi.clearAllMocks();
  });

  // ---- persistScrapeJob ----
  describe("persistScrapeJob", () => {
    it("saves job to localStorage with correct key", () => {
      persistScrapeJob("job-1", "cache-abc", { seller: "copart" });

      const raw = store.get(SCRAPE_JOB_STORAGE_KEY);
      expect(raw).toBeDefined();
      const parsed = JSON.parse(raw!);
      expect(parsed.jobId).toBe("job-1");
      expect(parsed.cacheKey).toBe("cache-abc");
      expect(parsed.criteria).toEqual({ seller: "copart" });
      expect(parsed.startedAt).toBeTypeOf("number");
    });

    it("overwrites previous entry", () => {
      persistScrapeJob("job-1", "c1", {});
      persistScrapeJob("job-2", "c2", { x: 1 });

      const parsed = JSON.parse(store.get(SCRAPE_JOB_STORAGE_KEY)!);
      expect(parsed.jobId).toBe("job-2");
    });

    it("does not throw when localStorage.setItem throws", () => {
      (localStorageMock.setItem as ReturnType<typeof vi.fn>).mockImplementationOnce(() => {
        throw new Error("QuotaExceededError");
      });

      expect(() => persistScrapeJob("j", "c", {})).not.toThrow();
    });
  });

  // ---- clearPersistedScrapeJob ----
  describe("clearPersistedScrapeJob", () => {
    it("removes the key from localStorage", () => {
      seedStorage({ jobId: "job-1", cacheKey: "c", criteria: {}, startedAt: 1 });
      clearPersistedScrapeJob();
      expect(store.has(SCRAPE_JOB_STORAGE_KEY)).toBe(false);
    });

    it("does not throw when localStorage.removeItem throws", () => {
      (localStorageMock.removeItem as ReturnType<typeof vi.fn>).mockImplementationOnce(() => {
        throw new Error("SecurityError");
      });
      expect(() => clearPersistedScrapeJob()).not.toThrow();
    });
  });

  // ---- readPersistedScrapeJob ----
  describe("readPersistedScrapeJob", () => {
    it("returns null when nothing stored", () => {
      expect(readPersistedScrapeJob()).toBeNull();
    });

    it("returns parsed job when valid data stored", () => {
      const job: PersistedScrapeJob = {
        jobId: "j-42",
        cacheKey: "ck",
        criteria: { damage: "front" },
        startedAt: 1700000000000,
      };
      store.set(SCRAPE_JOB_STORAGE_KEY, JSON.stringify(job));

      const result = readPersistedScrapeJob();
      expect(result).toEqual(job);
    });

    it("returns null and clears storage when jobId is empty", () => {
      seedStorage({ jobId: "", cacheKey: "c", criteria: {}, startedAt: 1 });

      const result = readPersistedScrapeJob();
      expect(result).toBeNull();
      expect(store.has(SCRAPE_JOB_STORAGE_KEY)).toBe(false);
    });

    it("returns null and clears storage when jobId is missing", () => {
      seedStorage({ cacheKey: "c", criteria: {}, startedAt: 1 });

      const result = readPersistedScrapeJob();
      expect(result).toBeNull();
      expect(store.has(SCRAPE_JOB_STORAGE_KEY)).toBe(false);
    });

    it("returns null and clears storage on malformed JSON", () => {
      store.set(SCRAPE_JOB_STORAGE_KEY, "not-json{{{");

      const result = readPersistedScrapeJob();
      expect(result).toBeNull();
      expect(store.has(SCRAPE_JOB_STORAGE_KEY)).toBe(false);
    });

    it("returns null when localStorage.getItem throws", () => {
      (localStorageMock.getItem as ReturnType<typeof vi.fn>).mockImplementationOnce(() => {
        throw new Error("SecurityError");
      });

      const result = readPersistedScrapeJob();
      expect(result).toBeNull();
    });
  });

  // ---- resume / dismiss flow (integration-style) ----
  describe("resume & dismiss flow", () => {
    it("persist → read → clear simulates dismiss", () => {
      persistScrapeJob("j-1", "ck-1", { seller: "iaai" });
      const found = readPersistedScrapeJob();
      expect(found).not.toBeNull();
      expect(found!.jobId).toBe("j-1");

      // Dismiss = clear
      clearPersistedScrapeJob();
      expect(readPersistedScrapeJob()).toBeNull();
    });

    it("persist → read simulates resume (data intact)", () => {
      const criteria = { dateFrom: "2025-01-01", dateTo: "2025-06-01" };
      persistScrapeJob("j-5", "ck-5", criteria);

      const found = readPersistedScrapeJob();
      expect(found).not.toBeNull();
      expect(found!.criteria).toEqual(criteria);
      expect(found!.cacheKey).toBe("ck-5");
      // After resume the entry stays in localStorage (cleared on job completion)
      expect(store.has(SCRAPE_JOB_STORAGE_KEY)).toBe(true);
    });

    it("persist → read → clear simulates not_found cleanup", () => {
      persistScrapeJob("expired-job", "ck-old", { seller: "copart" });
      const found = readPersistedScrapeJob();
      expect(found).not.toBeNull();
      expect(found!.jobId).toBe("expired-job");

      // Simulate: poll returned not_found → cleanup
      clearPersistedScrapeJob();
      expect(readPersistedScrapeJob()).toBeNull();
      expect(store.has(SCRAPE_JOB_STORAGE_KEY)).toBe(false);
    });
  });
});
