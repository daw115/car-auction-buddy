/**
 * Validates consistency between artifacts_meta JSON and actual DB fields.
 * Pure function — no DB or network access.
 */

export type ValidationResult = {
  valid: boolean;
  warnings: string[];
  corrected_meta: Record<string, unknown> | null;
};

const FIELD_MAP: Record<string, string> = {
  report_html: "report_html",
  mail_html: "mail_html",
  ai_input: "ai_input",
  ai_prompt: "ai_prompt",
};

export function validateArtifactsMeta(row: Record<string, unknown>): ValidationResult {
  const meta = (row.artifacts_meta ?? {}) as Record<string, unknown>;
  const warnings: string[] = [];

  let needsCorrection = false;
  const corrected = { ...meta };

  for (const [metaKey, dbField] of Object.entries(FIELD_MAP)) {
    const fieldValue = row[dbField];
    const hasField = fieldValue !== null && fieldValue !== undefined && fieldValue !== "";
    const hasMeta = meta[metaKey] !== null && meta[metaKey] !== undefined;

    if (hasMeta && !hasField) {
      warnings.push(`artifacts_meta.${metaKey} present but ${dbField} is empty`);
      corrected[metaKey] = { ...(corrected[metaKey] as Record<string, unknown> ?? {}), _missing: true };
      needsCorrection = true;
    } else if (hasField && !hasMeta) {
      const size = typeof fieldValue === "string" ? fieldValue.length : JSON.stringify(fieldValue).length;
      warnings.push(`${dbField} present but artifacts_meta.${metaKey} missing — auto-added`);
      corrected[metaKey] = { size, generated_at: new Date().toISOString(), _auto: true };
      needsCorrection = true;
    }
  }

  // Check analysis lots count
  if (Array.isArray(row.analysis) && (row.analysis as unknown[]).length > 0 && !meta.analysis) {
    const count = (row.analysis as unknown[]).length;
    warnings.push(`analysis has ${count} lots but artifacts_meta.analysis missing — auto-added`);
    corrected.analysis = { lots_count: count, generated_at: new Date().toISOString(), _auto: true };
    needsCorrection = true;
  }

  return {
    valid: warnings.length === 0,
    warnings,
    corrected_meta: needsCorrection ? corrected : null,
  };
}
