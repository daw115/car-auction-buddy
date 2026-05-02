/**
 * Pure helpers for persisting / recovering active scrape-job state
 * via localStorage. Extracted from index.tsx so they can be unit-tested.
 */

export const SCRAPE_JOB_STORAGE_KEY = "car-finder:active-scrape-job";

export interface PersistedScrapeJob {
  jobId: string;
  cacheKey: string;
  criteria: Record<string, unknown>;
  startedAt: number;
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
 * Read persisted job from localStorage.
 * Returns `null` when nothing valid is stored.
 * Clears storage automatically if the payload is malformed.
 */
export function readPersistedScrapeJob(): PersistedScrapeJob | null {
  try {
    const raw = localStorage.getItem(SCRAPE_JOB_STORAGE_KEY);
    if (!raw) return null;
    const saved = JSON.parse(raw) as PersistedScrapeJob;
    if (!saved.jobId) {
      clearPersistedScrapeJob();
      return null;
    }
    return saved;
  } catch {
    clearPersistedScrapeJob();
    return null;
  }
}
