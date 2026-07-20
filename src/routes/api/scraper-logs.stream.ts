import { createFileRoute } from "@tanstack/react-router";
import { siteSessionGuard } from "@/server/site-session.server";

// SSE proxy: streams logs from upstream scraper. Tries several known paths
// and falls back through them. Keeps SCRAPER_API_TOKEN server-side.
const CANDIDATE_PATHS = ["/api/logs/stream", "/logs/stream", "/api/stream/logs"];

export const Route = createFileRoute("/api/scraper-logs/stream")({
  server: {
    handlers: {
      GET: async ({ request }) => {
        const unauthorized = await siteSessionGuard();
        if (unauthorized) return unauthorized;

        const baseUrl = process.env.SCRAPER_BASE_URL?.replace(/\/+$/, "");
        const token = process.env.SCRAPER_API_TOKEN;

        if (!baseUrl || !token) {
          return new Response("Scraper not configured", { status: 503 });
        }

        let lastStatus = 0;
        let lastPath = "";
        for (const path of CANDIDATE_PATHS) {
          const upstreamUrl = `${baseUrl}${path}`;
          try {
            const upstream = await fetch(upstreamUrl, {
              method: "GET",
              headers: {
                Accept: "text/event-stream",
                Authorization: `Bearer ${token}`,
              },
              signal: request.signal,
            });

            if (upstream.ok && upstream.body) {
              return new Response(upstream.body, {
                status: 200,
                headers: {
                  "Content-Type": "text/event-stream; charset=utf-8",
                  "Cache-Control": "no-cache, no-transform",
                  Connection: "keep-alive",
                  "X-Accel-Buffering": "no",
                  "X-Upstream-Path": path,
                },
              });
            }
            lastStatus = upstream.status;
            lastPath = path;
            // try next candidate
          } catch (e) {
            return new Response(`Proxy error: ${(e as Error).message}`, { status: 502 });
          }
        }
        return new Response(`Upstream not found. Last tried: ${lastPath} → ${lastStatus}`, {
          status: lastStatus || 502,
        });
      },
    },
  },
});
