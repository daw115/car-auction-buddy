import { createServerFn } from "@tanstack/react-start";
import { siteSessionMiddleware } from "@/functions/site-session-middleware.functions";
import {
  createQueueWatch,
  createQueueWatchInputSchema,
  deleteQueueWatch,
  deleteQueueWatchInputSchema,
  listQueueWatches,
  type WatchEntry,
  type WatchQueueList,
} from "@/server/scraper-queue.server";

export type { WatchEntry } from "@/server/scraper-queue.server";

// POST /api/queue — add a recurring watch
export const createWatchQueue = createServerFn({ method: "POST" })
  .middleware([siteSessionMiddleware])
  .inputValidator(createQueueWatchInputSchema.parse)
  .handler(async ({ data }): Promise<WatchEntry> => createQueueWatch(data));

// GET /api/queue — list watches
export const listWatchQueue = createServerFn({ method: "GET" })
  .middleware([siteSessionMiddleware])
  .handler(async (): Promise<WatchQueueList> => listQueueWatches());

// DELETE /api/queue/{id} — cancel watch
export const deleteWatchQueue = createServerFn({ method: "POST" })
  .middleware([siteSessionMiddleware])
  .inputValidator(deleteQueueWatchInputSchema.parse)
  .handler(async ({ data }) => deleteQueueWatch(data.id));
