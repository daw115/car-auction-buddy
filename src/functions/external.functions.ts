// Zewnętrzne darmowe API (NHTSA + Frankfurter FX) jako chronione server functions.

import { createServerFn } from "@tanstack/react-start";
import { siteSessionMiddleware } from "@/functions/site-session-middleware.functions";
import {
  decodeVinExternal,
  decodeVinInputSchema,
  fetchRecallsExternal,
  getFxRatesExternal,
  recallsInputSchema,
  type FxRates,
  type RecallItem,
  type VinDecoded,
} from "@/server/external-apis.server";

export type { FxRates, RecallItem, VinDecoded } from "@/server/external-apis.server";

export const decodeVin = createServerFn({ method: "POST" })
  .middleware([siteSessionMiddleware])
  .inputValidator(decodeVinInputSchema.parse)
  .handler(async ({ data }): Promise<VinDecoded> => decodeVinExternal(data));

export const fetchRecalls = createServerFn({ method: "POST" })
  .middleware([siteSessionMiddleware])
  .inputValidator(recallsInputSchema.parse)
  .handler(async ({ data }): Promise<RecallItem[]> => fetchRecallsExternal(data));

export const getFxRates = createServerFn({ method: "GET" })
  .middleware([siteSessionMiddleware])
  .handler(async (): Promise<FxRates> => getFxRatesExternal());
