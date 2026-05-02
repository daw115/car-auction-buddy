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

function validCriteria() {
  return { make: "Toyota", budget_usd: 15000 };
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
      persistScrapeJob("job-1", "cache-abc", { make: "Toyota", budget_usd: 10000 });

      const raw = store.get(SCRAPE_JOB_STORAGE_KEY);
      expect(raw).toBeDefined();
      const parsed = JSON.parse(raw!);
      expect(parsed.jobId).toBe("job-1");
      expect(parsed.cacheKey).toBe("cache-abc");
      expect(parsed.criteria).toEqual({ make: "Toyota", budget_usd: 10000 });
      expect(parsed.startedAt).toBeTypeOf("number");
    });

    it("overwrites previous entry", () => {
      persistScrapeJob("job-1", "c1", validCriteria());
      persistScrapeJob("job-2", "c2", { make: "Honda", budget_usd: 5000 });

      const parsed = JSON.parse(store.get(SCRAPE_JOB_STORAGE_KEY)!);
      expect(parsed.jobId).toBe("job-2");
    });

    it("does not throw when localStorage.setItem throws", () => {
      (localStorageMock.setItem as ReturnType<typeof vi.fn>).mockImplementationOnce(() => {
        throw new Error("QuotaExceededError");
      });

      expect(() => persistScrapeJob("j", "c", validCriteria())).not.toThrow();
    });
  });

  // ---- clearPersistedScrapeJob ----
  describe("clearPersistedScrapeJob", () => {
    it("removes the key from localStorage", () => {
      seedStorage({ jobId: "job-1", cacheKey: "c", criteria: validCriteria(), startedAt: 1 });
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
    it("returns null job when nothing stored", () => {
      const { job, validationErrors } = readPersistedScrapeJob();
      expect(job).toBeNull();
      expect(validationErrors).toEqual([]);
    });

    it("returns validated job when valid data stored", () => {
      const criteria = { make: "BMW", budget_usd: 20000, model: "X5" };
      seedStorage({
        jobId: "j-42",
        cacheKey: "ck",
        criteria,
        startedAt: 1700000000000,
      });

      const { job, validationErrors } = readPersistedScrapeJob();
      expect(validationErrors).toEqual([]);
      expect(job).not.toBeNull();
      expect(job!.jobId).toBe("j-42");
      expect(job!.criteria.make).toBe("BMW");
      expect(job!.criteria.budget_usd).toBe(20000);
    });

    it("returns null and clears storage when jobId is empty", () => {
      seedStorage({ jobId: "", cacheKey: "c", criteria: validCriteria(), startedAt: 1 });

      const { job } = readPersistedScrapeJob();
      expect(job).toBeNull();
      expect(store.has(SCRAPE_JOB_STORAGE_KEY)).toBe(false);
    });

    it("returns null and clears storage when jobId is missing", () => {
      seedStorage({ cacheKey: "c", criteria: validCriteria(), startedAt: 1 });

      const { job } = readPersistedScrapeJob();
      expect(job).toBeNull();
      expect(store.has(SCRAPE_JOB_STORAGE_KEY)).toBe(false);
    });

    it("returns null and clears storage on malformed JSON", () => {
      store.set(SCRAPE_JOB_STORAGE_KEY, "not-json{{{");

      const { job } = readPersistedScrapeJob();
      expect(job).toBeNull();
      expect(store.has(SCRAPE_JOB_STORAGE_KEY)).toBe(false);
    });

    it("returns null when localStorage.getItem throws", () => {
      (localStorageMock.getItem as ReturnType<typeof vi.fn>).mockImplementationOnce(() => {
        throw new Error("SecurityError");
      });

      const { job } = readPersistedScrapeJob();
      expect(job).toBeNull();
    });
  });

  // ---- criteria validation ----
  describe("criteria validation", () => {
    it("rejects criteria with missing make", () => {
      seedStorage({ jobId: "j-1", cacheKey: "c", criteria: { budget_usd: 5000 }, startedAt: Date.now() });

      const { job, validationErrors } = readPersistedScrapeJob();
      expect(job).toBeNull();
      expect(validationErrors.length).toBeGreaterThan(0);
      expect(validationErrors.some((e) => e.includes("make"))).toBe(true);
      expect(store.has(SCRAPE_JOB_STORAGE_KEY)).toBe(false);
    });

    it("rejects criteria with missing budget_usd", () => {
      seedStorage({ jobId: "j-1", cacheKey: "c", criteria: { make: "Ford" }, startedAt: Date.now() });

      const { job, validationErrors } = readPersistedScrapeJob();
      expect(job).toBeNull();
      expect(validationErrors.length).toBeGreaterThan(0);
      expect(validationErrors.some((e) => e.includes("budget_usd"))).toBe(true);
    });

    it("rejects criteria with empty make", () => {
      seedStorage({ jobId: "j-1", cacheKey: "c", criteria: { make: "", budget_usd: 5000 }, startedAt: Date.now() });

      const { job, validationErrors } = readPersistedScrapeJob();
      expect(job).toBeNull();
      expect(validationErrors.some((e) => e.toLowerCase().includes("make"))).toBe(true);
    });

    it("rejects criteria with budget out of range", () => {
      seedStorage({ jobId: "j-1", cacheKey: "c", criteria: { make: "BMW", budget_usd: -500 }, startedAt: Date.now() });

      const { job, validationErrors } = readPersistedScrapeJob();
      expect(job).toBeNull();
      expect(validationErrors.length).toBeGreaterThan(0);
    });

    it("rejects criteria with year_from out of range", () => {
      seedStorage({ jobId: "j-1", cacheKey: "c", criteria: { make: "BMW", budget_usd: 5000, year_from: 1800 }, startedAt: Date.now() });

      const { job, validationErrors } = readPersistedScrapeJob();
      expect(job).toBeNull();
      expect(validationErrors.some((e) => e.includes("year_from"))).toBe(true);
    });

    it("accepts valid optional fields", () => {
      const criteria = {
        make: "Audi",
        budget_usd: 25000,
        model: "A4",
        year_from: 2018,
        year_to: 2024,
        max_odometer_mi: 80000,
        sources: ["copart", "iaai"],
        max_results: 50,
      };
      seedStorage({ jobId: "j-1", cacheKey: "c", criteria, startedAt: Date.now() });

      const { job, validationErrors } = readPersistedScrapeJob();
      expect(validationErrors).toEqual([]);
      expect(job).not.toBeNull();
      expect(job!.criteria).toMatchObject({ make: "Audi", budget_usd: 25000, year_from: 2018 });
    });

    it("rejects when cacheKey is missing", () => {
      seedStorage({ jobId: "j-1", criteria: validCriteria(), startedAt: Date.now() } as any);

      const { job, validationErrors } = readPersistedScrapeJob();
      expect(job).toBeNull();
      expect(validationErrors.some((e) => e.includes("cache"))).toBe(true);
    });

    it("rejects when startedAt is invalid", () => {
      seedStorage({ jobId: "j-1", cacheKey: "c", criteria: validCriteria(), startedAt: -1 });

      const { job, validationErrors } = readPersistedScrapeJob();
      expect(job).toBeNull();
      expect(validationErrors.some((e) => e.includes("znacznik"))).toBe(true);
    });
  });

  // ---- resume / dismiss flow (integration-style) ----
  describe("resume & dismiss flow", () => {
    it("persist → read → clear simulates dismiss", () => {
      persistScrapeJob("j-1", "ck-1", { make: "Kia", budget_usd: 8000 });
      const { job } = readPersistedScrapeJob();
      expect(job).not.toBeNull();
      expect(job!.jobId).toBe("j-1");

      // Dismiss = clear
      clearPersistedScrapeJob();
      expect(readPersistedScrapeJob().job).toBeNull();
    });

    it("persist → read simulates resume (data intact)", () => {
      const criteria = { make: "Mazda", budget_usd: 12000, model: "CX-5" };
      persistScrapeJob("j-5", "ck-5", criteria);

      const { job } = readPersistedScrapeJob();
      expect(job).not.toBeNull();
      expect(job!.criteria.make).toBe("Mazda");
      expect(job!.cacheKey).toBe("ck-5");
      expect(store.has(SCRAPE_JOB_STORAGE_KEY)).toBe(true);
    });

    it("persist → read → clear simulates not_found cleanup", () => {
      persistScrapeJob("expired-job", "ck-old", { make: "Nissan", budget_usd: 7000 });
      const { job } = readPersistedScrapeJob();
      expect(job).not.toBeNull();
      expect(job!.jobId).toBe("expired-job");

      clearPersistedScrapeJob();
      expect(readPersistedScrapeJob().job).toBeNull();
      expect(store.has(SCRAPE_JOB_STORAGE_KEY)).toBe(false);
    });

    it("dismiss clears localStorage completely — key no longer exists", () => {
      persistScrapeJob("j-dismiss", "ck-d", { make: "Hyundai", budget_usd: 11000 });
      expect(store.has(SCRAPE_JOB_STORAGE_KEY)).toBe(true);

      // Simulate dismiss: clear + verify no residual data
      clearPersistedScrapeJob();
      expect(store.has(SCRAPE_JOB_STORAGE_KEY)).toBe(false);
      expect(store.size).toBe(0);

      // Subsequent read returns clean state
      const { job, validationErrors } = readPersistedScrapeJob();
      expect(job).toBeNull();
      expect(validationErrors).toEqual([]);
    });

    it("dismiss after multiple persists only removes latest entry", () => {
      persistScrapeJob("j-a", "c-a", validCriteria());
      persistScrapeJob("j-b", "c-b", validCriteria()); // overwrites

      clearPersistedScrapeJob();
      expect(readPersistedScrapeJob().job).toBeNull();
    });
  });

  // ---- localStorage error resilience ----
  describe("localStorage error resilience", () => {
    it("persistScrapeJob silently fails when setItem throws QuotaExceededError", () => {
      (localStorageMock.setItem as ReturnType<typeof vi.fn>).mockImplementationOnce(() => {
        throw new DOMException("quota exceeded", "QuotaExceededError");
      });

      expect(() => persistScrapeJob("j", "c", validCriteria())).not.toThrow();
      // Nothing was stored
      expect(store.has(SCRAPE_JOB_STORAGE_KEY)).toBe(false);
    });

    it("persistScrapeJob silently fails when setItem throws SecurityError", () => {
      (localStorageMock.setItem as ReturnType<typeof vi.fn>).mockImplementationOnce(() => {
        throw new DOMException("access denied", "SecurityError");
      });

      expect(() => persistScrapeJob("j", "c", validCriteria())).not.toThrow();
    });

    it("clearPersistedScrapeJob silently fails when removeItem throws", () => {
      store.set(SCRAPE_JOB_STORAGE_KEY, "data");
      (localStorageMock.removeItem as ReturnType<typeof vi.fn>).mockImplementationOnce(() => {
        throw new DOMException("access denied", "SecurityError");
      });

      expect(() => clearPersistedScrapeJob()).not.toThrow();
      // Data remains because removeItem failed
      expect(store.has(SCRAPE_JOB_STORAGE_KEY)).toBe(true);
    });

    it("readPersistedScrapeJob returns empty result when getItem throws", () => {
      (localStorageMock.getItem as ReturnType<typeof vi.fn>).mockImplementationOnce(() => {
        throw new DOMException("access denied", "SecurityError");
      });

      const { job, validationErrors } = readPersistedScrapeJob();
      expect(job).toBeNull();
      expect(validationErrors).toEqual([]);
    });

    it("readPersistedScrapeJob returns empty when getItem throws TypeError", () => {
      (localStorageMock.getItem as ReturnType<typeof vi.fn>).mockImplementationOnce(() => {
        throw new TypeError("Cannot read properties of null");
      });

      const { job, validationErrors } = readPersistedScrapeJob();
      expect(job).toBeNull();
      expect(validationErrors).toEqual([]);
    });

    it("readPersistedScrapeJob clears storage when getItem returns non-JSON and removeItem also throws", () => {
      store.set(SCRAPE_JOB_STORAGE_KEY, "{{broken");
      // removeItem called inside clearPersistedScrapeJob will also throw
      const originalRemove = localStorageMock.removeItem;
      (localStorageMock.removeItem as ReturnType<typeof vi.fn>).mockImplementation(() => {
        throw new DOMException("denied", "SecurityError");
      });

      // Should not throw despite both parse error and removeItem error
      const { job, validationErrors } = readPersistedScrapeJob();
      expect(job).toBeNull();
      expect(validationErrors).toEqual([]);

      // Restore
      (localStorageMock.removeItem as ReturnType<typeof vi.fn>).mockImplementation(
        (key: string) => { store.delete(key); },
      );
    });

    it("persist → getItem throws → read returns null (no stale resume)", () => {
      persistScrapeJob("j-1", "c-1", validCriteria());
      expect(store.has(SCRAPE_JOB_STORAGE_KEY)).toBe(true);

      // Simulate private browsing or cookie clearing between persist and read
      (localStorageMock.getItem as ReturnType<typeof vi.fn>).mockImplementationOnce(() => {
        throw new Error("Storage disabled");
      });

      const { job } = readPersistedScrapeJob();
      expect(job).toBeNull();
    });

    it("all three ops are safe when localStorage is completely broken", () => {
      const throwFn = () => { throw new Error("storage disabled"); };
      (localStorageMock.getItem as ReturnType<typeof vi.fn>).mockImplementation(throwFn);
      (localStorageMock.setItem as ReturnType<typeof vi.fn>).mockImplementation(throwFn);
      (localStorageMock.removeItem as ReturnType<typeof vi.fn>).mockImplementation(throwFn);

      expect(() => persistScrapeJob("j", "c", validCriteria())).not.toThrow();
      expect(() => clearPersistedScrapeJob()).not.toThrow();
      const { job, validationErrors } = readPersistedScrapeJob();
      expect(job).toBeNull();
      expect(validationErrors).toEqual([]);
    });
  });
});
