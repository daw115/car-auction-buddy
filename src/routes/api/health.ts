import { createFileRoute } from "@tanstack/react-router";
import { supabaseAdmin } from "@/integrations/supabase/client.server";

type Status = "ok" | "down" | "unconfigured";

async function pingScraper(): Promise<Status> {
  const baseUrl = process.env.SCRAPER_BASE_URL?.replace(/\/+$/, "");
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

async function pingDatabase(): Promise<Status> {
  try {
    const { error } = await supabaseAdmin.from("app_config").select("id").limit(1);
    return error ? "down" : "ok";
  } catch {
    return "down";
  }
}

export const Route = createFileRoute("/api/health")({
  server: {
    handlers: {
      GET: async () => {
        const startedAt = Date.now();
        const [scraper, database] = await Promise.all([pingScraper(), pingDatabase()]);

        const ai: Status = process.env.ANTHROPIC_API_KEY ? "ok" : "unconfigured";
        const allOk = database === "ok" && (scraper === "ok" || scraper === "unconfigured");

        return Response.json(
          {
            ok: allOk,
            checkedAt: new Date().toISOString(),
            durationMs: Date.now() - startedAt,
            services: { database, scraper, ai },
          },
          { status: allOk ? 200 : 503 },
        );
      },
    },
  },
});
