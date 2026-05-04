// Log-related server functions — extracted from src/server/api.functions.ts
// so that src/components/LogsPanel.tsx can import them without triggering
// the import-protection plugin (which blocks **/server/** from components).

import { createServerFn } from "@tanstack/react-start";
import { z } from "zod";
import { supabaseAdmin } from "@/integrations/supabase/client.server";

export const listLogs = createServerFn({ method: "POST" })
  .inputValidator(
    z.object({
      limit: z.number().int().min(1).max(500).optional(),
      offset: z.number().int().min(0).optional(),
      clientId: z.string().uuid().optional(),
      recordId: z.string().uuid().optional(),
      filter: z.string().max(200).optional(),
      levels: z.array(z.string().max(20)).optional(),
      dateFrom: z.string().max(30).optional(),
      dateTo: z.string().max(30).optional(),
    }).parse,
  )
  .handler(async ({ data }) => {
    let q = supabaseAdmin
      .from("operation_logs")
      .select("*", { count: "exact" })
      .order("created_at", { ascending: false })
      .range(data.offset ?? 0, (data.offset ?? 0) + (data.limit ?? 100) - 1);

    if (data.clientId) q = q.eq("client_id", data.clientId);
    if (data.recordId) q = q.eq("record_id", data.recordId);
    if (data.filter) q = q.or(`message.ilike.%${data.filter}%,operation.ilike.%${data.filter}%,step.ilike.%${data.filter}%`);
    if (data.levels && data.levels.length > 0) q = q.in("level", data.levels);
    if (data.dateFrom) q = q.gte("created_at", data.dateFrom);
    if (data.dateTo) q = q.lte("created_at", data.dateTo);

    const { data: rows, error, count } = await q;
    if (error) throw new Error(error.message);
    return { rows: rows ?? [], total: count ?? 0 };
  });

export const clearLogs = createServerFn({ method: "POST" })
  .inputValidator(
    z.object({
      clientId: z.string().uuid().optional(),
    }).parse,
  )
  .handler(async ({ data }) => {
    let q = supabaseAdmin.from("operation_logs").delete();
    if (data.clientId) {
      q = q.eq("client_id", data.clientId);
    } else {
      q = q.neq("id", "00000000-0000-0000-0000-000000000000"); // delete all
    }
    const { error } = await q;
    if (error) throw new Error(error.message);
    return { ok: true };
  });

export const getLogRetention = createServerFn({ method: "GET" }).handler(async () => {
  const { data } = await supabaseAdmin
    .from("app_config")
    .select("value")
    .eq("key", "log_retention_days")
    .maybeSingle();
  return { days: data?.value ? Number(data.value) : 30, source: data ? "db" : "default" };
});

export const cleanupLogs = createServerFn({ method: "POST" }).handler(async () => {
  const { data: cfg } = await supabaseAdmin
    .from("app_config")
    .select("value")
    .eq("key", "log_retention_days")
    .maybeSingle();
  const days = cfg?.value ? Number(cfg.value) : 30;
  const cutoff = new Date(Date.now() - days * 86400000).toISOString();
  const { error, count } = await supabaseAdmin
    .from("operation_logs")
    .delete({ count: "exact" })
    .lt("created_at", cutoff);
  if (error) throw new Error(error.message);
  return { deleted: count ?? 0, retention_days: days };
});
