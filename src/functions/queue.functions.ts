import { createServerFn } from "@tanstack/react-start";
import { z } from "zod";

const criteriaSchema = z.object({}).passthrough();

function scraperBase() {
  const baseUrl = process.env.SCRAPER_BASE_URL?.replace(/\/+$/, "");
  if (!baseUrl) throw new Error("SCRAPER_BASE_URL nie jest ustawiony.");
  const token = process.env.SCRAPER_API_TOKEN;
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (token) headers.Authorization = `Bearer ${token}`;
  return { baseUrl, headers };
}

export type WatchEntry = {
  id: string;
  label?: string | null;
  interval_hours: number;
  next_run_at: string;
  runs_count?: number;
  last_result_count?: number | null;
  status?: string;
};

// POST /api/queue — add a recurring watch
export const createWatchQueue = createServerFn({ method: "POST" })
  .inputValidator(
    z.object({
      search: z.object({
        criteria: criteriaSchema,
        disable_auction_filter: z.boolean().optional(),
      }),
      interval_hours: z.number().int().min(1).max(168),
      label: z.string().max(200).optional(),
    }).parse,
  )
  .handler(async ({ data }): Promise<WatchEntry> => {
    const { baseUrl, headers } = scraperBase();
    const res = await fetch(`${baseUrl}/api/queue`, {
      method: "POST",
      headers,
      body: JSON.stringify(data),
    });
    const text = await res.text();
    if (!res.ok) {
      throw new Error(`Queue HTTP ${res.status}: ${text.slice(0, 400)}`);
    }
    try {
      return JSON.parse(text) as WatchEntry;
    } catch {
      throw new Error(`Queue: niepoprawny JSON: ${text.slice(0, 200)}`);
    }
  });

// GET /api/queue — list watches
export const listWatchQueue = createServerFn({ method: "GET" })
  .handler(async (): Promise<{ watches: WatchEntry[]; count: number }> => {
    const { baseUrl, headers } = scraperBase();
    const res = await fetch(`${baseUrl}/api/queue`, { headers });
    if (!res.ok) {
      const body = await res.text().catch(() => "");
      throw new Error(`Queue HTTP ${res.status}: ${body.slice(0, 200)}`);
    }
    return (await res.json()) as { watches: WatchEntry[]; count: number };
  });

// DELETE /api/queue/{id} — cancel watch
export const deleteWatchQueue = createServerFn({ method: "POST" })
  .inputValidator(z.object({ id: z.string().min(1) }).parse)
  .handler(async ({ data }) => {
    const { baseUrl, headers } = scraperBase();
    const res = await fetch(`${baseUrl}/api/queue/${encodeURIComponent(data.id)}`, {
      method: "DELETE",
      headers,
    });
    if (!res.ok && res.status !== 404) {
      const body = await res.text().catch(() => "");
      throw new Error(`Queue HTTP ${res.status}: ${body.slice(0, 200)}`);
    }
    return { ok: true };
  });
