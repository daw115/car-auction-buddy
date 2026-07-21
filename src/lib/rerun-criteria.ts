import { normalizeAuctionSources } from "@/lib/auction-sources";
import type { ClientCriteria } from "@/lib/types";

/**
 * sessionStorage key used to hand off criteria from a past record ("ponów
 * wyszukiwanie") to the home page search form, without adding a query-string
 * contract or touching routing. Cleared by the reader after consumption.
 */
export const RERUN_CRITERIA_STORAGE_KEY = "car-auction-buddy:rerun-criteria";

/** Extracts a safe, normalized ClientCriteria from an arbitrary record's stored criteria blob. */
export function extractRerunCriteria(rawCriteria: unknown): ClientCriteria | null {
  if (!rawCriteria || typeof rawCriteria !== "object") return null;
  const c = rawCriteria as Record<string, unknown>;
  const make = typeof c.make === "string" ? c.make.trim() : "";
  if (!make) return null;
  return {
    make,
    model: typeof c.model === "string" ? c.model : null,
    year_from: typeof c.year_from === "number" ? c.year_from : null,
    year_to: typeof c.year_to === "number" ? c.year_to : null,
    budget_usd: typeof c.budget_usd === "number" ? c.budget_usd : null,
    max_odometer_mi: typeof c.max_odometer_mi === "number" ? c.max_odometer_mi : null,
    fuel_type:
      c.fuel_type === "Gas" ||
      c.fuel_type === "Hybrid" ||
      c.fuel_type === "Diesel" ||
      c.fuel_type === "Electric"
        ? c.fuel_type
        : null,
    excluded_damage_types: Array.isArray(c.excluded_damage_types)
      ? c.excluded_damage_types.filter((v): v is string => typeof v === "string")
      : [],
    max_results: typeof c.max_results === "number" ? c.max_results : 15,
    sources: normalizeAuctionSources(Array.isArray(c.sources) ? (c.sources as string[]) : null),
  };
}
