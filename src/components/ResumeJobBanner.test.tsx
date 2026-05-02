// @vitest-environment jsdom
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
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

describe("ResumeJobBanner", () => {
  // ---- visibility ----
  it("renders nothing when no pending resume and no errors", () => {
    const { container } = render(
      <ResumeJobBanner
        pendingResume={null}
        validationErrors={[]}
        onResume={vi.fn()}
        onDismiss={vi.fn()}
        onClearErrors={vi.fn()}
      />,
    );
    expect(container.innerHTML).toBe("");
  });

  it('shows "Wznów" and "Odrzuć" buttons when pendingResume is set', () => {
    render(
      <ResumeJobBanner
        pendingResume={makeJob()}
        validationErrors={[]}
        onResume={vi.fn()}
        onDismiss={vi.fn()}
        onClearErrors={vi.fn()}
      />,
    );

    expect(screen.getByText("Wznów")).toBeInTheDocument();
    expect(screen.getByText("Odrzuć")).toBeInTheDocument();
  });

  it("displays job ID prefix in the banner", () => {
    render(
      <ResumeJobBanner
        pendingResume={makeJob({ jobId: "xyz98765-aaa" })}
        validationErrors={[]}
        onResume={vi.fn()}
        onDismiss={vi.fn()}
        onClearErrors={vi.fn()}
      />,
    );

    expect(screen.getByText("#xyz98765")).toBeInTheDocument();
  });

  it("displays criteria summary (make, budget)", () => {
    render(
      <ResumeJobBanner
        pendingResume={makeJob({ criteria: { make: "BMW", budget_usd: 25000, model: "X5", year_from: 2020, year_to: 2024 } })}
        validationErrors={[]}
        onResume={vi.fn()}
        onDismiss={vi.fn()}
        onClearErrors={vi.fn()}
      />,
    );

    expect(screen.getByText("BMW")).toBeInTheDocument();
    expect(screen.getByText("X5")).toBeInTheDocument();
    expect(screen.getByText("2020")).toBeInTheDocument();
    expect(screen.getByText("2024")).toBeInTheDocument();
  });

  // ---- interactions ----
  it('calls onResume when "Wznów" is clicked', async () => {
    const onResume = vi.fn();
    render(
      <ResumeJobBanner
        pendingResume={makeJob()}
        validationErrors={[]}
        onResume={onResume}
        onDismiss={vi.fn()}
        onClearErrors={vi.fn()}
      />,
    );

    await userEvent.click(screen.getByText("Wznów"));
    expect(onResume).toHaveBeenCalledTimes(1);
  });

  it('calls onDismiss when "Odrzuć" is clicked', async () => {
    const onDismiss = vi.fn();
    render(
      <ResumeJobBanner
        pendingResume={makeJob()}
        validationErrors={[]}
        onResume={vi.fn()}
        onDismiss={onDismiss}
        onClearErrors={vi.fn()}
      />,
    );

    await userEvent.click(screen.getByText("Odrzuć"));
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });

  // ---- validation errors ----
  it("shows validation errors when present and no pendingResume", () => {
    render(
      <ResumeJobBanner
        pendingResume={null}
        validationErrors={["make: Marka jest wymagana", "budget_usd: Expected number"]}
        onResume={vi.fn()}
        onDismiss={vi.fn()}
        onClearErrors={vi.fn()}
      />,
    );

    expect(screen.getByText("Zapisane kryteria scrapera były nieprawidłowe — dane wyczyszczone.")).toBeInTheDocument();
    expect(screen.getByText("make: Marka jest wymagana")).toBeInTheDocument();
    expect(screen.getByText("budget_usd: Expected number")).toBeInTheDocument();
    // "Wznów" should NOT be visible
    expect(screen.queryByText("Wznów")).not.toBeInTheDocument();
  });

  it('calls onClearErrors when "Zamknij" is clicked on error banner', async () => {
    const onClearErrors = vi.fn();
    render(
      <ResumeJobBanner
        pendingResume={null}
        validationErrors={["some error"]}
        onResume={vi.fn()}
        onDismiss={vi.fn()}
        onClearErrors={onClearErrors}
      />,
    );

    await userEvent.click(screen.getByText("Zamknij"));
    expect(onClearErrors).toHaveBeenCalledTimes(1);
  });

  it("shows resume banner (not errors) when both pendingResume and errors exist", () => {
    render(
      <ResumeJobBanner
        pendingResume={makeJob()}
        validationErrors={["should be ignored"]}
        onResume={vi.fn()}
        onDismiss={vi.fn()}
        onClearErrors={vi.fn()}
      />,
    );

    // Resume banner shown
    expect(screen.getByText("Wznów")).toBeInTheDocument();
    // Error banner not shown
    expect(screen.queryByText("Zapisane kryteria scrapera były nieprawidłowe")).not.toBeInTheDocument();
  });
});
