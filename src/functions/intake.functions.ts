/** Wywiad z klientem: rozmowa, nagranie, tekst — wszystko wpada tym samym korytem.
 *
 *  Backend miał te trzy wejścia od dawna, ale panel nie miał do nich żadnego
 *  przycisku, więc broker przepisywał wymagania ręcznie. Każde z nich kończy się
 *  tym samym: gotowe kryteria plus lista pól, których klient NIE potwierdził.
 *
 *  Żadne z nich nie uruchamia wyszukiwania. Transkrypt bywa niedosłowny, a scrape
 *  trwa kilkanaście minut — broker ma najpierw zobaczyć, co system zrozumiał.
 */

import { createServerFn } from "@tanstack/react-start";
import { siteSessionMiddleware } from "@/functions/site-session-middleware.functions";
import { devRequestLogger } from "@/functions/dev-logging-middleware.functions";
import { backendRequest } from "@/lib/backend-transport.server";
import type { ClientCriteria } from "@/lib/types";

export type IntakeResult = {
  criteria: ClientCriteria | null;
  /** Pola, których klient nie potwierdził — do dopytania, nie do zgadywania. */
  assumed: string[];
  summary: string;
  transcript?: {
    text: string;
    language: string;
    durationSeconds: number;
    model: string;
  } | null;
  chat?: string;
  messages?: Array<{ kierunek: "klient" | "broker"; tekst: string }>;
  total?: number;
};

/** Czyta rozmowę OTWARTĄ w oknie operatora. Nie przegląda listy czatów. */
export const readWhatsappConversation = createServerFn({ method: "POST" })
  .middleware([devRequestLogger, siteSessionMiddleware])
  .handler(
    async (): Promise<IntakeResult> =>
      backendRequest<IntakeResult>({
        path: "/api/intake/whatsapp",
        method: "POST",
        timeoutMs: 180_000,
      }),
  );

// Wiadomość wklejona ręcznie ma już server function w backend.functions.ts
// (backendParseClientMessage) — nie dublujemy jej tutaj.
