// @vitest-environment jsdom
/**
 * Integration test: full resume flow from localStorage → banner → user action.
 * Uses a wrapper component that mimics the parent logic from index.tsx
 * (readPersistedScrapeJob on mount, state management, callbacks).
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom/vitest";
import { useState, useEffect, useRef } from "react";
import { ResumeJobBanner } from "./ResumeJobBanner";
import {
  SCRAPE_JOB_STORAGE_KEY,
  persistScrapeJob,
  clearPersistedScrapeJob,
  readPersistedScrapeJob,
  type ValidatedScrapeJob,
} from "@/lib/scrape-job-storage";

/* ---- localStorage mock ---- */
const store = new Map<string, string>();
const localStorageMock: Storage = {
  getItem: vi.fn((key: string) => store.get(key) ?? null),
  setItem: vi.fn((key: string, value: string) => store.set(key, value)),
  removeItem: vi.fn((key: string) => store.delete(key)),
  clear: vi.fn(() => store.clear()),
  get length() { return store.size; },
  key: vi.fn(() => null),
};
Object.defineProperty(globalThis, "localStorage", { value: localStorageMock, writable: true });

/* ---- Spy to track resume side-effects ---- */
interface ResumeEvent {
  jobId: string;
  cacheKey: string;
  criteria: Record<string, unknown>;
}

/** Ref handle exposed by the harness so tests can simulate job lifecycle events */
interface HarnessHandle {
  completeJob: () => void;
  failJob: () => void;
  cancelJob: () => void;
}

/**
 * Wrapper component that replicates the parent flow from index.tsx:
 * - On mount: reads localStorage and sets pendingResume (NO auto-resume)
 * - "Wznów" → calls onResume callback, clears pendingResume, keeps localStorage
 * - "Odrzuć" → clears pendingResume AND localStorage
 * - completeJob/failJob/cancelJob → clears busy + localStorage (like real poller)
 */
