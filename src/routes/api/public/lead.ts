// Zgłoszenie po pełną kalkulację ze strony /sprawdz-vin — BEZ logowania.
//
// Tu klient pierwszy raz zostawia kontakt. Trasa przepuszczana przez Cloudflare
// Access bez pytania o tożsamość, więc obowiązuje ta sama reguła co w vin-check:
// wyłącznie `/api/public/*` backendu. Zgłoszenie ląduje w Skrzynce brokera —
// nic nie wraca do klienta automatycznie.

import { createFileRoute } from "@tanstack/react-router";
import { z } from "zod";

import { backendRequest } from "@/lib/backend-transport.server";

const wejscie = z.object({
  message: z.string().max(2000).default(""),
  name: z.string().max(120).optional(),
  phone: z.string().max(32).optional(),
  email: z.string().max(160).optional(),
  // Pole-pułapka. Człowiek go nie zobaczy, bot wypełni wszystko, co znajdzie.
  website: z.string().max(200).default(""),
});

export const Route = createFileRoute("/api/public/lead")({
  server: {
    handlers: {
      POST: async ({ request }) => {
        const surowe = await request.json().catch(() => null);
        const dane = wejscie.safeParse(surowe);
        if (!dane.success) {
          return Response.json(
            { error: "Sprawdź numer telefonu i spróbuj ponownie." },
            { status: 400 },
          );
        }
        try {
          return Response.json(
            await backendRequest({
              // Adres z krawędzi Cloudflare — bez niego backend widzi loopback
              // panelu i limit zgłoszeń działa globalnie dla całego świata.
              clientIp: request.headers.get("cf-connecting-ip"),
              path: "/api/public/leads",
              method: "POST",
              body: dane.data,
            }),
          );
        } catch (blad) {
          console.error("[public-lead] backend nie odpowiedział:", blad);
          return Response.json(
            { error: "Nie udało się wysłać zgłoszenia. Zadzwoń albo spróbuj później." },
            { status: 502 },
          );
        }
      },
    },
  },
});
