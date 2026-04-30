import { createFileRoute } from "@tanstack/react-router";

// Wartości wstrzykiwane w build-time przez vite.config.ts (define).
// Fallbacki na wypadek lokalnego dev bez gita.
declare const __APP_COMMIT_SHA__: string;
declare const __APP_COMMIT_SHORT__: string;
declare const __APP_BUILD_TIME__: string;
declare const __APP_BRANCH__: string;
declare const __APP_VERSION__: string;

export const Route = createFileRoute("/api/version")({
  server: {
    handlers: {
      GET: async () => {
        return Response.json({
          version: __APP_VERSION__,
          commit: {
            sha: __APP_COMMIT_SHA__,
            short: __APP_COMMIT_SHORT__,
            branch: __APP_BRANCH__,
          },
          buildTime: __APP_BUILD_TIME__,
          runtime: {
            node: typeof process !== "undefined" ? process.version : null,
            platform: typeof process !== "undefined" ? process.platform : null,
          },
          env: {
            anthropicModel: process.env.ANTHROPIC_MODEL || "claude-sonnet-4-6",
            scraperConfigured: !!process.env.SCRAPER_BASE_URL,
          },
        });
      },
    },
  },
});
