// SSE dla panelu /dev/logs. Route brakowało — UI od początku wołał ten adres
// (EventSource w dev.logs.tsx), a serwer odpowiadał 404, więc panel świecił pustką
// i wyglądało to jak "brak logów", a nie jak brak endpointu.
//
// Stream łączy DWA źródła, bo w panelu chodzi o jedno okno na całość:
//   1. bufor dashboardu (log-stream.server.ts) — żądania HTTP, błędy renderowania;
//   2. log backendu FastAPI — i to jest to, czego brakowało najbardziej: przebieg
//      wyszukiwania ([Scraper], [AI], [claude-code]) dzieje się w Pythonie, nie tutaj,
//      więc bufor dashboardu nie mógł go pokazać choćby działał idealnie.
//
// Token backendu zostaje na serwerze. Przeglądarka rozmawia tylko z tym route'em —
// inaczej klucz do API musiałby trafić do JS-a w kliencie.
import { createFileRoute } from "@tanstack/react-router";

import { checkDevAuth } from "@/server/dev-auth.server";
import { getRecentLogs, subscribe, type LogStreamEntry } from "@/server/log-stream.server";

const KEEP_ALIVE_MS = 15_000;

/** Poziom z treści linii backendu. Python nie wysyła pola level, więc czytamy tekst. */
function levelOf(line: string): LogStreamEntry["level"] {
  if (/\bERROR\b|Traceback|CRITICAL/.test(line)) return "error";
  if (/\bWARN(ING)?\b|⚠/.test(line)) return "warn";
  if (/^INFO: {5}\d|HTTP\/1\.1" \d{3}/.test(line)) return "http";
  return "info";
}

/** "2026-08-11 09:40:13,684 INFO report.llm_cache | treść" → scope + message. */
function parseBackendLine(line: string, id: number): LogStreamEntry {
  const match = line.match(
    /^(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2})[.,]\d+\s+(\w+)\s+([\w.]+)\s*\|\s*(.*)$/,
  );
  if (match) {
    return {
      id,
      ts: match[1].replace(" ", "T"),
      level: levelOf(match[2]),
      scope: match[3],
      message: match[4],
    };
  }
  return { id, ts: new Date().toISOString(), level: levelOf(line), scope: "api", message: line };
}

function backendBase(): string | null {
  const base = (process.env.UBUNTU_API_BASE_URL ?? process.env.API_BASE_URL ?? "").trim();
  return base ? base.replace(/\/$/, "") : null;
}

function backendHeaders(): HeadersInit {
  const headers: Record<string, string> = { Accept: "text/event-stream" };
  const token = (
    process.env.UBUNTU_API_BEARER_TOKEN ??
    process.env.SCRAPER_API_TOKEN ??
    process.env.API_BEARER_TOKEN ??
    ""
  ).trim();
  if (token) headers.Authorization = `Bearer ${token}`;
  const cfId = process.env.CF_ACCESS_CLIENT_ID?.trim();
  const cfSecret = process.env.CF_ACCESS_CLIENT_SECRET?.trim();
  if (cfId && cfSecret) {
    headers["CF-Access-Client-Id"] = cfId;
    headers["CF-Access-Client-Secret"] = cfSecret;
  }
  return headers;
}

export const Route = createFileRoute("/api/dev/logs/stream")({
  server: {
    handlers: {
      GET: async ({ request }) => {
        const auth = checkDevAuth(request);
        if (!auth.ok) {
          return Response.json({ ok: false, reason: auth.reason }, { status: auth.status ?? 401 });
        }

        const since = Number(new URL(request.url).searchParams.get("since") ?? 0);
        const encoder = new TextEncoder();
        let nextId = -1; // ujemne id dla wpisów backendu, żeby nie zderzały się z buforem

        const stream = new ReadableStream({
          start(controller) {
            let closed = false;
            const send = (entry: LogStreamEntry) => {
              if (closed) return;
              try {
                controller.enqueue(encoder.encode(`data: ${JSON.stringify(entry)}\n\n`));
              } catch {
                closed = true;
              }
            };

            for (const entry of getRecentLogs(Number.isFinite(since) ? since : 0)) {
              send(entry);
            }
            const unsubscribe = subscribe(send);

            // Backend: doklejamy jego log do tego samego strumienia.
            const backendAbort = new AbortController();
            const base = backendBase();
            if (base) {
              void (async () => {
                try {
                  const upstream = await fetch(`${base}/api/logs/stream`, {
                    headers: backendHeaders(),
                    signal: backendAbort.signal,
                  });
                  if (!upstream.ok || !upstream.body) {
                    send({
                      id: nextId--,
                      ts: new Date().toISOString(),
                      level: "warn",
                      scope: "dev-logs",
                      message: `Log backendu niedostępny (HTTP ${upstream.status}) — widać tylko logi dashboardu.`,
                    });
                    return;
                  }
                  const reader = upstream.body.getReader();
                  const decoder = new TextDecoder();
                  let buffer = "";
                  for (;;) {
                    const { done, value } = await reader.read();
                    if (done) break;
                    buffer += decoder.decode(value, { stream: true });
                    const chunks = buffer.split("\n\n");
                    buffer = chunks.pop() ?? "";
                    for (const chunk of chunks) {
                      // Backend wysyła "event: line\ndata: <tekst>" — bierzemy sam tekst.
                      const text = chunk
                        .split("\n")
                        .filter((l) => l.startsWith("data:"))
                        .map((l) => l.slice(5).trimStart())
                        .join("\n");
                      if (text) send(parseBackendLine(text, nextId--));
                    }
                  }
                } catch (error) {
                  if (backendAbort.signal.aborted) return;
                  send({
                    id: nextId--,
                    ts: new Date().toISOString(),
                    level: "error",
                    scope: "dev-logs",
                    message: `Stream backendu przerwany: ${(error as Error).message}`,
                  });
                }
              })();
            } else {
              send({
                id: nextId--,
                ts: new Date().toISOString(),
                level: "warn",
                scope: "dev-logs",
                message:
                  "Brak UBUNTU_API_BASE_URL/API_BASE_URL — logi backendu (przebieg wyszukiwania) nie będą widoczne.",
              });
            }

            // Cloudflare zrywa bezruch na tunelu, więc komentarz co 15 s trzyma połączenie.
            const keepAlive = setInterval(() => {
              if (closed) return;
              try {
                controller.enqueue(encoder.encode(": keep-alive\n\n"));
              } catch {
                closed = true;
              }
            }, KEEP_ALIVE_MS);

            request.signal.addEventListener("abort", () => {
              closed = true;
              clearInterval(keepAlive);
              unsubscribe();
              backendAbort.abort();
              try {
                controller.close();
              } catch {
                /* już zamknięty */
              }
            });
          },
        });

        return new Response(stream, {
          headers: {
            "Content-Type": "text/event-stream; charset=utf-8",
            "Cache-Control": "no-store",
            Connection: "keep-alive",
            "X-Accel-Buffering": "no",
          },
        });
      },
    },
  },
});
