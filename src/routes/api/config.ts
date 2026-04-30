import { createFileRoute } from "@tanstack/react-router";
import { supabaseAdmin } from "@/integrations/supabase/client.server";

export const Route = createFileRoute("/api/config")({
  server: {
    handlers: {
      GET: async () => {
        const { data, error } = await supabaseAdmin
          .from("app_config")
          .select("*")
          .eq("id", 1)
          .single();
        if (error) {
          return Response.json({ error: error.message }, { status: 500 });
        }
        return Response.json({
          config: data,
          env: {
            ANTHROPIC_API_KEY: !!process.env.ANTHROPIC_API_KEY,
            ANTHROPIC_MODEL: process.env.ANTHROPIC_MODEL || "claude-sonnet-4-5",
            ANTHROPIC_BASE_URL: process.env.ANTHROPIC_BASE_URL || "https://api.anthropic.com",
            SCRAPER_BASE_URL: !!process.env.SCRAPER_BASE_URL,
            SCRAPER_API_TOKEN: !!process.env.SCRAPER_API_TOKEN,
          },
        });
      },
    },
  },
});
