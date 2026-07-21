import { createFileRoute } from "@tanstack/react-router";
import { siteSessionGuard } from "@/server/site-session.server";
import { backendStreamRequest } from "@/server/backend-transport.server";

// SSE proxy: streams logs from the active backend transport (Ubuntu API or
// legacy) via src/server/backend-transport.server.ts. Never reads
// UBUNTU_*/CF_ACCESS_*/API_BASE_URL/API_BEARER_TOKEN directly — the unified
// transport owns credential handling so this route stays server-secret-free.
const CANDIDATE_PATHS = ["/api/logs/stream", "/logs/stream", "/api/stream/logs"];

export const Route = createFileRoute("/api/scraper-logs/stream")({
  server: {
    handlers: {
      GET: async ({ request }) => {
        const unauthorized = await siteSessionGuard();
        if (unauthorized) return unauthorized;

        let lastStatus = 0;
        let lastPath = "";
        for (const path of CANDIDATE_PATHS) {
          try {
            const upstream = await backendStreamRequest({ path, signal: request.signal });
            if (upstream.body) {
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
            const err = e as { status?: number; message?: string };
            lastStatus = err.status ?? 0;
            lastPath = path;
            if (
              err.status === 500 &&
              /nieskonfigurowany|not configured|unconfigured/i.test(err.message ?? "")
            ) {
              return new Response("Scraper not configured", { status: 503 });
            }
            // network/upstream error on this candidate — try the next one
          }
        }
        return new Response(`Upstream not found. Last tried: ${lastPath} → ${lastStatus}`, {
          status: lastStatus || 502,
        });
      },
    },
  },
});
