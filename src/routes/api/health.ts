import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/api/health")({
  server: {
    handlers: {
      GET: async () => {
        const baseUrl = process.env.SCRAPER_BASE_URL?.replace(/\/+$/, "");
        let scraper: "unconfigured" | "reachable" | "down" = "unconfigured";
        if (baseUrl) {
          try {
            const ctrl = new AbortController();
            const timer = setTimeout(() => ctrl.abort(), 4000);
            const res = await fetch(`${baseUrl}/health`, { signal: ctrl.signal });
            clearTimeout(timer);
            scraper = res.ok ? "reachable" : "down";
          } catch {
            scraper = "down";
          }
        }
        return Response.json({
          ok: true,
          scraper,
          ai: process.env.ANTHROPIC_API_KEY ? "configured" : "missing-key",
        });
      },
    },
  },
});
