import { describe, it, expect, vi } from "vitest";
import {
  withRetry,
  classifyProviderError,
  AIRetryableError,
  AITimeoutError,
} from "./ai-retry.server";

describe("classifyProviderError", () => {
  it("classifies rate limit errors as retryable", () => {
    const result = classifyProviderError(
      new AIRetryableError("429", 429, null, "Anthropic"),
      "Anthropic",
    );
    expect(result.retryable).toBe(true);
    expect(result.message).toContain("429");
  });

  it("classifies timeout errors as retryable", () => {
    const result = classifyProviderError(
      new AITimeoutError("timeout", "Gemini"),
      "Gemini",
    );
    expect(result.retryable).toBe(true);
    expect(result.message).toContain("timeout");
  });

  it("classifies 503 as retryable", () => {
    const result = classifyProviderError(
      new Error("Gemini HTTP 503: overloaded"),
      "Gemini",
    );
    expect(result.retryable).toBe(true);
  });

  it("classifies 401 as non-retryable", () => {
    const result = classifyProviderError(
      new Error("Anthropic HTTP 401: unauthorized"),
      "Anthropic",
    );
    expect(result.retryable).toBe(false);
    expect(result.message).toContain("autoryzacji");
  });

  it("classifies unknown errors as non-retryable", () => {
    const result = classifyProviderError(
      new Error("Something weird happened"),
      "Anthropic",
    );
    expect(result.retryable).toBe(false);
  });
});

describe("withRetry", () => {
  it("returns on first success without retrying", async () => {
    const fn = vi.fn().mockResolvedValue("ok");

    const result = await withRetry(fn, { provider: "Test", maxRetries: 3 });

    expect(result).toBe("ok");
    expect(fn).toHaveBeenCalledOnce();
  });

  it("retries on retryable error and succeeds", async () => {
    const fn = vi
      .fn()
      .mockRejectedValueOnce(new AIRetryableError("rate limit", 429, null, "Test"))
      .mockResolvedValueOnce("ok");

    const result = await withRetry(fn, {
      provider: "Test",
      maxRetries: 3,
      initialDelayMs: 10, // fast for testing
    });

    expect(result).toBe("ok");
    expect(fn).toHaveBeenCalledTimes(2);
  });

  it("does not retry non-retryable errors", async () => {
    const fn = vi.fn().mockRejectedValue(new Error("HTTP 401: unauthorized"));

    await expect(
      withRetry(fn, { provider: "Test", maxRetries: 3, initialDelayMs: 10 }),
    ).rejects.toThrow(/autoryzacji/);

    expect(fn).toHaveBeenCalledOnce();
  });

  it("throws after max retries exhausted", async () => {
    const fn = vi.fn().mockRejectedValue(
      new AIRetryableError("rate limit", 429, null, "Test"),
    );

    await expect(
      withRetry(fn, { provider: "Test", maxRetries: 2, initialDelayMs: 10 }),
    ).rejects.toThrow(/po 2 ponowieniach/);

    expect(fn).toHaveBeenCalledTimes(3); // initial + 2 retries
  });

  it("retries timeout errors", async () => {
    const fn = vi
      .fn()
      .mockRejectedValueOnce(new AITimeoutError("timeout", "Test"))
      .mockResolvedValueOnce("recovered");

    const result = await withRetry(fn, {
      provider: "Test",
      maxRetries: 2,
      initialDelayMs: 10,
    });

    expect(result).toBe("recovered");
    expect(fn).toHaveBeenCalledTimes(2);
  });

  it("respects Retry-After from AIRetryableError", async () => {
    const start = Date.now();
    const fn = vi
      .fn()
      .mockRejectedValueOnce(new AIRetryableError("rate limit", 429, 50, "Test"))
      .mockResolvedValueOnce("ok");

    await withRetry(fn, {
      provider: "Test",
      maxRetries: 2,
      initialDelayMs: 10,
    });

    const elapsed = Date.now() - start;
    // Should have waited ~50ms (the Retry-After), not ~10ms (initialDelay)
    expect(elapsed).toBeGreaterThanOrEqual(40);
  });
});
