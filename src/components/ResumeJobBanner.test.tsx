// @vitest-environment jsdom
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom/vitest";
import { ResumeJobBanner, formatElapsed } from "./ResumeJobBanner";
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

  // ---- data correctness: jobId, cacheKey, criteria, time ----
  describe("banner displays correct data from localStorage", () => {
    it("shows truncated jobId (first 8 chars)", () => {
      render(
        <ResumeJobBanner
          pendingResume={makeJob({ jobId: "abcdefgh-1234-5678-9abc" })}
          validationErrors={[]}
          {...defaults()}
        />,
      );
      expect(screen.getByText("#abcdefgh")).toBeInTheDocument();
      expect(screen.queryByText("abcdefgh-1234-5678-9abc")).not.toBeInTheDocument();
    });

    it("shows truncated cacheKey (first 12 chars)", () => {
      render(
        <ResumeJobBanner
          pendingResume={makeJob({ cacheKey: "sha256-abc1234567890xyz" })}
          validationErrors={[]}
          {...defaults()}
        />,
      );
      const el = screen.getByTestId("cache-key");
      expect(el.textContent).toBe("sha256-abc12");
    });

    it("shows full cacheKey when shorter than 12 chars", () => {
      render(
        <ResumeJobBanner
          pendingResume={makeJob({ cacheKey: "short" })}
          validationErrors={[]}
          {...defaults()}
        />,
      );
      expect(screen.getByTestId("cache-key").textContent).toBe("short");
    });

    it("shows make and budget from criteria", () => {
      render(
        <ResumeJobBanner
          pendingResume={makeJob({ criteria: { make: "Subaru", budget_usd: 18500 } })}
          validationErrors={[]}
          {...defaults()}
        />,
      );
      expect(screen.getByText("Subaru")).toBeInTheDocument();
      expect(screen.getByText("$18,500")).toBeInTheDocument();
    });

    it("shows year range when year_from and year_to present", () => {
      render(
        <ResumeJobBanner
          pendingResume={makeJob({
            criteria: { make: "Ford", budget_usd: 10000, year_from: 2019, year_to: 2023 },
          })}
          validationErrors={[]}
          {...defaults()}
        />,
      );
      expect(screen.getByText("2019")).toBeInTheDocument();
      expect(screen.getByText("2023")).toBeInTheDocument();
    });

    it("hides year labels when year_from/year_to are absent", () => {
      render(
        <ResumeJobBanner
          pendingResume={makeJob({ criteria: { make: "Kia", budget_usd: 7000 } })}
          validationErrors={[]}
          {...defaults()}
        />,
      );
      expect(screen.queryByText("Od:")).not.toBeInTheDocument();
      expect(screen.queryByText("Do:")).not.toBeInTheDocument();
    });

    it("shows model when present in criteria", () => {
      render(
        <ResumeJobBanner
          pendingResume={makeJob({ criteria: { make: "Toyota", budget_usd: 15000, model: "Camry" } })}
          validationErrors={[]}
          {...defaults()}
        />,
      );
      expect(screen.getByText("Camry")).toBeInTheDocument();
    });

    it("hides model label when model is absent", () => {
      render(
        <ResumeJobBanner
          pendingResume={makeJob({ criteria: { make: "Toyota", budget_usd: 15000 } })}
          validationErrors={[]}
          {...defaults()}
        />,
      );
      expect(screen.queryByText("Model:")).not.toBeInTheDocument();
    });

    it("shows elapsed time since job started", () => {
      const twoMinAgo = Date.now() - 2 * 60 * 1000;
      render(
        <ResumeJobBanner
          pendingResume={makeJob({ startedAt: twoMinAgo })}
          validationErrors={[]}
          {...defaults()}
        />,
      );
      const el = screen.getByTestId("started-ago");
      expect(el.textContent).toBe("2min temu");
    });

    it("shows seconds when started less than a minute ago", () => {
      const thirtySecAgo = Date.now() - 30 * 1000;
      render(
        <ResumeJobBanner
          pendingResume={makeJob({ startedAt: thirtySecAgo })}
          validationErrors={[]}
          {...defaults()}
        />,
      );
      const el = screen.getByTestId("started-ago");
      expect(el.textContent).toMatch(/^\d+s temu$/);
    });

    it("shows hours for long-running jobs", () => {
      const ninetyMinAgo = Date.now() - 90 * 60 * 1000;
      render(
        <ResumeJobBanner
          pendingResume={makeJob({ startedAt: ninetyMinAgo })}
          validationErrors={[]}
          {...defaults()}
        />,
      );
      const el = screen.getByTestId("started-ago");
      expect(el.textContent).toBe("1h 30min temu");
    });
  });

  // ---- formatElapsed unit tests ----
  describe("formatElapsed", () => {
    it("formats 0ms as 0s", () => expect(formatElapsed(0)).toBe("0s temu"));
    it("formats 45s", () => expect(formatElapsed(45_000)).toBe("45s temu"));
    it("formats 60s as 1min", () => expect(formatElapsed(60_000)).toBe("1min temu"));
    it("formats 5min", () => expect(formatElapsed(5 * 60_000)).toBe("5min temu"));
    it("formats 1h exactly", () => expect(formatElapsed(60 * 60_000)).toBe("1h temu"));
    it("formats 1h 15min", () => expect(formatElapsed(75 * 60_000)).toBe("1h 15min temu"));
    it("formats 2h 0min as 2h", () => expect(formatElapsed(120 * 60_000)).toBe("2h temu"));
    it("handles negative as 0s", () => expect(formatElapsed(-5000)).toBe("0s temu"));
  });
});
