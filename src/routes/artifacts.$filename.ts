import { createFileRoute } from "@tanstack/react-router";
import { siteSessionGuard } from "@/server/site-session.server";
import { backendRequest } from "@/lib/backend-transport.server";

/** Raporty klient/broker spod `/artifacts/...`.
 *
 *  Backend skleja te odnośniki z PUBLIC_BASE_URL, a ten host tunel kieruje na
 *  dashboard — FastAPI nie ma już własnego wpisu ingress i z internetu jest
 *  nieosiągalny. Bez tego proxy każdy link do raportu trafiał w aplikację,
 *  która o `/artifacts` nic nie wie, i kończył się 404.
 *
 *  Trzymamy je za sesją dashboardu świadomie: raport brokerski zawiera marżę
 *  i ocenę wewnętrzną, a kliencki — dane klienta. Publiczny link do pliku
 *  na aukcyjnym backendzie byłby wyciekiem, nie wygodą.
 */

const MEDIA_TYPES: Record<string, string> = {
  html: "text/html; charset=utf-8",
  md: "text/markdown; charset=utf-8",
  json: "application/json; charset=utf-8",
  txt: "text/plain; charset=utf-8",
};

export const Route = createFileRoute("/artifacts/$filename")({
  server: {
    handlers: {
      GET: async ({ params }) => {
        const unauthorized = await siteSessionGuard();
        if (unauthorized) return unauthorized;

        // Nazwa pliku idzie do ścieżki backendu, więc nie może z niej wyjść.
        const filename = String(params.filename ?? "");
        if (!/^[A-Za-z0-9._-]+$/.test(filename) || filename.includes("..")) {
          return new Response("Nieprawidłowa nazwa artefaktu", { status: 400 });
        }

        const extension = filename.split(".").pop()?.toLowerCase() ?? "";
        try {
          const body = await backendRequest<string>({
            path: `/artifacts/${encodeURIComponent(filename)}`,
            responseType: "text",
            timeoutMs: 30_000,
          });
          return new Response(body, {
            headers: {
              "Content-Type": MEDIA_TYPES[extension] ?? "application/octet-stream",
              // Raporty mają się otwierać, nie pobierać — to strony do czytania.
              "Content-Disposition": "inline",
              "Cache-Control": "private, max-age=60",
            },
          });
        } catch (error) {
          const status =
            error && typeof error === "object" && "status" in error
              ? Number((error as { status: number }).status)
              : 0;
          if (status === 404) {
            return new Response("Nie znaleziono raportu", { status: 404 });
          }
          return new Response("Backend nie oddał raportu", { status: 502 });
        }
      },
    },
  },
});
