import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/api/scraper-logs/probe")({
  server: {
    handlers: {
      GET: async () => {
        const baseUrl = process.env.SCRAPER_BASE_URL?.replace(/\/+$/, "");
        const token = process.env.SCRAPER_API_TOKEN;
        if (!baseUrl || !token) return Response.json({ error: "no env" }, { status: 503 });

        const candidates = [
          `/api/logs/stream`,
          `/logs/stream`,
          `/api/logs/tail?lines=5`,
          `/logs/tail?lines=5`,
          `/api/logs`,
          `/logs`,
        ];
        const results: any[] = [];
        for (const path of candidates) {
          const sep = path.includes("?") ? "&" : "?";
          const url = `${baseUrl}${path}${sep}token=${encodeURIComponent(token)}`;
          try {
            const ctrl = new AbortController();
            const t = setTimeout(() => ctrl.abort(), 4000);
            const r = await fetch(url, {
              headers: { Authorization: `Bearer ${token}`, Accept: "text/event-stream, */*" },
              signal: ctrl.signal,
            });
            clearTimeout(t);
            const ct = r.headers.get("content-type") || "";
            let bodyPreview = "";
            try {
              const txt = await r.text();
              bodyPreview = txt.slice(0, 200);
            } catch {}
            results.push({ path, status: r.status, ct, bodyPreview });
          } catch (e) {
            results.push({ path, error: (e as Error).message });
          }
        }
        return Response.json({ baseUrl, results });
      },
    },
  },
});