function ResumeFlowHarness({
  onResumeTriggered,
  handleRef,
}: {
  onResumeTriggered: (e: ResumeEvent) => void;
  handleRef?: React.MutableRefObject<HarnessHandle | null>;
}) {
  const [pendingResume, setPendingResume] = useState<ValidatedScrapeJob | null>(null);
  const [validationErrors, setValidationErrors] = useState<string[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [jobResult, setJobResult] = useState<string | null>(null);
  const wasResumedRef = useRef(false);

  // On mount: detect job in localStorage (mirrors index.tsx useEffect)
  useEffect(() => {
    const { job, validationErrors: errs } = readPersistedScrapeJob();
    if (errs.length > 0) {
      setValidationErrors(errs);
    } else if (job) {
      setPendingResume(job);
    }
  }, []);

  // Expose lifecycle controls to tests
  useEffect(() => {
    if (!handleRef) return;
    handleRef.current = {
      completeJob: () => {
        setBusy(null);
        clearPersistedScrapeJob();
        setJobResult("done");
      },
      failJob: () => {
        setBusy(null);
        clearPersistedScrapeJob();
        setJobResult("failed");
      },
      cancelJob: () => {
        setBusy(null);
        clearPersistedScrapeJob();
        setJobResult("cancelled");
      },
    };
  });

  function handleResume() {
    if (!pendingResume) return;
    const saved = pendingResume;
    setPendingResume(null);
    setBusy("scraper");
    wasResumedRef.current = true;
    setJobResult(null);
    onResumeTriggered({
      jobId: saved.jobId,
      cacheKey: saved.cacheKey,
      criteria: saved.criteria,
    });
    // Note: localStorage is NOT cleared here (only on job completion/cancel)
  }

  function handleDismiss() {
    setPendingResume(null);
    clearPersistedScrapeJob();
  }

  return (
    <div>
      <ResumeJobBanner
        pendingResume={pendingResume}
        validationErrors={validationErrors}
        onResume={handleResume}
        onDismiss={handleDismiss}
        onClearErrors={() => setValidationErrors([])}
      />
      {busy && <div data-testid="busy-indicator">busy: {busy}</div>}
      {jobResult && <div data-testid="job-result">{jobResult}</div>}
      {!pendingResume && !busy && !validationErrors.length && !jobResult && (
        <div data-testid="idle-state">idle</div>
      )}
    </div>
  );
}

/* ---- Tests ---- */
describe("Resume flow integration", () => {
  beforeEach(() => {
    store.clear();
    vi.clearAllMocks();
  });
  afterEach(cleanup);

  it("does NOT auto-resume on mount — shows banner with buttons instead", () => {
    // Seed localStorage with a valid job
    persistScrapeJob("job-e2e-1", "ck-e2e", { make: "Toyota", budget_usd: 12000 });

    const onResume = vi.fn();
    render(<ResumeFlowHarness onResumeTriggered={onResume} />);

    // Banner is visible
    expect(screen.getByRole("button", { name: /Wznów/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Odrzuć/i })).toBeInTheDocument();

    // Auto-resume did NOT happen
    expect(onResume).not.toHaveBeenCalled();
    expect(screen.queryByTestId("busy-indicator")).not.toBeInTheDocument();
  });

  it("clicking Wznów triggers resume with correct data and hides the banner", async () => {
    persistScrapeJob("job-resume-42", "cache-hash-xyz", {
      make: "BMW",
      budget_usd: 25000,
      model: "X5",
      year_from: 2020,
      year_to: 2024,
    });

    const onResume = vi.fn();
    render(<ResumeFlowHarness onResumeTriggered={onResume} />);

    // Banner shows correct data
    expect(screen.getByText("#job-resu")).toBeInTheDocument(); // first 8 chars
    expect(screen.getByText("BMW")).toBeInTheDocument();
    expect(screen.getByText("X5")).toBeInTheDocument();
    expect(screen.getByText("2020")).toBeInTheDocument();
    expect(screen.getByText("2024")).toBeInTheDocument();

    // Click Wznów
    await userEvent.click(screen.getByRole("button", { name: /Wznów/i }));

    // Resume callback fired with correct data
    expect(onResume).toHaveBeenCalledTimes(1);
    expect(onResume).toHaveBeenCalledWith({
      jobId: "job-resume-42",
      cacheKey: "cache-hash-xyz",
      criteria: expect.objectContaining({ make: "BMW", budget_usd: 25000, model: "X5" }),
    });

    // Banner disappeared
    expect(screen.queryByRole("button", { name: /Wznów/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Odrzuć/i })).not.toBeInTheDocument();

    // System is now busy
    expect(screen.getByTestId("busy-indicator")).toHaveTextContent("busy: scraper");

    // localStorage still has the job (cleared only on completion/cancel, not on resume)
    expect(store.has(SCRAPE_JOB_STORAGE_KEY)).toBe(true);
  });

  it("clicking Odrzuć clears localStorage and hides the banner without resuming", async () => {
    persistScrapeJob("job-dismiss-99", "ck-d", { make: "Honda", budget_usd: 8000 });

    const onResume = vi.fn();
    render(<ResumeFlowHarness onResumeTriggered={onResume} />);

    // Banner visible
    expect(screen.getByRole("button", { name: /Wznów/i })).toBeInTheDocument();

    // Click Odrzuć
    await userEvent.click(screen.getByRole("button", { name: /Odrzuć/i }));

    // Banner gone
    expect(screen.queryByRole("button", { name: /Wznów/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Odrzuć/i })).not.toBeInTheDocument();

    // Resume was NOT called
    expect(onResume).not.toHaveBeenCalled();

    // localStorage cleared
    expect(store.has(SCRAPE_JOB_STORAGE_KEY)).toBe(false);

    // App is idle
    expect(screen.getByTestId("idle-state")).toBeInTheDocument();
  });

  it("shows nothing when localStorage is empty — no banner, no auto-resume", () => {
    const onResume = vi.fn();
    render(<ResumeFlowHarness onResumeTriggered={onResume} />);

    expect(screen.queryByRole("button", { name: /Wznów/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Odrzuć/i })).not.toBeInTheDocument();
    expect(onResume).not.toHaveBeenCalled();
    expect(screen.getByTestId("idle-state")).toBeInTheDocument();
  });

  it("shows validation errors and hides banner when localStorage has invalid criteria", () => {
    // Seed with invalid criteria (missing required make)
    store.set(
      SCRAPE_JOB_STORAGE_KEY,
      JSON.stringify({ jobId: "j-bad", cacheKey: "c", criteria: { budget_usd: 5000 }, startedAt: Date.now() }),
    );

    const onResume = vi.fn();
    render(<ResumeFlowHarness onResumeTriggered={onResume} />);

    // Error banner shown
    expect(screen.getByText(/nieprawidłowe/)).toBeInTheDocument();

    // Resume/dismiss buttons NOT shown
    expect(screen.queryByRole("button", { name: /Wznów/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Odrzuć/i })).not.toBeInTheDocument();

    // Auto-resume did NOT happen
    expect(onResume).not.toHaveBeenCalled();

    // localStorage was auto-cleared by validation
    expect(store.has(SCRAPE_JOB_STORAGE_KEY)).toBe(false);
  });

  it("after dismiss, a subsequent mount shows no banner (simulates page reload)", async () => {
    persistScrapeJob("job-reload", "ck-r", { make: "Mazda", budget_usd: 14000 });

    const onResume = vi.fn();
    const { unmount } = render(<ResumeFlowHarness onResumeTriggered={onResume} />);

    // Dismiss
    await userEvent.click(screen.getByRole("button", { name: /Odrzuć/i }));
    expect(store.has(SCRAPE_JOB_STORAGE_KEY)).toBe(false);

    // Unmount and remount (simulates page reload)
    unmount();
    render(<ResumeFlowHarness onResumeTriggered={onResume} />);

    // No banner
    expect(screen.queryByRole("button", { name: /Wznów/i })).not.toBeInTheDocument();
    expect(screen.getByTestId("idle-state")).toBeInTheDocument();
    expect(onResume).not.toHaveBeenCalled();
  });

  it("after resume, a subsequent mount still shows banner (localStorage not cleared until job ends)", async () => {
    persistScrapeJob("job-persist", "ck-p", { make: "Audi", budget_usd: 30000 });

    const onResume = vi.fn();
    const { unmount } = render(<ResumeFlowHarness onResumeTriggered={onResume} />);

    // Resume
    await userEvent.click(screen.getByRole("button", { name: /Wznów/i }));
    expect(onResume).toHaveBeenCalledTimes(1);
    expect(store.has(SCRAPE_JOB_STORAGE_KEY)).toBe(true);

    // Unmount and remount (simulates another reload while job still runs)
    unmount();
    render(<ResumeFlowHarness onResumeTriggered={onResume} />);

    // Banner reappears because localStorage still has the job
    expect(screen.getByRole("button", { name: /Wznów/i })).toBeInTheDocument();
  });

  // ---- Job lifecycle after resume ----
  describe("job completion clears banner and localStorage", () => {
    it("after resume → job done: banner gone, localStorage cleared, result shown", async () => {
      persistScrapeJob("job-done-1", "ck-done", { make: "Volvo", budget_usd: 22000 });

      const onResume = vi.fn();
      const handleRef = { current: null as HarnessHandle | null };
      render(<ResumeFlowHarness onResumeTriggered={onResume} handleRef={handleRef} />);

      // Click Wznów
      await userEvent.click(screen.getByRole("button", { name: /Wznów/i }));
      expect(screen.getByTestId("busy-indicator")).toHaveTextContent("busy: scraper");
      expect(store.has(SCRAPE_JOB_STORAGE_KEY)).toBe(true);

      // Simulate job completion (like poller receiving "done" status)
      act(() => handleRef.current!.completeJob());

      // Busy indicator gone
      expect(screen.queryByTestId("busy-indicator")).not.toBeInTheDocument();
      // Banner NOT shown (no pendingResume)
      expect(screen.queryByRole("button", { name: /Wznów/i })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: /Odrzuć/i })).not.toBeInTheDocument();
      // localStorage cleared
      expect(store.has(SCRAPE_JOB_STORAGE_KEY)).toBe(false);
      // Result indicator shown
      expect(screen.getByTestId("job-result")).toHaveTextContent("done");
    });

    it("after resume → job failed: localStorage cleared, no banner", async () => {
      persistScrapeJob("job-fail-1", "ck-fail", { make: "Fiat", budget_usd: 6000 });

      const onResume = vi.fn();
      const handleRef = { current: null as HarnessHandle | null };
      render(<ResumeFlowHarness onResumeTriggered={onResume} handleRef={handleRef} />);

      await userEvent.click(screen.getByRole("button", { name: /Wznów/i }));
      expect(store.has(SCRAPE_JOB_STORAGE_KEY)).toBe(true);

      act(() => handleRef.current!.failJob());

      expect(screen.queryByTestId("busy-indicator")).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: /Wznów/i })).not.toBeInTheDocument();
      expect(store.has(SCRAPE_JOB_STORAGE_KEY)).toBe(false);
      expect(screen.getByTestId("job-result")).toHaveTextContent("failed");
    });

    it("after resume → job cancelled: localStorage cleared, no banner", async () => {
      persistScrapeJob("job-cancel-1", "ck-cancel", { make: "Peugeot", budget_usd: 9000 });

      const onResume = vi.fn();
      const handleRef = { current: null as HarnessHandle | null };
      render(<ResumeFlowHarness onResumeTriggered={onResume} handleRef={handleRef} />);

      await userEvent.click(screen.getByRole("button", { name: /Wznów/i }));

      act(() => handleRef.current!.cancelJob());

      expect(store.has(SCRAPE_JOB_STORAGE_KEY)).toBe(false);
      expect(screen.queryByRole("button", { name: /Wznów/i })).not.toBeInTheDocument();
      expect(screen.getByTestId("job-result")).toHaveTextContent("cancelled");
    });

    it("after job done + remount: no banner appears (localStorage is clean)", async () => {
      persistScrapeJob("job-clean-1", "ck-clean", { make: "Lexus", budget_usd: 35000 });

      const onResume = vi.fn();
      const handleRef = { current: null as HarnessHandle | null };
      const { unmount } = render(
        <ResumeFlowHarness onResumeTriggered={onResume} handleRef={handleRef} />,
      );

      // Resume + complete
      await userEvent.click(screen.getByRole("button", { name: /Wznów/i }));
      act(() => handleRef.current!.completeJob());
      expect(store.has(SCRAPE_JOB_STORAGE_KEY)).toBe(false);

      // Remount (simulates page reload after job finished)
      unmount();
      render(<ResumeFlowHarness onResumeTriggered={onResume} />);

      // No banner, idle state
      expect(screen.queryByRole("button", { name: /Wznów/i })).not.toBeInTheDocument();
      expect(screen.getByTestId("idle-state")).toBeInTheDocument();
      expect(onResume).toHaveBeenCalledTimes(1); // only from earlier click
    });
  });
});
