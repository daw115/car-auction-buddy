import { createFileRoute } from "@tanstack/react-router";
import { supabaseAdmin } from "@/integrations/supabase/client.server";
import { siteSessionGuard } from "@/server/site-session.server";
import { DEFAULT_GEMINI_MODEL } from "@/server/gemini.server";

export const Route = createFileRoute("/api/config")({
  server: {
    handlers: {
      GET: async () => {
        const unauthorized = await siteSessionGuard();
        if (unauthorized) return unauthorized;

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
            ANTHROPIC_MODEL: process.env.ANTHROPIC_MODEL || "claude-sonnet-4-6",
            ANTHROPIC_BASE_URL: process.env.ANTHROPIC_BASE_URL || "https://api.anthropic.com",
            GEMINI_API_KEY: !!process.env.GEMINI_API_KEY,
            GEMINI_MODEL: process.env.GEMINI_MODEL || DEFAULT_GEMINI_MODEL,
            GEMINI_ENTERPRISE: !!(
              process.env.GEMINI_ENTERPRISE_SA_JSON && process.env.GEMINI_ENTERPRISE_PROJECT_ID
            ),
            GEMINI_ENTERPRISE_PROJECT_ID: process.env.GEMINI_ENTERPRISE_PROJECT_ID || null,
            GEMINI_ENTERPRISE_LOCATION: process.env.GEMINI_ENTERPRISE_LOCATION || "us-central1",
            GEMINI_ENTERPRISE_MODEL: process.env.GEMINI_ENTERPRISE_MODEL || "gemini-2.5-pro",
            AI_PROVIDER:
              process.env.AI_PROVIDER ||
              (process.env.ANTHROPIC_API_KEY
                ? "anthropic"
                : process.env.GEMINI_API_KEY
                  ? "gemini"
                  : process.env.GEMINI_ENTERPRISE_SA_JSON
                    ? "gemini_enterprise"
                    : "anthropic"),
            SCRAPER_BASE_URL: !!process.env.SCRAPER_BASE_URL,
            SCRAPER_API_TOKEN: !!process.env.SCRAPER_API_TOKEN,
          },
        });
      },
    },
  },
});
