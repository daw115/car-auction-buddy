// SSE ze strumieniem logów serwera dla panelu /dev/logs.
//
// Ta trasa nigdy nie powstała, mimo że wszystko po obu jej stronach istniało:
// `src/server/log-stream.server.ts` wypełniał bufor, a `dev.logs.tsx` łączył się
// z `/api/dev/logs/stream` i dostawał 404. Pozycja w menu prowadziła do pustej
// tabeli z napisem o endpoincie, którego nie było.
//
// Brama jest ta sama co przy logowaniu do panelu (`checkDevAuth`) — logi potrafią
// zawierać ścieżki, nazwy tabel i fragmenty zapytań, więc nie mogą wisieć otwarte.

import { createFileRoute } from "@tanstack/react-router";
import { checkDevAuth } from "@/server/dev-auth.server";
import { getRecentLogs, subscribe } from "@/server/log-stream.server";

/** Co ile wysyłamy komentarz podtrzymujący. Proxy i przeglądarki zrywają
 *  bezczynne połączenia SSE po ok. minucie, a cisza w logach jest normalna. */
const KEEPALIVE_MS = 25_000;

export const Route = createFileRoute("/api/dev/logs/stream")({
  server: {
    handlers: {
      GET: async ({ request }) => {
        if (!checkDevAuth(request).ok) {
          return new Response("Nieautoryzowane", { status: 401 });
        }

        // Klient podaje ostatnie widziane id, żeby po zerwaniu połączenia nie
        // dostać drugi raz tego samego — EventSource wznawia sam.
        const url = new URL(request.url);
        const sinceId = Number(url.searchParams.get("sinceId") ?? 0) || 0;

        const encoder = new TextEncoder();
        let odsubskrybuj: (() => void) | undefined;
        let keepalive: ReturnType<typeof setInterval> | undefined;

        const stream = new ReadableStream({
          start(controller) {
            const wyslij = (data: unknown) => {
              try {
                controller.enqueue(encoder.encode(`data: ${JSON.stringify(data)}\n\n`));
              } catch {
                // Klient zamknął kartę w trakcie zapisu — sprzątamy i milkniemy.
                zamknij();
              }
            };

            const zamknij = () => {
              odsubskrybuj?.();
              odsubskrybuj = undefined;
              if (keepalive) clearInterval(keepalive);
              keepalive = undefined;
            };

            for (const entry of getRecentLogs(sinceId)) wyslij(entry);
            odsubskrybuj = subscribe(wyslij);

            keepalive = setInterval(() => {
              try {
                controller.enqueue(encoder.encode(": keepalive\n\n"));
              } catch {
                zamknij();
              }
            }, KEEPALIVE_MS);

            request.signal?.addEventListener("abort", () => {
              zamknij();
              try {
                controller.close();
              } catch {
                // już zamknięty
              }
            });
          },
          cancel() {
            odsubskrybuj?.();
            if (keepalive) clearInterval(keepalive);
          },
        });

        return new Response(stream, {
          headers: {
            "Content-Type": "text/event-stream; charset=utf-8",
            "Cache-Control": "no-cache, no-transform",
            Connection: "keep-alive",
            // Bez tego nginx buforuje SSE i logi przychodzą paczkami po minucie.
            "X-Accel-Buffering": "no",
          },
        });
      },
    },
  },
});
