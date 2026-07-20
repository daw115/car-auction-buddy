// Cron hook: /api/public/hooks/cases-refresh
// Odpalany przez pg_cron co ~15 min. Wyszukuje sprawy z włączonym
// auto_refresh_enabled i next_auto_run_at <= now(), uruchamia dla każdej
// backendSearch (przez transport backendu), zapisuje case_search z diffem
// nowych lot_id oraz przesuwa next_auto_run_at.
//
// Bezpieczeństwo: weryfikuje apikey (Supabase anon key) — /api/public/* pomija
// auth Lovable, ale odrzucamy ruch bez klucza żeby uniknąć brute-force.

import { createFileRoute } from "@tanstack/react-router";
import { supabaseAdmin } from "@/integrations/supabase/client.server";
import { backendRequest } from "@/lib/backend-transport.server";

type CaseRow = {
  id: string;
  default_criteria: Record<string, unknown> | null;
  auto_refresh_interval_hours: number;
};

type PrevSearchRow = { new_lot_ids: string[] | null };

type BackendSearchLite = {
  job_id: string;
  listings?: Array<{ lot_id?: string | null }>;
};

const MAX_PER_RUN = 10;

export const Route = createFileRoute("/api/public/hooks/cases-refresh")({
  server: {
    handlers: {
      POST: async ({ request }) => {
        const apikey =
          request.headers.get("apikey") ??
          request.headers.get("authorization")?.replace(/^Bearer\s+/i, "") ??
          "";
        const expected = process.env.SUPABASE_PUBLISHABLE_KEY ?? "";
        if (!expected || apikey !== expected) {
          return new Response("Forbidden", { status: 403 });
        }

        const nowIso = new Date().toISOString();
        const { data: cases, error } = await supabaseAdmin
          .from("client_cases")
          .select("id, default_criteria, auto_refresh_interval_hours")
          .eq("auto_refresh_enabled", true)
          .lte("next_auto_run_at", nowIso)
          .limit(MAX_PER_RUN);
        if (error) {
          return Response.json({ error: error.message }, { status: 500 });
        }

        const results: Array<{
          case_id: string;
          ok: boolean;
          new_lots?: number;
          total_lots?: number;
          error?: string;
        }> = [];

        for (const row of (cases ?? []) as CaseRow[]) {
          try {
            const criteria = (row.default_criteria ?? {}) as Record<string, unknown>;
            if (!criteria.make) {
              results.push({ case_id: row.id, ok: false, error: "no_default_criteria" });
              // przesuń next_auto_run żeby nie zapętlić
              await supabaseAdmin
                .from("client_cases")
                .update({
                  next_auto_run_at: new Date(
                    Date.now() + row.auto_refresh_interval_hours * 3600_000,
                  ).toISOString(),
                } as never)
                .eq("id", row.id);
              continue;
            }

            const { data: prev } = await supabaseAdmin
              .from("case_searches")
              .select("new_lot_ids")
              .eq("case_id", row.id)
              .order("created_at", { ascending: false })
              .limit(50);
            const seen = new Set<string>();
            for (const p of (prev ?? []) as PrevSearchRow[]) {
              for (const id of p.new_lot_ids ?? []) seen.add(id);
            }

            const resp = await backendRequest<BackendSearchLite>({
              path: "/api/search",
              method: "POST",
              body: { criteria },
              timeoutMs: 5 * 60 * 1000,
            });
            const currentIds = (resp.listings ?? [])
              .map((l) => l.lot_id)
              .filter((v): v is string => !!v);
            const newIds = currentIds.filter((id) => !seen.has(id));

            await supabaseAdmin
              .from("case_searches")
              .upsert(
                {
                  case_id: row.id,
                  record_id: resp.job_id,
                  searched_by: "auto",
                  new_lot_ids: newIds,
                  triggered_by: "auto",
                },
                { onConflict: "case_id,record_id" },
              );

            await supabaseAdmin
              .from("client_cases")
              .update({
                last_auto_run_at: new Date().toISOString(),
                next_auto_run_at: new Date(
                  Date.now() + row.auto_refresh_interval_hours * 3600_000,
                ).toISOString(),
              } as never)
              .eq("id", row.id);

            results.push({
              case_id: row.id,
              ok: true,
              total_lots: currentIds.length,
              new_lots: newIds.length,
            });
          } catch (e) {
            results.push({ case_id: row.id, ok: false, error: (e as Error).message });
          }
        }

        return Response.json({
          processed: results.length,
          results,
          checked_at: nowIso,
        });
      },
    },
  },
});
