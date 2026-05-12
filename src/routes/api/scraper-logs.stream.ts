import { createFileRoute } from "@tanstack/react-router";

// SSE proxy: streams logs from upstream scraper /api/logs/stream
// Keeps SCRAPER_API_TOKEN server-side (never exposed to the browser).
export const Route = createFileRoute("/api/scraper-logs/stream")({
  server: {
    handlers: {
      GET: async ({ request }) => {
        const baseUrl = process.env.SCRAPER_BASE_URL?.replace(/\/+$/, "");
        const token = process.env.SCRAPER_API_TOKEN;

        if (!baseUrl || !token) {
          return new Response("Scraper not configured", { status: 503 });
        }

        const upstreamUrl = `${baseUrl}/api/logs/stream?token=${encodeURIComponent(token)}`;

        try {
          const upstream = await fetch(upstreamUrl, {
            method: "GET",
            headers: {
              Accept: "text/event-stream",
              Authorization: `Bearer ${token}`,
            },
            signal: request.signal,
          });

          if (!upstream.ok || !upstream.body) {
            return new Response(`Upstream error: ${upstream.status}`, {
              status: upstream.status || 502,
            });
          }

          return new Response(upstream.body, {
            status: 200,
            headers: {
              "Content-Type": "text/event-stream; charset=utf-8",
              "Cache-Control": "no-cache, no-transform",
              Connection: "keep-alive",
              "X-Accel-Buffering": "no",
            },
          });
        } catch (e) {
          return new Response(`Proxy error: ${(e as Error).message}`, { status: 502 });
        }
      },
    },
  },
});
