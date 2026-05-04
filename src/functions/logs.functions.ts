// Log-related server functions — placed outside src/server/ so that
// src/components/LogsPanel.tsx can import them without triggering import-protection.

import { createServerFn } from "@tanstack/react-start";
import { z } from "zod";
import { supabaseAdmin } from "@/integrations/supabase/client.server";

export const listLogs = createServerFn({ method: "GET" })
  .inputValidator(
    z.object({
      clientId: z.string().uuid().nullable().optional(),
      recordId: z.string().uuid().nullable().optional(),
      operation: z.string().max(40).optional(),
      levels: z.array(z.enum(["info", "warn", "error", "debug"])).max(4).optional(),
      from: z.string().datetime().optional(),
      to: z.string().datetime().optional(),
      limit: z.number().int().min(1).max(500).optional(),
    }).parse,
  )
  .handler(async ({ data }) => {
    let q = supabaseAdmin
      .from("operation_logs")
      .select("id, created_at, client_id, record_id, operation, step, level, message, details, duration_ms")
      .order("created_at", { ascending: false })
      .limit(data.limit ?? 100);
    if (data.clientId) q = q.eq("client_id", data.clientId);
    if (data.recordId) q = q.eq("record_id", data.recordId);
    if (data.operation) q = q.eq("operation", data.operation);
    if (data.levels && data.levels.length > 0) q = q.in("level", data.levels);
    if (data.from) q = q.gte("created_at", data.from);
    if (data.to) q = q.lte("created_at", data.to);
    const { data: rows, error } = await q;
    if (error) throw new Error(error.message);
    return rows ?? [];
  });

export const clearLogs = createServerFn({ method: "POST" })
  .inputValidator(
    z.object({
      clientId: z.string().uuid().nullable().optional(),
    }).parse,
  )
  .handler(async ({ data }) => {
    let q = supabaseAdmin.from("operation_logs").delete();
    if (data.clientId) {
      q = q.eq("client_id", data.clientId);
    } else {
      q = q.not("id", "is", null);
    }
    const { error } = await q;
    if (error) throw new Error(error.message);
    return { ok: true };
  });

const DEFAULT_LOG_RETENTION_DAYS = 30;

function getLogRetentionDays(): number {
  const raw = process.env.LOG_RETENTION_DAYS;
  const parsed = raw ? parseInt(raw, 10) : NaN;
  if (!Number.isFinite(parsed) || parsed <= 0) return DEFAULT_LOG_RETENTION_DAYS;
  return Math.min(parsed, 3650);
}

export const getLogRetention = createServerFn({ method: "GET" }).handler(async () => {
  return {
    days: getLogRetentionDays(),
    default: DEFAULT_LOG_RETENTION_DAYS,
    source: process.env.LOG_RETENTION_DAYS ? "env" : "default",
  };
});

export const cleanupLogs = createServerFn({ method: "POST" }).handler(async () => {
  const days = getLogRetentionDays();
  const cutoff = new Date(Date.now() - days * 24 * 60 * 60 * 1000).toISOString();
  const { error, count } = await supabaseAdmin
    .from("operation_logs")
    .delete({ count: "exact" })
    .lt("created_at", cutoff);
  if (error) throw new Error(error.message);
  return { ok: true, retention_days: days, cutoff, deleted: count ?? 0 };
});
