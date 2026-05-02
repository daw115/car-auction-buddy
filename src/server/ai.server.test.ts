import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

// Mock the provider modules before importing ai.server
const mockCallAnthropic = vi.fn();
const mockCallGemini = vi.fn();

vi.mock("./anthropic.server", () => ({
  callAnthropic: (...args: unknown[]) => mockCallAnthropic(...args),
}));

vi.mock("./gemini.server", () => ({
  callGemini: (...args: unknown[]) => mockCallGemini(...args),
}));

import { callAI, detectProvider } from "./ai.server";
import type { AnthropicResult } from "./anthropic.server";

const OK_ANTHROPIC: AnthropicResult = {
  text: '{"answer":"from anthropic"}',
  model: "claude-sonnet-4-6",
  usage: { input_tokens: 10, output_tokens: 20 },
  stop_reason: "end_turn",
};

const OK_GEMINI: AnthropicResult = {
  text: '{"answer":"from gemini"}',
  model: "gemini-2.5-flash",
  usage: { input_tokens: 5, output_tokens: 15 },
  stop_reason: "STOP",
};

const BASE_OPTS = { system: "test", userPrompt: "hello" };

// Helpers to set env vars and restore after each test
const origEnv = { ...process.env };

beforeEach(() => {
  mockCallAnthropic.mockReset();
  mockCallGemini.mockReset();
});

afterEach(() => {
  process.env = { ...origEnv };
});

// ---------- detectProvider ----------

describe("detectProvider", () => {
  it("returns dbPreference when set", () => {
    expect(detectProvider("gemini")).toBe("gemini");
    expect(detectProvider("anthropic")).toBe("anthropic");
  });

  it("falls back to env AI_PROVIDER", () => {
    process.env.AI_PROVIDER = "gemini";
    expect(detectProvider(null)).toBe("gemini");
  });

  it("auto-detects by available keys", () => {
    delete process.env.AI_PROVIDER;
    process.env.ANTHROPIC_API_KEY = "sk-ant-test";
    delete process.env.GEMINI_API_KEY;
    expect(detectProvider(null)).toBe("anthropic");

    delete process.env.ANTHROPIC_API_KEY;
    process.env.GEMINI_API_KEY = "AIza-test";
    expect(detectProvider(null)).toBe("gemini");
  });
});

// ---------- callAI — primary success ----------

describe("callAI — primary provider succeeds", () => {
  it("uses Anthropic when configured as primary", async () => {
    process.env.ANTHROPIC_API_KEY = "sk-ant-test";
    delete process.env.GEMINI_API_KEY;
    mockCallAnthropic.mockResolvedValue(OK_ANTHROPIC);

    const result = await callAI({ ...BASE_OPTS, dbPreference: "anthropic" });

    expect(result.provider).toBe("anthropic");
    expect(result.usedFallback).toBe(false);
    expect(result.text).toContain("anthropic");
    expect(mockCallAnthropic).toHaveBeenCalledOnce();
    expect(mockCallGemini).not.toHaveBeenCalled();
  });

  it("uses Gemini when configured as primary", async () => {
    process.env.GEMINI_API_KEY = "AIza-test";
    delete process.env.ANTHROPIC_API_KEY;
    mockCallGemini.mockResolvedValue(OK_GEMINI);

    const result = await callAI({ ...BASE_OPTS, dbPreference: "gemini" });

    expect(result.provider).toBe("gemini");
    expect(result.usedFallback).toBe(false);
    expect(result.text).toContain("gemini");
    expect(mockCallGemini).toHaveBeenCalledOnce();
    expect(mockCallAnthropic).not.toHaveBeenCalled();
  });
});

// ---------- callAI — error_only fallback ----------

