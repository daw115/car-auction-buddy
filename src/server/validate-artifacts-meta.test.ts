import { describe, it, expect } from "vitest";
import { validateArtifactsMeta } from "./validate-artifacts-meta";

describe("validateArtifactsMeta", () => {
  it("returns valid when meta and fields are fully consistent", () => {
    const row = {
      report_html: "<h1>Report</h1>",
      mail_html: "<p>Mail</p>",
      ai_input: { lots: [] },
      ai_prompt: "prompt text",
      analysis: [{ id: 1 }],
      artifacts_meta: {
        report_html: { size: 15, generated_at: "2025-01-01T00:00:00Z" },
        mail_html: { size: 12, generated_at: "2025-01-01T00:00:00Z" },
        ai_input: { size: 14, generated_at: "2025-01-01T00:00:00Z" },
        ai_prompt: { size: 11, generated_at: "2025-01-01T00:00:00Z" },
        analysis: { lots_count: 1, generated_at: "2025-01-01T00:00:00Z" },
      },
    };
    const result = validateArtifactsMeta(row);
    expect(result.valid).toBe(true);
    expect(result.warnings).toHaveLength(0);
    expect(result.corrected_meta).toBeNull();
  });

  it("returns valid when both meta and fields are empty", () => {
    const result = validateArtifactsMeta({
      report_html: null,
      mail_html: null,
      ai_input: null,
      ai_prompt: null,
      analysis: null,
      artifacts_meta: {},
    });
    expect(result.valid).toBe(true);
    expect(result.corrected_meta).toBeNull();
  });

  it("returns valid when artifacts_meta is missing entirely", () => {
    const result = validateArtifactsMeta({
      report_html: null,
      mail_html: null,
    });
    expect(result.valid).toBe(true);
  });

  // --- Missing meta entries (field present, meta missing) ---

  it("auto-adds meta for report_html when field exists but meta is missing", () => {
    const result = validateArtifactsMeta({
      report_html: "<h1>Report</h1>",
      artifacts_meta: {},
    });
    expect(result.valid).toBe(false);
    expect(result.warnings).toHaveLength(1);
    expect(result.warnings[0]).toContain("report_html present but artifacts_meta.report_html missing");
    expect(result.corrected_meta).not.toBeNull();
    const corrected = result.corrected_meta!.report_html as Record<string, unknown>;
    expect(corrected._auto).toBe(true);
    expect(corrected.size).toBe(15);
    expect(corrected.generated_at).toBeDefined();
  });

  it("auto-adds meta for all four fields when all are present but meta is empty", () => {
    const result = validateArtifactsMeta({
      report_html: "r",
      mail_html: "m",
      ai_input: { x: 1 },
      ai_prompt: "p",
      artifacts_meta: {},
    });
    expect(result.valid).toBe(false);
    expect(result.warnings).toHaveLength(4);
    expect(result.corrected_meta).not.toBeNull();
    for (const key of ["report_html", "mail_html", "ai_input", "ai_prompt"]) {
      const entry = result.corrected_meta![key] as Record<string, unknown>;
      expect(entry._auto).toBe(true);
      expect(entry.size).toBeGreaterThan(0);
    }
  });

  it("computes size from JSON.stringify for non-string fields (ai_input)", () => {
    const input = { lots: [1, 2, 3] };
    const result = validateArtifactsMeta({
      ai_input: input,
      artifacts_meta: {},
    });
    const entry = result.corrected_meta!.ai_input as Record<string, unknown>;
    expect(entry.size).toBe(JSON.stringify(input).length);
  });

  // --- Orphaned meta entries (meta present, field empty) ---

  it("marks meta as _missing when field is null", () => {
    const result = validateArtifactsMeta({
      report_html: null,
      artifacts_meta: {
        report_html: { size: 100, generated_at: "2025-01-01T00:00:00Z" },
      },
    });
    expect(result.valid).toBe(false);
    expect(result.warnings[0]).toContain("artifacts_meta.report_html present but report_html is empty");
    const corrected = result.corrected_meta!.report_html as Record<string, unknown>;
    expect(corrected._missing).toBe(true);
  });

  it("marks meta as _missing when field is empty string", () => {
    const result = validateArtifactsMeta({
      mail_html: "",
      artifacts_meta: {
        mail_html: { size: 50, generated_at: "2025-01-01T00:00:00Z" },
      },
    });
    expect(result.valid).toBe(false);
    const corrected = result.corrected_meta!.mail_html as Record<string, unknown>;
    expect(corrected._missing).toBe(true);
  });

  it("marks meta as _missing when field is undefined", () => {
    const result = validateArtifactsMeta({
      artifacts_meta: {
        ai_prompt: { size: 10, generated_at: "2025-01-01T00:00:00Z" },
      },
    });
    expect(result.valid).toBe(false);
    expect(result.warnings[0]).toContain("ai_prompt");
    const corrected = result.corrected_meta!.ai_prompt as Record<string, unknown>;
    expect(corrected._missing).toBe(true);
  });

  // --- Analysis lots validation ---

  it("auto-adds analysis meta when analysis array exists but meta.analysis is missing", () => {
    const result = validateArtifactsMeta({
      analysis: [{ lot_id: "A" }, { lot_id: "B" }, { lot_id: "C" }],
      artifacts_meta: {},
    });
    expect(result.valid).toBe(false);
    expect(result.warnings).toHaveLength(1);
    expect(result.warnings[0]).toContain("3 lots");
    const corrected = result.corrected_meta!.analysis as Record<string, unknown>;
    expect(corrected.lots_count).toBe(3);
    expect(corrected._auto).toBe(true);
  });

  it("does not flag analysis when array is empty", () => {
    const result = validateArtifactsMeta({
      analysis: [],
      artifacts_meta: {},
    });
    expect(result.valid).toBe(true);
  });

  it("does not flag analysis when meta.analysis already exists", () => {
    const result = validateArtifactsMeta({
      analysis: [{ lot_id: "A" }],
      artifacts_meta: {
        analysis: { lots_count: 1, generated_at: "2025-01-01T00:00:00Z" },
      },
    });
    expect(result.valid).toBe(true);
  });

  // --- Mixed scenarios ---

  it("handles mix of missing meta and orphaned meta in one row", () => {
    const result = validateArtifactsMeta({
      report_html: "<h1>New</h1>",
      mail_html: null,
      ai_input: null,
      ai_prompt: "new prompt",
      artifacts_meta: {
        mail_html: { size: 50, generated_at: "2025-01-01T00:00:00Z" },
      },
    });
    expect(result.valid).toBe(false);
    // report_html missing from meta, ai_prompt missing from meta, mail_html orphaned
    expect(result.warnings).toHaveLength(3);
    const corrected = result.corrected_meta!;
    expect((corrected.report_html as Record<string, unknown>)._auto).toBe(true);
    expect((corrected.ai_prompt as Record<string, unknown>)._auto).toBe(true);
    expect((corrected.mail_html as Record<string, unknown>)._missing).toBe(true);
  });

  it("preserves existing valid meta entries in corrected output", () => {
    const result = validateArtifactsMeta({
      report_html: "<h1>R</h1>",
      mail_html: "<p>M</p>",
      artifacts_meta: {
        report_html: { size: 10, generated_at: "2025-01-01T00:00:00Z" },
        // mail_html missing — should be auto-added
      },
    });
    expect(result.corrected_meta).not.toBeNull();
    // Original report_html meta preserved
    expect((result.corrected_meta!.report_html as Record<string, unknown>).size).toBe(10);
    // mail_html auto-added
    expect((result.corrected_meta!.mail_html as Record<string, unknown>)._auto).toBe(true);
  });
});
