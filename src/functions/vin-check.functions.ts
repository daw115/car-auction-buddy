// Publiczny checker VIN — jedyne funkcje serwerowe w tym projekcie BEZ `siteSessionMiddleware`.
//
// To jest zamierzone i wąskie. Obie proxy'ują wyłącznie do endpointów, które backend
// sam wystawia jako publiczne (`/api/public/*`) — nie sięgają do żadnych danych panelu,
// nie znają leadów ani rozmów. Dodanie tu czegokolwiek innego otworzyłoby panel na świat,
// bo brak middleware znaczy brak logowania.
//
// Token API i tak leci w nagłówku (robi to transport), ale backend go dla tych ścieżek
// nie sprawdza — dzięki temu ta sama funkcja działa i z landing page'a, i z panelu.

import { createServerFn } from "@tanstack/react-start";
import { z } from "zod";

import { backendRequest } from "@/lib/backend-transport.server";

export type VinCheckResult = {
  vin: string;
  assembly_country: string;
  assembled_in_usa: boolean;
  duty_rate_pct: number;
  duty_free: boolean;
  duty_reason: string;
  excise_rate_pct: number;
  excise_reason: string;
  drivetrain: string;
  drivetrain_confident: boolean;
  assumptions: string[];
  usd_rate: number;
  landed_pln?: number;
  landed_if_duty_10_pln?: number;
  saving_pln?: number;
};

const vinCheckInput = z.object({
  vin: z.string().min(8).max(20),
  bid_usd: z.number().positive().max(500_000).optional(),
  state: z.string().max(2).optional(),
  make: z.string().max(60).optional(),
  model: z.string().max(60).optional(),
  trim: z.string().max(120).optional(),
  settlement: z.enum(["private", "company"]).default("private"),
});

export const checkVin = createServerFn({ method: "POST" })
  .inputValidator(vinCheckInput.parse)
  .handler(
    async ({ data }): Promise<VinCheckResult> =>
      backendRequest<VinCheckResult>({
        path: "/api/public/vin-check",
        method: "POST",
        body: data,
      }),
  );

/** Zgłoszenie po pełną kalkulację — dopiero tu klient zostawia kontakt. */
export const submitPublicLead = createServerFn({ method: "POST" })
  .inputValidator(
    z.object({
      message: z.string().max(2000).default(""),
      name: z.string().max(120).optional(),
      phone: z.string().max(32).optional(),
      email: z.string().max(160).optional(),
      // Pole-pułapka. Człowiek go nie zobaczy, bot wypełni wszystko, co znajdzie.
      website: z.string().max(200).default(""),
    }).parse,
  )
  .handler(
    async ({ data }): Promise<{ ok: boolean }> =>
      backendRequest({ path: "/api/public/leads", method: "POST", body: data }),
  );