describe("callAI — error_only fallback", () => {
  beforeEach(() => {
    process.env.ANTHROPIC_API_KEY = "sk-ant-test";
    process.env.GEMINI_API_KEY = "AIza-test";
  });

  it("falls back to Gemini when Anthropic fails", async () => {
    mockCallAnthropic.mockRejectedValue(new Error("Anthropic HTTP 500"));
    mockCallGemini.mockResolvedValue(OK_GEMINI);

    const result = await callAI({
      ...BASE_OPTS,
      dbPreference: "anthropic",
      fallbackMode: "error_only",
    });

    expect(result.provider).toBe("gemini");
    expect(result.usedFallback).toBe(true);
    expect(result.fallbackMode).toBe("error_only");
    expect(mockCallAnthropic).toHaveBeenCalledOnce();
    expect(mockCallGemini).toHaveBeenCalledOnce();
  });

  it("falls back to Anthropic when Gemini fails", async () => {
    mockCallGemini.mockRejectedValue(new Error("Gemini HTTP 429"));
    mockCallAnthropic.mockResolvedValue(OK_ANTHROPIC);

    const result = await callAI({
      ...BASE_OPTS,
      dbPreference: "gemini",
      fallbackMode: "error_only",
    });

    expect(result.provider).toBe("anthropic");
    expect(result.usedFallback).toBe(true);
  });

  it("throws when both providers fail", async () => {
    mockCallAnthropic.mockRejectedValue(new Error("Anthropic down"));
    mockCallGemini.mockRejectedValue(new Error("Gemini down"));

    await expect(
      callAI({ ...BASE_OPTS, dbPreference: "anthropic", fallbackMode: "error_only" }),
    ).rejects.toThrow(/AI niedostępne/);
  });

  it("does not call fallback when primary succeeds", async () => {
    mockCallAnthropic.mockResolvedValue(OK_ANTHROPIC);

    const result = await callAI({
      ...BASE_OPTS,
      dbPreference: "anthropic",
      fallbackMode: "error_only",
    });

    expect(result.usedFallback).toBe(false);
    expect(mockCallGemini).not.toHaveBeenCalled();
  });
});

// ---------- callAI — race_both ----------

describe("callAI — race_both", () => {
  beforeEach(() => {
    process.env.ANTHROPIC_API_KEY = "sk-ant-test";
    process.env.GEMINI_API_KEY = "AIza-test";
  });

  it("returns faster provider when both succeed", async () => {
    // Gemini resolves instantly, Anthropic delayed
    mockCallGemini.mockResolvedValue(OK_GEMINI);
    mockCallAnthropic.mockImplementation(
      () => new Promise((resolve) => setTimeout(() => resolve(OK_ANTHROPIC), 200)),
    );

    const result = await callAI({
      ...BASE_OPTS,
      dbPreference: "anthropic",
      fallbackMode: "race_both",
    });

    expect(result.fallbackMode).toBe("race_both");
    // Gemini should win since it resolves first
    expect(result.provider).toBe("gemini");
    // Both should have been called
    expect(mockCallAnthropic).toHaveBeenCalledOnce();
    expect(mockCallGemini).toHaveBeenCalledOnce();
  });

  it("returns surviving provider when one fails", async () => {
    mockCallAnthropic.mockRejectedValue(new Error("Anthropic timeout"));
    mockCallGemini.mockResolvedValue(OK_GEMINI);

    const result = await callAI({
      ...BASE_OPTS,
      dbPreference: "anthropic",
      fallbackMode: "race_both",
    });

    expect(result.provider).toBe("gemini");
  });

  it("throws when both fail in race mode", async () => {
    mockCallAnthropic.mockRejectedValue(new Error("Anthropic error"));
    mockCallGemini.mockRejectedValue(new Error("Gemini error"));

    await expect(
      callAI({ ...BASE_OPTS, dbPreference: "anthropic", fallbackMode: "race_both" }),
    ).rejects.toThrow(/oba dostawcy/);
  });
});

// ---------- callAI — no fallback available ----------

describe("callAI — single provider (no fallback)", () => {
  it("throws directly when single provider fails", async () => {
    process.env.ANTHROPIC_API_KEY = "sk-ant-test";
    delete process.env.GEMINI_API_KEY;
    mockCallAnthropic.mockRejectedValue(new Error("API down"));

    await expect(
      callAI({ ...BASE_OPTS, dbPreference: "anthropic" }),
    ).rejects.toThrow("API down");

    expect(mockCallGemini).not.toHaveBeenCalled();
  });
});
