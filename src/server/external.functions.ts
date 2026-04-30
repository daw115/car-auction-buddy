// Zewnętrzne darmowe API (NHTSA + Frankfurter FX) jako server functions.
// Wszystko bez kluczy, bez limitów istotnych dla tego use-case.

import { createServerFn } from "@tanstack/react-start";
import { z } from "zod";

// ---------- NHTSA VIN Decoder ----------

export type VinDecoded = {
  vin: string;
  make: string | null;
  model: string | null;
  year: number | null;
  trim: string | null;
  body_class: string | null;
  fuel_type: string | null;
  drive_type: string | null;
  transmission: string | null;
  engine_cc: number | null;
  engine_cylinders: number | null;
  engine_power_hp: number | null;
  manufacturer: string | null;
  plant_country: string | null;
  vehicle_type: string | null;
  errors: string[];
};

export const decodeVin = createServerFn({ method: "POST" })
  .inputValidator(z.object({ vin: z.string().trim().min(11).max(17) }).parse)
  .handler(async ({ data }): Promise<VinDecoded> => {
    const vin = data.vin.toUpperCase().replace(/[^A-Z0-9]/g, "");
    const url = `https://vpic.nhtsa.dot.gov/api/vehicles/decodevinvalues/${encodeURIComponent(vin)}?format=json`;
    const res = await fetch(url, { headers: { accept: "application/json" } });
    if (!res.ok) throw new Error(`NHTSA HTTP ${res.status}`);
    const json = (await res.json()) as { Results?: Array<Record<string, string>> };
    const r = json.Results?.[0] ?? {};
    const num = (v: string | undefined) => {
      if (!v) return null;
      const n = parseFloat(v.replace(",", "."));
      return Number.isFinite(n) ? n : null;
    };
    const ccFromLiters = num(r.DisplacementL);
    const ccDirect = num(r.DisplacementCC);
    const errors = (r.ErrorText ?? "").split(";").map((s) => s.trim()).filter((s) => s && s !== "0 - VIN decoded clean. Check Digit (9th position) is correct");
    return {
      vin,
      make: r.Make || null,
      model: r.Model || null,
      year: num(r.ModelYear) ? Math.round(num(r.ModelYear)!) : null,
      trim: r.Trim || null,
      body_class: r.BodyClass || null,
      fuel_type: r.FuelTypePrimary || null,
      drive_type: r.DriveType || null,
      transmission: r.TransmissionStyle || null,
      engine_cc: ccDirect ?? (ccFromLiters ? Math.round(ccFromLiters * 1000) : null),
      engine_cylinders: num(r.EngineCylinders) ? Math.round(num(r.EngineCylinders)!) : null,
      engine_power_hp: num(r.EngineHP) ? Math.round(num(r.EngineHP)!) : null,
      manufacturer: r.Manufacturer || null,
      plant_country: r.PlantCountry || null,
      vehicle_type: r.VehicleType || null,
      errors: errors.slice(0, 5),
    };
  });

// ---------- NHTSA Recalls ----------

export type RecallItem = {
  campaign_number: string;
  component: string;
  summary: string;
  consequence: string;
  remedy: string;
  report_received_date: string | null;
};

export const fetchRecalls = createServerFn({ method: "POST" })
  .inputValidator(
    z.object({
      make: z.string().trim().min(1).max(80),
      model: z.string().trim().min(1).max(80),
      year: z.number().int().min(1980).max(2100),
    }).parse,
  )
  .handler(async ({ data }): Promise<RecallItem[]> => {
    const url = `https://api.nhtsa.gov/recalls/recallsByVehicle?make=${encodeURIComponent(data.make)}&model=${encodeURIComponent(data.model)}&modelYear=${data.year}`;
    const res = await fetch(url, { headers: { accept: "application/json" } });
    if (!res.ok) return [];
    const json = (await res.json()) as { results?: Array<Record<string, string>> };
    return (json.results ?? []).slice(0, 20).map((r) => ({
      campaign_number: r.NHTSACampaignNumber || "",
      component: r.Component || "",
      summary: r.Summary || "",
      consequence: r.Consequence || "",
      remedy: r.Remedy || "",
      report_received_date: r.ReportReceivedDate || null,
    }));
  });

// ---------- Frankfurter FX (USD → PLN, EUR) ----------

export type FxRates = {
  usd_pln: number;
  usd_eur: number;
  fetched_at: string;
  source: string;
};

let fxCache: { value: FxRates; expires: number } | null = null;

export const getFxRates = createServerFn({ method: "GET" }).handler(async (): Promise<FxRates> => {
  const now = Date.now();
  if (fxCache && fxCache.expires > now) return fxCache.value;
  try {
    const res = await fetch("https://api.frankfurter.app/latest?from=USD&to=PLN,EUR", {
      headers: { accept: "application/json" },
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const json = (await res.json()) as { rates?: { PLN?: number; EUR?: number }; date?: string };
    const usd_pln = json.rates?.PLN ?? 4.0;
    const usd_eur = json.rates?.EUR ?? 0.92;
    const value: FxRates = {
      usd_pln,
      usd_eur,
      fetched_at: json.date ?? new Date().toISOString().slice(0, 10),
      source: "frankfurter.app",
    };
    fxCache = { value, expires: now + 6 * 60 * 60 * 1000 }; // cache 6h
    return value;
  } catch {
    // Fallback gdyby Frankfurter padł — przybliżone, ostrzega w UI
    return { usd_pln: 4.0, usd_eur: 0.92, fetched_at: new Date().toISOString().slice(0, 10), source: "fallback" };
  }
});
