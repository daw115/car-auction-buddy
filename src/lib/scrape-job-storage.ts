/**
 * Pure helpers for persisting / recovering active scrape-job state
 * via localStorage. Extracted from index.tsx so they can be unit-tested.
 */

import { z } from "zod";

export const SCRAPE_JOB_STORAGE_KEY = "car-finder:active-scrape-job";

/**
 * Zod schema mirroring the server-side criteriaSchema.
 * Used to validate persisted criteria before allowing resume.
 */
export const persistedCriteriaSchema = z.object({
  make: z.string().min(1, "Marka jest wymagana").max(80),
  model: z.string().max(80).nullable().optional(),
  year_from: z.number().int().min(1900).max(2100).nullable().optional(),
  year_to: z.number().int().min(1900).max(2100).nullable().optional(),
  budget_usd: z.number().min(0).max(1_000_000),
  max_odometer_mi: z.number().int().min(0).max(1_000_000).nullable().optional(),
  excluded_damage_types: z.array(z.string().max(40)).max(20).optional(),
  max_results: z.number().int().min(1).max(100).optional(),
  sources: z.array(z.string().max(20)).max(5).optional(),
});

export type PersistedCriteria = z.infer<typeof persistedCriteriaSchema>;

export interface PersistedScrapeJob {
  jobId: string;
  cacheKey: string;
  criteria: Record<string, unknown>;
  startedAt: number;
}

export interface ValidatedScrapeJob {
  jobId: string;
  cacheKey: string;
  criteria: PersistedCriteria;
  startedAt: number;
}

export interface ReadResult {
  job: ValidatedScrapeJob | null;
  /** Non-empty when criteria failed validation — human-readable issues */
  validationErrors: string[];
}

/** Save active job metadata to localStorage. */
export function persistScrapeJob(
  jobId: string,
  cacheKey: string,
  criteria: Record<string, unknown>,
): void {
  try {
    const value: PersistedScrapeJob = {
      jobId,
      cacheKey,
      criteria,
      startedAt: Date.now(),
    };
    localStorage.setItem(SCRAPE_JOB_STORAGE_KEY, JSON.stringify(value));
  } catch {
    /* quota exceeded etc. */
  }
}

/** Remove persisted job from localStorage. */
export function clearPersistedScrapeJob(): void {
  try {
    localStorage.removeItem(SCRAPE_JOB_STORAGE_KEY);
  } catch {
    /* noop */
  }
}

/**
 * Read and validate persisted job from localStorage.
 * Returns `{ job, validationErrors }`.
 * - If nothing stored → `{ job: null, validationErrors: [] }`.
 * - If stored but criteria invalid → `{ job: null, validationErrors: [...] }` and clears storage.
 * - If malformed JSON / missing jobId → clears storage, returns null.
 */
export function readPersistedScrapeJob(): ReadResult {
  try {
    const raw = localStorage.getItem(SCRAPE_JOB_STORAGE_KEY);
    if (!raw) return { job: null, validationErrors: [] };

    const saved = JSON.parse(raw) as PersistedScrapeJob;

    if (!saved.jobId || typeof saved.jobId !== "string") {
      clearPersistedScrapeJob();
      return { job: null, validationErrors: [] };
    }

    if (!saved.cacheKey || typeof saved.cacheKey !== "string") {
      clearPersistedScrapeJob();
      return { job: null, validationErrors: ["Brak klucza cache — dane uszkodzone."] };
    }

    if (typeof saved.startedAt !== "number" || saved.startedAt <= 0) {
      clearPersistedScrapeJob();
      return { job: null, validationErrors: ["Brak znacznika czasu — dane uszkodzone."] };
    }

    // Validate criteria against the schema
    const result = persistedCriteriaSchema.safeParse(saved.criteria);
    if (!result.success) {
      const errors = result.error.issues.map((i) => {
        const path = i.path.join(".");
        return `${path || "criteria"}: ${i.message}`;
      });
      clearPersistedScrapeJob();
      return { job: null, validationErrors: errors };
    }

    return {
      job: {
        jobId: saved.jobId,
        cacheKey: saved.cacheKey,
        criteria: result.data,
        startedAt: saved.startedAt,
      },
      validationErrors: [],
    };
  } catch {
    clearPersistedScrapeJob();
    return { job: null, validationErrors: [] };
  }
}
