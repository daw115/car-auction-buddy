// Publiczny checker VIN — trasa dostępna BEZ logowania.
//
// Jedna z dwóch ścieżek w całym panelu, które Cloudflare Access przepuszcza bez
// pytania o tożsamość (druga to /api/public/lead, a stroną jest /sprawdz-vin).
// Dlatego wolno jej sięgać wyłącznie do `/api/public/*` backendu: te endpointy
// nie znają żadnego klienta, żadnego leada i żadnej rozmowy. Dopisanie tu
// czegokolwiek spod innej ścieżki backendu wystawia dane panelu na świat —
// pilnuje tego test w src/functions/site-session-inventory.test.ts.

import { createFileRoute } from "@tanstack/react-router";
import { z } from "zod";

import { backendRequest } from "@/lib/backend-transport.server";

const wejscie = z.object({
  vin: z.string().min(8).max(20),
  bid_usd: z.number().positive().max(500_000).optional(),
  state: z.string().max(2).optional(),
  make: z.string().max(60).optional(),
  model: z.string().max(60).optional(),
  trim: z.string().max(120).optional(),
  settlement: z.enum(["private", "company"]).default("private"),
});

export const Route = createFileRoute("/api/public/vin-check")({
  server: {
    handlers: {
      POST: async ({ request }) => {
        const surowe = await request.json().catch(() => null);
        const dane = wejscie.safeParse(surowe);
        if (!dane.success) {
          return Response.json({ error: "Nieprawidłowy numer VIN." }, { status: 400 });
        }
        try {
          return Response.json(
            await backendRequest({
              path: "/api/public/vin-check",
              method: "POST",
              body: dane.data,
            }),
          );
        } catch (blad) {
          // Klient nie ma co zrobić z treścią błędu backendu, a ta potrafi zawierać
          // adres wewnętrzny albo fragment odpowiedzi — zostaje w logach serwera.
          console.error("[vin-check] backend nie odpowiedział:", blad);
          return Response.json(
            { error: "Sprawdzarka chwilowo nie działa. Spróbuj za kilka minut." },
            { status: 502 },
          );
        }
      },
    },
  },
});
