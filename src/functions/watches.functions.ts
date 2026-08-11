/** Nasłuchy aukcji pod klienta.
 *
 *  Jeden mechanizm, świadomie. Wcześniej były trzy: te nasłuchy, martwe
 *  `/api/queue` (czytało skasowane sekrety SCRAPER_*) i auto-refresh spraw
 *  w Supabase. Trzy źródła prawdy o tym samym to gwarancja, że dwa z nich
 *  cicho przestaną działać i nikt tego nie zauważy.
 *
 *  Nasłuch odzywa się DO BROKERA, nie do klienta — przygotowuje materiał,
 *  wysyła człowiek.
 */

import { createServerFn } from "@tanstack/react-start";
import { z } from "zod";
import { siteSessionMiddleware } from "@/functions/site-session-middleware.functions";
import { backendRequest } from "@/lib/backend-transport.server";
import type { CarLot, ClientCriteria } from "@/lib/types";
import { criteriaShape } from "@/functions/backend.functions";

export type Watch = {
  id: number;
  clientName: string | null;
  clientPhone: string | null;
  criteria: ClientCriteria;
  intervalHours: number;
  active: boolean;
  createdAt: number;
  lastRunAt: number | null;
  lastError: string | null;
  runs: number;
  foundTotal: number;
};

export const listWatches = createServerFn({ method: "GET" })
  .middleware([siteSessionMiddleware])
  .handler(
    async (): Promise<{ watches: Watch[] }> =>
      backendRequest({ path: "/api/watches", method: "GET" }),
  );

export const createWatch = createServerFn({ method: "POST" })
  .middleware([siteSessionMiddleware])
  .inputValidator(
    z.object({
      criteria: criteriaShape,
      clientName: z.string().max(160).optional().nullable(),
      clientPhone: z.string().max(40).optional().nullable(),
      // Minimum godzina: aukcje nie odświeżają się w minutach, a każdy przebieg
      // to realne wejście na Copart, IAAI i Manheima.
      intervalHours: z.number().min(1).max(168).default(12),
    }).parse,
  )
  .handler(
    async ({ data }): Promise<Watch> =>
      backendRequest({ path: "/api/watches", method: "POST", body: data }),
  );

export const deleteWatch = createServerFn({ method: "POST" })
  .middleware([siteSessionMiddleware])
  .inputValidator(z.object({ id: z.number().int().positive() }).parse)
  .handler(async ({ data }) =>
    backendRequest<{ status: string; id: number }>({
      path: `/api/watches/${data.id}`,
      method: "DELETE",
    }),
  );

export const setWatchActive = createServerFn({ method: "POST" })
  .middleware([siteSessionMiddleware])
  .inputValidator(z.object({ id: z.number().int().positive(), active: z.boolean() }).parse)
  .handler(
    async ({ data }): Promise<Watch> =>
      backendRequest({
        path: `/api/watches/${data.id}/pause?active=${data.active}`,
        method: "POST",
      }),
  );

export type WatchHit = {
  watchId: number;
  foundAt: number;
  lot: CarLot;
};

/** Co nasłuchy faktycznie znalazły — powiadomienie z Telegrama znika, to zostaje. */
export const listWatchHits = createServerFn({ method: "GET" })
  .middleware([siteSessionMiddleware])
  .inputValidator(
    z.object({
      watchId: z.number().int().positive().optional(),
      limit: z.number().int().min(1).max(200).default(20),
    }).parse,
  )
  .handler(async ({ data }): Promise<{ hits: WatchHit[] }> => {
    const query = new URLSearchParams({ limit: String(data.limit) });
    if (data.watchId) query.set("watch_id", String(data.watchId));
    return backendRequest({ path: `/api/watches/hits?${query}`, method: "GET" });
  });
