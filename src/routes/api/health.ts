import { createFileRoute } from "@tanstack/react-router";
import { supabaseAdmin } from "@/integrations/supabase/client.server";
import { probeUbuntuApi } from "@/lib/ubuntu-api.server";

type Status = "ok" | "down" | "unconfigured";

async function pingScraper(): Promise<Status> {
  const baseUrl = process.env.API_BASE_URL?.replace(/\/+$/, "");
  if (!baseUrl) return "unconfigured";
  try {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 4000);
    const res = await fetch(`${baseUrl}/health`, { signal: ctrl.signal });
    clearTimeout(timer);
    return res.ok ? "ok" : "down";
  } catch {
    return "down";
  }
}

// Two tables, not one. After the server rebuild PostgREST kept a schema cache
// built on an empty database and answered PGRST205 for `site_user_passwords`, so
// every login failed while this check still saw `app_config` and reported `ok`.
// A green status next to a dead panel is worse than no status, so we also probe
// the table every user has to go through.
const PROBED_TABLES = ["app_config", "site_user_passwords"] as const;

async function pingDatabase(): Promise<Status> {
  try {
    const results = await Promise.all(
      PROBED_TABLES.map((table) =>
        supabaseAdmin
          .from(table)
          .select("*", { count: "exact", head: true })
          .limit(1)
          // Explicit type: `from()` with a union of table names loses response inference.
          .then((res: { error: unknown }) => !res.error),
      ),
    );
    return results.every(Boolean) ? "ok" : "down";
  } catch {
    return "down";
  }
}

export const Route = createFileRoute("/api/health")({
  server: {
    handlers: {
      GET: async () => {
        const startedAt = Date.now();
        const [scraper, database, ubuntuApi] = await Promise.all([
          pingScraper(),
          pingDatabase(),
          probeUbuntuApi(),
        ]);

        const ai: Status = process.env.ANTHROPIC_API_KEY ? "ok" : "unconfigured";
        // Backwards-compatible readiness: Ubuntu API is optional in this
        // migration phase — its `unconfigured`/`down` state MUST NOT flip the
        // whole /api/health to 503 while no production screen depends on it.
        const allOk = database === "ok" && (scraper === "ok" || scraper === "unconfigured");

        return Response.json(
          {
            ok: allOk,
            checkedAt: new Date().toISOString(),
            durationMs: Date.now() - startedAt,
            services: {
              database,
              scraper,
              ai,
              ubuntuApi: {
                status: ubuntuApi.status,
                latencyMs: ubuntuApi.latencyMs,
                requestId: ubuntuApi.requestId,
              },
            },
          },
          { status: allOk ? 200 : 503 },
        );
      },
    },
  },
});
