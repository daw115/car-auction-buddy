// @vitest-environment jsdom
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom/vitest";
import { ResumeJobBanner } from "./ResumeJobBanner";
import type { ValidatedScrapeJob } from "@/lib/scrape-job-storage";

function makeJob(overrides?: Partial<ValidatedScrapeJob>): ValidatedScrapeJob {
  return {
    jobId: "abc12345-def6-7890",
    cacheKey: "ck-test",
    criteria: { make: "Toyota", budget_usd: 15000 },
    startedAt: Date.now() - 60_000,
    ...overrides,
  };
}

const defaults = () => ({
  onResume: vi.fn(),
  onDismiss: vi.fn(),
  onClearErrors: vi.fn(),
});

describe("ResumeJobBanner", () => {
  afterEach(cleanup);
  // ---- visibility ----
  it("renders nothing when no pending resume and no errors", () => {
    const { container } = render(
      <ResumeJobBanner pendingResume={null} validationErrors={[]} {...defaults()} />,
    );
    expect(container.innerHTML).toBe("");
  });

  it('shows "Wznów" and "Odrzuć" buttons when pendingResume is set', () => {
    render(
      <ResumeJobBanner pendingResume={makeJob()} validationErrors={[]} {...defaults()} />,
    );

    expect(screen.getByRole("button", { name: /Wznów/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Odrzuć/i })).toBeInTheDocument();
  });

  it("displays job ID prefix in the banner", () => {
    render(
      <ResumeJobBanner
        pendingResume={makeJob({ jobId: "xyz98765-aaa" })}
        validationErrors={[]}
        {...defaults()}
      />,
    );

    expect(screen.getByText("#xyz98765")).toBeInTheDocument();
  });

  it("displays criteria summary (make, budget, model, years)", () => {
    render(
      <ResumeJobBanner
        pendingResume={makeJob({
          criteria: { make: "BMW", budget_usd: 25000, model: "X5", year_from: 2020, year_to: 2024 },
        })}
        validationErrors={[]}
        {...defaults()}
      />,
    );

    expect(screen.getByText("BMW")).toBeInTheDocument();
    expect(screen.getByText("X5")).toBeInTheDocument();
    expect(screen.getByText("2020")).toBeInTheDocument();
    expect(screen.getByText("2024")).toBeInTheDocument();
  });

  // ---- interactions ----
  it('calls onResume when "Wznów" is clicked', async () => {
    const cbs = defaults();
    render(
      <ResumeJobBanner pendingResume={makeJob()} validationErrors={[]} {...cbs} />,
    );

    await userEvent.click(screen.getByRole("button", { name: /Wznów/i }));
    expect(cbs.onResume).toHaveBeenCalledTimes(1);
  });

  it('calls onDismiss when "Odrzuć" is clicked', async () => {
    const cbs = defaults();
    render(
      <ResumeJobBanner pendingResume={makeJob()} validationErrors={[]} {...cbs} />,
    );

    await userEvent.click(screen.getByRole("button", { name: /Odrzuć/i }));
    expect(cbs.onDismiss).toHaveBeenCalledTimes(1);
  });

  // ---- validation errors ----
  it("shows validation errors when present and no pendingResume", () => {
    render(
      <ResumeJobBanner
        pendingResume={null}
        validationErrors={["make: Marka jest wymagana", "budget_usd: Expected number"]}
        {...defaults()}
      />,
    );

    expect(screen.getByText(/nieprawidłowe/)).toBeInTheDocument();
    expect(screen.getByText("make: Marka jest wymagana")).toBeInTheDocument();
    expect(screen.getByText("budget_usd: Expected number")).toBeInTheDocument();
    // "Wznów" should NOT be visible
    expect(screen.queryByRole("button", { name: /Wznów/i })).not.toBeInTheDocument();
  });

  it('calls onClearErrors when "Zamknij" is clicked on error banner', async () => {
    const cbs = defaults();
    render(
      <ResumeJobBanner
        pendingResume={null}
        validationErrors={["some error"]}
        {...cbs}
      />,
    );

    await userEvent.click(screen.getByRole("button", { name: /Zamknij/i }));
    expect(cbs.onClearErrors).toHaveBeenCalledTimes(1);
  });

  it("shows resume banner (not errors) when both pendingResume and errors exist", () => {
    render(
      <ResumeJobBanner
        pendingResume={makeJob()}
        validationErrors={["should be ignored"]}
        {...defaults()}
      />,
    );

    expect(screen.getByRole("button", { name: /Wznów/i })).toBeInTheDocument();
    expect(screen.queryByText(/nieprawidłowe/)).not.toBeInTheDocument();
  });

  // ---- localStorage failures → UI stays clean ----
  describe("behavior when localStorage errors cause null pendingResume", () => {
    it("renders nothing when both pendingResume and validationErrors are empty (simulates getItem throw)", () => {
      // When readPersistedScrapeJob catches a getItem error it returns { job: null, validationErrors: [] }
      // The parent passes both as props → banner should be invisible
      const { container } = render(
        <ResumeJobBanner pendingResume={null} validationErrors={[]} {...defaults()} />,
      );
      expect(container.innerHTML).toBe("");
    });

    it("shows only error list when storage returned validation errors (simulates corrupt data)", () => {
      render(
        <ResumeJobBanner
          pendingResume={null}
          validationErrors={[
            "make: Marka jest wymagana",
            "budget_usd: Required",
          ]}
          {...defaults()}
        />,
      );

      // Error banner visible
      expect(screen.getByText(/nieprawidłowe/)).toBeInTheDocument();
      expect(screen.getByText("make: Marka jest wymagana")).toBeInTheDocument();
      expect(screen.getByText("budget_usd: Required")).toBeInTheDocument();

      // Resume/dismiss buttons NOT visible
      expect(screen.queryByRole("button", { name: /Wznów/i })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: /Odrzuć/i })).not.toBeInTheDocument();

      // Zamknij button IS visible
      expect(screen.getByRole("button", { name: /Zamknij/i })).toBeInTheDocument();
    });

    it("error banner can be dismissed without side effects", async () => {
      const cbs = defaults();
      render(
        <ResumeJobBanner pendingResume={null} validationErrors={["err"]} {...cbs} />,
      );

      await userEvent.click(screen.getByRole("button", { name: /Zamknij/i }));
      expect(cbs.onClearErrors).toHaveBeenCalledTimes(1);
      // onResume and onDismiss should not have been called
      expect(cbs.onResume).not.toHaveBeenCalled();
      expect(cbs.onDismiss).not.toHaveBeenCalled();
    });

    it("does not crash with empty validation errors array and null resume", () => {
      // Edge case: everything empty, no crash
      expect(() =>
        render(
          <ResumeJobBanner pendingResume={null} validationErrors={[]} {...defaults()} />,
        ),
      ).not.toThrow();
    });
  });

  // ---- dismiss flow: banner disappears + storage cleared ----
  describe("dismiss flow (Odrzuć)", () => {
    it("banner disappears after re-render with null pendingResume (simulates parent state update)", async () => {
      const cbs = defaults();
      const job = makeJob();
      const { rerender, container } = render(
        <ResumeJobBanner pendingResume={job} validationErrors={[]} {...cbs} />,
      );

      // Banner visible
      expect(screen.getByRole("button", { name: /Odrzuć/i })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /Wznów/i })).toBeInTheDocument();

      // Click Odrzuć
      await userEvent.click(screen.getByRole("button", { name: /Odrzuć/i }));
      expect(cbs.onDismiss).toHaveBeenCalledTimes(1);

      // Parent would set pendingResume to null → re-render
      rerender(
        <ResumeJobBanner pendingResume={null} validationErrors={[]} {...cbs} />,
      );

      // Banner gone
      expect(container.innerHTML).toBe("");
      expect(screen.queryByRole("button", { name: /Wznów/i })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: /Odrzuć/i })).not.toBeInTheDocument();
    });

    it("criteria summary disappears together with the banner after dismiss", async () => {
      const cbs = defaults();
      const job = makeJob({ criteria: { make: "Honda", budget_usd: 9000, model: "Civic" } });
      const { rerender } = render(
        <ResumeJobBanner pendingResume={job} validationErrors={[]} {...cbs} />,
      );

      // Criteria visible
      expect(screen.getByText("Honda")).toBeInTheDocument();
      expect(screen.getByText("Civic")).toBeInTheDocument();

      await userEvent.click(screen.getByRole("button", { name: /Odrzuć/i }));

      // Parent clears state
      rerender(
        <ResumeJobBanner pendingResume={null} validationErrors={[]} {...cbs} />,
      );

      expect(screen.queryByText("Honda")).not.toBeInTheDocument();
      expect(screen.queryByText("Civic")).not.toBeInTheDocument();
    });

    it("onResume is NOT called when Odrzuć is clicked", async () => {
      const cbs = defaults();
      render(
        <ResumeJobBanner pendingResume={makeJob()} validationErrors={[]} {...cbs} />,
      );

      await userEvent.click(screen.getByRole("button", { name: /Odrzuć/i }));
      expect(cbs.onDismiss).toHaveBeenCalledTimes(1);
      expect(cbs.onResume).not.toHaveBeenCalled();
      expect(cbs.onClearErrors).not.toHaveBeenCalled();
    });
  });
});
