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

/** Nagranie rozmowy z klientem — transkrypcja i spisane wymagania.
 *
 *  Backend potrafił to od dawna (`POST /api/intake/voice`, faster-whisper lokalnie),
 *  ale panel nie miał do tego żadnego przycisku — funkcja istniała wyłącznie w
 *  docstringu. Broker nie miał jak z niej skorzystać.
 *
 *  Nagranie NIE opuszcza serwera: transkrypcja idzie lokalnie, bo głos klienta to
 *  dane osobowe. Wyszukiwanie się nie uruchamia — transkrypt bywa niedosłowny,
 *  więc broker ma najpierw zobaczyć, co system usłyszał.
 *
 *  Wspólny transport wysyła JSON-a, a tu leci plik, więc żądanie budujemy sami.
 */
export const transcribeRecording = createServerFn({ method: "POST" })
  .middleware([devRequestLogger, siteSessionMiddleware])
  .inputValidator((dane: unknown) => {
    if (!(dane instanceof FormData)) throw new Error("Oczekuję nagrania jako FormData.");
    const plik = dane.get("file");
    if (!(plik instanceof File) || plik.size === 0) throw new Error("Nie ma pliku z nagraniem.");
    // Whisper na CPU liczy mniej wiecej w czasie rzeczywistym; 25 MB to okolo
    // godziny rozmowy i granica, po ktorej zadanie i tak by sie przeterminowalo.
    if (plik.size > 25 * 1024 * 1024) throw new Error("Nagranie większe niż 25 MB.");
    return dane;
  })
  .handler(async ({ data }): Promise<IntakeResult> => {
    const baza = process.env.API_BASE_URL;
    if (!baza) throw new Error("Backend nie jest skonfigurowany (API_BASE_URL).");
    const token = process.env.API_BEARER_TOKEN;

    const odpowiedz = await fetch(`${baza.replace(/\/$/, "")}/api/intake/voice`, {
      method: "POST",
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
      body: data,
      // Transkrypcja godzinnej rozmowy na CPU trwa tyle, co sama rozmowa.
      signal: AbortSignal.timeout(20 * 60 * 1000),
    });

    if (!odpowiedz.ok) {
      const tresc = await odpowiedz.text().catch(() => "");
      if (odpowiedz.status === 503) {
        throw new Error("Serwer nie ma silnika transkrypcji — zgłoś to administratorowi.");
      }
      throw new Error(tresc || `Backend odpowiedział ${odpowiedz.status}.`);
    }
    return (await odpowiedz.json()) as IntakeResult;
  });

// Wiadomość wklejona ręcznie ma już server function w backend.functions.ts
// (backendParseClientMessage) — nie dublujemy jej tutaj.
