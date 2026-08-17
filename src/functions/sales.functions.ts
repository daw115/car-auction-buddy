// Skrzynka agenta sprzedażowego — proxy do FastAPI.
//
// Wszystko idzie przez server function, tak jak reszta panelu, żeby Bearer token
// nie trafił do bundla klienta (patrz backend.functions.ts). Endpointy sprzedażowe
// są za tym samym tokenem co reszta — publiczny jest tylko formularz z landing
// page'a, którego panel nie wywołuje.
//
// ŻADNA Z TYCH FUNKCJI NIE WYSYŁA WIADOMOŚCI DO KLIENTA. `approveDraft` zapisuje
// ją jako wysłaną i zwraca link wa.me — otwiera go broker, ze swojego telefonu.

import { createServerFn } from "@tanstack/react-start";
import { z } from "zod";

import { siteSessionMiddleware } from "@/functions/site-session-middleware.functions";
import { devRequestLogger } from "@/functions/dev-logging-middleware.functions";
import { backendRequest } from "@/lib/backend-transport.server";
import type { CarLot } from "@/lib/types";

// ---------- typy ----------

export type LeadSegment = "A" | "B" | "C" | "D";

export type ScoreComponent = {
  key: string;
  label: string;
  value: number;
  weight: number;
  points: number;
  note: string;
};

export type LeadScore = {
  score: number;
  segment: LeadSegment;
  segment_label: string;
  summary: string;
  next_action: string;
  red_flags: string[];
  missing: string[];
  components: ScoreComponent[];
};

export type Lead = {
  id: number;
  name: string | null;
  display_name: string;
  phone: string | null;
  email: string | null;
  channel: string;
  stage: string;
  raw_request: string;
  make: string | null;
  model: string | null;
  year_from: number | null;
  year_to: number | null;
  budget_pln: number | null;
  settlement: string;
  timeline_days: number | null;
  /** Warunek wznowienia — „najpierw muszę sprzedać auto" to wyzwalacz, nie termin. */
  blocked_by: string | null;
  /** Auto w rozliczeniu. Dla wielu klientów TO JEST budżet. */
  trade_in_model: string | null;
  trade_in_year: number | null;
  trade_in_value_pln: number | null;
  trade_in_sold: boolean;
  engine_hint: string | null;
  trim_hint: string | null;
  /** Sufit przebiegu z rozmowy. Backend go zwraca, typ o nim milczał. */
  max_odometer_mi: number | null;
  damage_ok: boolean | null;
  bought_before: boolean;
  referred_by: string | null;
  notes: string;
  created_at: string | null;
  updated_at: string | null;
  last_client_message_at: string | null;
  /** Ustawiane dopiero przez /promote — panel po tym poznaje, czy pokazać awans. */
  client_id: number | null;
  /**
   * Dwa budżety, bo klient ma dwie różne kwoty — liczone przez backend, nie trzymane.
   *
   * `confirmed` to pieniądze, które ma dzisiaj; `potential` to kwota po sprzedaży auta
   * w rozliczeniu. Sito patrzy na potencjał (czy warto poświęcić czas), a wyszukiwanie
   * i wycena na potwierdzony (co mu dziś pokazać). Różnica między nimi jest treścią
   * rozmowy: „mam sto, będę miał sto osiemdziesiąt pięć po sprzedaży Audi".
   */
  confirmed_budget_pln: number | null;
  potential_budget_pln: number | null;
  /** Na co lead czeka, zanim będzie mógł kupić. Null = na nic. */
  waiting_on: string | null;
};

export type InboxItem = {
  id: number;
  lead_id: number;
  text: string;
  channel: string;
  rationale: string;
  stage_after: string | null;
  created_at: string | null;
  lead: Lead | null;
  score: LeadScore;
  wa_me: string | null;
  search?: LeadSearch;
};

export type Inbox = {
  count: number;
  items: InboxItem[];
  /**
   * Leady bez propozycji, na które ktoś czeka — nigdy do nich nie napisaliśmy albo
   * ostatnie słowo należy do klienta. Nie mogą zniknąć tylko dlatego, że agent nie
   * miał czego napisać: to awaria, która wygląda jak cisza.
   */
  needs_attention: Array<
    Lead & { score: LeadScore; waiting_since: string | null; last_client_message: string | null }
  >;
  /**
   * Odrzuceni przez sito — z powodem i warunkiem powrotu. Backend świadomie ich
   * ZWRACA zamiast ukrywać: filtr, który chowa leada bez śladu, jest nie do
   * odróżnienia od cichej utraty klienta. Panel musi ich pokazać, choćby zwiniętych.
   */
  parked?: Array<InboxItem & { parked_reasons: string[]; unlock: string[] }>;
  /** Progi sita — żeby napisać brokerowi, czego brakuje, a nie samo „odrzucony". */
  gate?: { min_budget_pln: number; min_score: number };
};

export type ConversationMessage = {
  id: number;
  author: "klient" | "broker" | "agent";
  text: string;
  channel: string | null;
  created_at: string | null;
  sent_at: string | null;
};

export type LeadDetail = Lead & {
  score: LeadScore;
  messages: ConversationMessage[];
  pending_drafts: InboxItem[];
};

export type ApproveResult = {
  sent: boolean;
  text: string;
  channel: string | null;
  wa_me: string | null;
  mailto: string | null;
  lead: Lead | null;
};

// ---------- wywołania ----------

export const getSalesInbox = createServerFn({ method: "GET" })
  .middleware([devRequestLogger, siteSessionMiddleware])
  .handler(
    async (): Promise<Inbox> => backendRequest<Inbox>({ path: "/api/sales/inbox", method: "GET" }),
  );

export const getSalesLeads = createServerFn({ method: "GET" })
  .middleware([devRequestLogger, siteSessionMiddleware])
  .handler(
    async (): Promise<{ count: number; items: Array<Lead & { score: LeadScore }> }> =>
      backendRequest({ path: "/api/sales/leads", method: "GET" }),
  );

export const getLeadDetail = createServerFn({ method: "GET" })
  .middleware([devRequestLogger, siteSessionMiddleware])
  .inputValidator(z.object({ leadId: z.number().int().positive() }).parse)
  .handler(
    async ({ data }): Promise<LeadDetail> =>
      backendRequest<LeadDetail>({ path: `/api/sales/leads/${data.leadId}`, method: "GET" }),
  );

/**
 * ZGODA BROKERA na wysłanie. Zwraca gotowy link wa.me — kliknięcie w niego jest
 * ostatnim krokiem i należy do człowieka.
 */
/** Ręczna zmiana etapu w lejku. Backend przesuwa automatycznie tylko cztery
 *  przejścia (nowy→kwalifikacja, →szukanie przy komplecie kryteriów, oferta→rozmowa
 *  po odpowiedzi klienta, oraz stage_after przy zatwierdzeniu draftu). Wszystko od
 *  etapu "decyzja" w dół przestawia człowiek — dotąd nie miał czym. */
export const setLeadStage = createServerFn({ method: "POST" })
  .middleware([devRequestLogger, siteSessionMiddleware])
  .inputValidator(
    z.object({ leadId: z.number().int().positive(), stage: z.string().min(1).max(40) }).parse,
  )
  .handler(async ({ data }) =>
    backendRequest<{ lead: Lead }>({
      path: `/api/sales/leads/${data.leadId}/stage`,
      method: "PUT",
      body: { stage: data.stage },
    }),
  );

export const approveDraft = createServerFn({ method: "POST" })
  .middleware([devRequestLogger, siteSessionMiddleware])
  .inputValidator(
    z.object({
      draftId: z.number().int().positive(),
      editedText: z.string().max(2000).optional(),
    }).parse,
  )
  .handler(
    async ({ data }): Promise<ApproveResult> =>
      backendRequest<ApproveResult>({
        path: `/api/sales/drafts/${data.draftId}/approve`,
        method: "POST",
        body: { edited_text: data.editedText ?? null },
      }),
  );

export const rejectDraft = createServerFn({ method: "POST" })
  .middleware([devRequestLogger, siteSessionMiddleware])
  .inputValidator(
    z.object({
      draftId: z.number().int().positive(),
      reason: z.string().max(500).default(""),
    }).parse,
  )
  .handler(
    async ({ data }): Promise<{ rejected: boolean }> =>
      backendRequest({
        path: `/api/sales/drafts/${data.draftId}/reject`,
        method: "POST",
        body: { reason: data.reason },
      }),
  );

/** Broker wkleja to, co klient odpisał na WhatsAppie. Agent proponuje odpowiedź. */
export const recordClientReply = createServerFn({ method: "POST" })
  .middleware([devRequestLogger, siteSessionMiddleware])
  .inputValidator(
    z.object({
      leadId: z.number().int().positive(),
      text: z.string().min(1).max(2000),
    }).parse,
  )
  .handler(
    async ({ data }): Promise<{ lead: Lead; score: LeadScore; draft: InboxItem | null }> =>
      backendRequest({
        path: `/api/sales/leads/${data.leadId}/reply`,
        method: "POST",
        body: { text: data.text, channel: "whatsapp" },
      }),
  );

/** Podsumowanie przy leadzie — bez samych lotów, tylko ich liczba. */
export type LeadSearch = {
  status: "brak" | "running" | "done" | "error";
  candidate_count: number;
  error?: string | null;
  finished_at?: string | null;
  offer_ready: boolean;
};

/**
 * Kandydat z wyszukiwania: lot razem z oceną, w kolejności z rankingu.
 *
 * Ocena zostaje przy locie, bo broker wybiera auta patrząc na nią i na uzasadnienie,
 * a nie na sam opis. `CarLot` jest współdzielony z resztą panelu, więc karta leada
 * i lista wyników pokazują to samo auto tak samo.
 */
export type LeadCandidate = {
  lot: CarLot;
  score: number | null;
  recommendation: string | null;
  reasoning: string | null;
  is_top: boolean;
};

/**
 * Uruchamia wyszukiwanie z kryteriów leada. Wraca od razu — scrape leci w tle
 * i trwa minuty, więc postęp czyta się przez `getLeadCandidates`.
 */
export const startLeadSearch = createServerFn({ method: "POST" })
  .middleware([devRequestLogger, siteSessionMiddleware])
  .inputValidator(z.object({ leadId: z.number().int().positive() }).parse)
  .handler(
    async ({ data }): Promise<{ started: boolean; warnings: string[] }> =>
      backendRequest({ path: `/api/sales/leads/${data.leadId}/search`, method: "POST" }),
  );

export const getLeadCandidates = createServerFn({ method: "GET" })
  .middleware([devRequestLogger, siteSessionMiddleware])
  .inputValidator(z.object({ leadId: z.number().int().positive() }).parse)
  .handler(
    async ({
      data,
    }): Promise<{
      status: LeadSearch["status"];
      candidates: LeadCandidate[];
      offer_ready: boolean;
      error?: string | null;
    }> => backendRequest({ path: `/api/sales/leads/${data.leadId}/candidates`, method: "GET" }),
  );

/**
 * Propozycja wiadomości, która ZNA auta wybrane przez brokera.
 *
 * Bez tego wywołania agent dostawał puste pole `offers` i pisał ogólniki —
 * backend liczył ceny pod drzwi do szuflady. Kolejności zaznaczonych aut nie
 * zmieniamy: broker wybrał je w takiej i taką zobaczy klient.
 */
export const proposeOffer = createServerFn({ method: "POST" })
  .middleware([devRequestLogger, siteSessionMiddleware])
  .inputValidator(
    z.object({
      leadId: z.number().int().positive(),
      // Backend i tak bierze z tego 3-4 auta; limit chroni przed wysłaniem
      // całej listy wyników w ciele żądania.
      lots: z.array(z.record(z.string(), z.unknown())).min(1).max(10),
    }).parse,
  )
  .handler(
    async ({ data }): Promise<{ draft: InboxItem | null; reason?: string }> =>
      // Backend zwraca tez `offers` (wyliczone ceny pod drzwi), ale panel ich nie
      // renderuje — kwoty sa juz w tresci propozycji. Nie deklarujemy ich w typie,
      // zeby nie obiecywac ksztaltu, ktorego nikt nie czyta.
      backendRequest({
        path: `/api/sales/leads/${data.leadId}/offer`,
        method: "POST",
        body: { lots: data.lots },
        // Agent liczy kilkadziesiąt sekund — domyślny timeout uciąłby go w połowie.
        timeoutMs: 180_000,
      }),
  );

/**
 * Przerzuca propozycję na Telegram brokera, z przyciskami „Wyślij" i „Odrzuć".
 *
 * Po to, żeby zatwierdzać z telefonu w trakcie rozmowy, bez wracania do panelu.
 * Naciśnięcie „Wyślij" idzie tą samą drogą co przycisk tutaj (approve_and_send),
 * a potem wstawia treść w rozmowę na WhatsApp Web.
 */
/**
 * Wysyła raport na Telegram brokera, żeby przekazał go klientowi w WhatsAppie.
 *
 * Link `wa.me` przenosi wyłącznie tekst i nie da się tym podać załącznika.
 * Bot dociera natomiast na ten sam telefon, na którym toczy się rozmowa —
 * plik przychodzi w kilka sekund i przekazuje się go jednym gestem.
 *
 * `oferta-png` to pierwszy kontakt: obrazek, nie PDF. Klient widzi trzy auta
 * od razu w wątku, zamiast pobierać plik i otwierać go w innej aplikacji.
 * PDF-y (`klient`, `broker`) idą dopiero wtedy, gdy wskaże numer.
 */
export const raportNaTelegram = createServerFn({ method: "POST" })
  .middleware([devRequestLogger, siteSessionMiddleware])
  .inputValidator(
    z.object({
      rodzaj: z.enum(["oferta-png", "shortlist", "klient", "broker"]),
      lots: z.array(z.record(z.string(), z.unknown())).min(1).max(10),
      clientName: z.string().max(160).optional().nullable(),
    }).parse,
  )
  .handler(
    async ({
      data,
    }): Promise<{
      wyslane: number;
      plik: string;
      rozmiar_kb: number;
      /** Treść wiadomości do klienta — tylko przy `oferta-png`. Obrazek pokazuje
       *  auta, ten tekst mówi, co z nimi zrobić. */
      tekst?: string;
    }> =>
      backendRequest({
        path: `/report/na-telegram?rodzaj=${data.rodzaj}`,
        method: "POST",
        body: {
          approved_lots: data.lots.map((lot) => ({ ...lot, included_in_report: true })),
          client_name: data.clientName ?? null,
        },
        // Render PDF-a ze zdjęciami wklejonymi jako data: potrafi potrwać.
        timeoutMs: 120_000,
      }),
  );

/** Cztery kroki sprawy: oferta wstępna, wybór klienta, raport, decyzja. */
export type WyslaneAuto = { lot_id?: string | null; nazwa?: string; url?: string | null };

export type StanSprawy = {
  lead_id: number;
  krok: number;
  krok_nazwa: string;
  wyslane: WyslaneAuto[];
  wybrane: WyslaneAuto[];
  raporty: string[];
  decyzja: string | null;
  notatka: string;
  zmieniono: string | null;
};

export const getStanSprawy = createServerFn({ method: "GET" })
  .middleware([devRequestLogger, siteSessionMiddleware])
  .inputValidator(z.object({ leadId: z.number().int().positive() }).parse)
  .handler(
    async ({ data }): Promise<StanSprawy> =>
      backendRequest({ path: `/api/sales/leads/${data.leadId}/sprawa`, method: "GET" }),
  );

/** Krok 2: na które auta wskazał klient. Identyfikatory z oferty wstępnej. */
export const zapiszWybor = createServerFn({ method: "POST" })
  .middleware([devRequestLogger, siteSessionMiddleware])
  .inputValidator(
    z.object({
      leadId: z.number().int().positive(),
      lotIds: z.array(z.string().min(1)).max(10),
    }).parse,
  )
  .handler(
    async ({ data }): Promise<StanSprawy> =>
      backendRequest({
        path: `/api/sales/leads/${data.leadId}/sprawa/wybor`,
        method: "POST",
        body: { lot_ids: data.lotIds },
      }),
  );

/** Co klient wskazał, sądząc po tym, co odpisał na ofertę.
 *
 *  Podpowiedź, nie automat: backend czyta z tekstu numery pozycji, panel je
 *  zaznacza, a potwierdza broker. „Mam 2 dzieci" też zawiera dwójkę.
 */
export const odczytajWybor = createServerFn({ method: "POST" })
  .middleware([devRequestLogger, siteSessionMiddleware])
  .inputValidator(
    z.object({
      leadId: z.number().int().positive(),
      tekst: z.string().min(1).max(2000),
    }).parse,
  )
  .handler(
    async ({ data }): Promise<{ numery: number[]; lot_ids: string[]; auta: WyslaneAuto[] }> =>
      backendRequest({
        path: `/api/sales/leads/${data.leadId}/sprawa/wybor-z-odpowiedzi`,
        method: "POST",
        body: { tekst: data.tekst },
      }),
  );

/** Krok 2 → 3 jednym kliknięciem: zapisuje wybór i wysyła oba raporty na Telegram.
 *
 *  Bez tego broker musiał zaznaczyć wybór, wrócić do listy kandydatów, odszukać
 *  tam to samo auto i wysłać raport osobnym przyciskiem.
 */
export const wyslijRaportSzczegolowy = createServerFn({ method: "POST" })
  .middleware([devRequestLogger, siteSessionMiddleware])
  .inputValidator(
    z.object({
      leadId: z.number().int().positive(),
      lotIds: z.array(z.string().min(1)).max(3),
    }).parse,
  )
  .handler(
    async ({ data }): Promise<{ sprawa: StanSprawy; pliki: string[]; rozmiar_kb: number }> =>
      backendRequest({
        path: `/api/sales/leads/${data.leadId}/sprawa/raport-szczegolowy`,
        method: "POST",
        body: { lot_ids: data.lotIds },
      }),
  );

/** Krok 4: decyzja klienta. Dwie wartości, bez „zastanawia się". */
export const zapiszDecyzje = createServerFn({ method: "POST" })
  .middleware([devRequestLogger, siteSessionMiddleware])
  .inputValidator(
    z.object({
      leadId: z.number().int().positive(),
      decyzja: z.enum(["kupuje", "rezygnuje"]),
      notatka: z.string().max(2000).default(""),
    }).parse,
  )
  .handler(
    async ({ data }): Promise<StanSprawy> =>
      backendRequest({
        path: `/api/sales/leads/${data.leadId}/sprawa/decyzja`,
        method: "POST",
        body: { decyzja: data.decyzja, notatka: data.notatka },
      }),
  );

export const sendDraftToTelegram = createServerFn({ method: "POST" })
  .middleware([devRequestLogger, siteSessionMiddleware])
  .inputValidator(z.object({ draftId: z.number().int().positive() }).parse)
  .handler(
    async ({ data }): Promise<{ wyslane: number; draft_id: number }> =>
      backendRequest({
        path: `/api/sales/drafts/${data.draftId}/na-telegram`,
        method: "POST",
      }),
  );

export const regenerateDraft = createServerFn({ method: "POST" })
  .middleware([devRequestLogger, siteSessionMiddleware])
  .inputValidator(z.object({ leadId: z.number().int().positive() }).parse)
  .handler(
    async ({ data }): Promise<{ draft: InboxItem | null; reason?: string }> =>
      backendRequest({
        path: `/api/sales/leads/${data.leadId}/regenerate`,
        method: "POST",
        // Model potrafi liczyć kilkadziesiąt sekund; domyślny timeout transportu
        // uciąłby wywołanie w połowie i broker zobaczyłby błąd zamiast propozycji.
        timeoutMs: 180_000,
      }),
  );

/** PATCH /api/sales/leads/{id} — poprawki po telefonie z klientem.
 *
 *  Wysyłamy WYŁĄCZNIE pola, które broker zmienił: backend rozróżnia „pola nie ma"
 *  od „pole ustawione na null", a `damage_ok` jest trójstanem, gdzie null znaczy
 *  „nie pytaliśmy", a nie „klient odmawia auta po szkodzie".
 */
export const patchLead = createServerFn({ method: "POST" })
  .middleware([devRequestLogger, siteSessionMiddleware])
  .inputValidator(
    z.object({
      leadId: z.number().int().positive(),
      changes: z
        .object({
          name: z.string().max(120).nullable().optional(),
          phone: z.string().max(40).optional(),
          email: z.string().max(160).nullable().optional(),
          make: z.string().max(60).nullable().optional(),
          model: z.string().max(60).nullable().optional(),
          year_from: z.number().int().min(1980).max(2100).nullable().optional(),
          year_to: z.number().int().min(1980).max(2100).nullable().optional(),
          budget_pln: z.number().min(0).max(10_000_000).nullable().optional(),
          settlement: z.enum(["private", "company"]).optional(),
          max_odometer_mi: z.number().int().min(0).max(1_000_000).nullable().optional(),
          damage_ok: z.boolean().nullable().optional(),
          timeline_days: z.number().int().min(0).max(3650).nullable().optional(),
          notes: z.string().max(4000).optional(),
          // Warunek wznowienia i auto w rozliczeniu. Bez nich formularz mógł
          // przestawić `trade_in_sold`, ale nie zapisać wartości auta — a to od niej
          // zależy różnica między budżetem potwierdzonym a potencjalnym.
          blocked_by: z.string().max(200).nullable().optional(),
          trade_in_model: z.string().max(120).nullable().optional(),
          trade_in_year: z.number().int().min(1980).max(2100).nullable().optional(),
          trade_in_value_pln: z.number().min(0).max(10_000_000).nullable().optional(),
          trade_in_sold: z.boolean().optional(),
          engine_hint: z.string().max(60).nullable().optional(),
          trim_hint: z.string().max(120).nullable().optional(),
        })
        .refine((c) => Object.keys(c).length > 0, "Nie ma czego zapisać."),
    }).parse,
  )
  .handler(
    async ({
      data,
    }): Promise<{
      lead: Lead;
      score: LeadScore;
      changed: string[];
      /** Czy lead przechodzi sito po zmianie — budżet edytuje się zwykle właśnie po to. */
      gate: { passes: boolean; reasons: string[]; unlock: string[] };
    }> =>
      backendRequest({
        path: `/api/sales/leads/${data.leadId}`,
        method: "PATCH",
        body: data.changes,
      }),
  );

/** POST /api/sales/leads/{id}/promote — wygrana sprzedaż zostawia ślad w bazie klientów.
 *
 *  Świadomie osobna akcja brokera, nie skutek uboczny zmiany etapu: automat przy
 *  przejściu na „wygrana" zaśmieciłby bazę przy pierwszym błędnym kliknięciu w select.
 *  Idempotentne — drugie kliknięcie nie zakłada duplikatu.
 */
/**
 * Awans leada na klienta — i jedyne miejsce, gdzie schodzą się dwa zbiory danych.
 *
 * Backend prowadzi leady w swoim SQLite i tam zapisuje `client_id`. Kartoteka
 * klientów, którą broker ogląda pod /clients, żyje w Postgresie (`clients_v2`)
 * razem ze sprawami i przypiętymi wyszukiwaniami. Do sierpnia 2026 awans pisał
 * WYŁĄCZNIE do SQLite, więc wygrana sprzedaż nie zostawiała śladu tam, gdzie
 * broker patrzy — ostatnie ogniwo lejka kończyło się w niewidocznej tabeli.
 *
 * Rozstrzygnięcie: kartoteka w Postgresie jest źródłem prawdy o kliencie, bo to
 * ona ma sprawy i historię wyszukiwań. Awans zapisuje więc w obu miejscach —
 * backend odnotowuje fakt przy leadzie, a panel zakłada (lub odnajduje) klienta.
 *
 * Dopasowanie po telefonie, nie po nazwisku: nazwiska się powtarzają, a numer
 * jest tym, czym broker i tak posługuje się w WhatsAppie.
 */
export const promoteLead = createServerFn({ method: "POST" })
  .middleware([devRequestLogger, siteSessionMiddleware])
  .inputValidator(z.object({ leadId: z.number().int().positive() }).parse)
  .handler(
    async ({
      data,
      context,
    }): Promise<{
      client_id: number;
      created: boolean;
      message: string;
      /** UUID w kartotece Postgresa — tam prowadzi przycisk po awansie. */
      crm_client_id: string | null;
    }> => {
      const wynik = await backendRequest<{
        client_id: number;
        created: boolean;
        message: string;
        lead?: Lead;
      }>({ path: `/api/sales/leads/${data.leadId}/promote`, method: "POST" });

      // LeadDetail rozszerza Lead wprost, wiec pola kontaktowe sa na wierzchu.
      const lead: Lead =
        wynik.lead ??
        (await backendRequest<LeadDetail>({
          path: `/api/sales/leads/${data.leadId}`,
          method: "GET",
        }));

      const nazwa = lead?.display_name?.trim() || `Lead #${data.leadId}`;
      const telefon = lead?.phone?.trim() || null;

      // Awans nie może się wywrócić przez kartotekę: lead jest już awansowany po
      // stronie backendu, a broker ma dostać potwierdzenie, nie czerwony błąd.
      try {
        const { supabaseAdmin } = await import("@/integrations/supabase/client.server");

        let istniejacy: { id: string } | null = null;
        if (telefon) {
          const { data: znaleziony } = await supabaseAdmin
            .from("clients_v2")
            .select("id")
            .eq("phone", telefon)
            .limit(1)
            .maybeSingle();
          istniejacy = znaleziony ?? null;
        }

        if (istniejacy) {
          return { ...wynik, crm_client_id: istniejacy.id };
        }

        const { data: nowy, error } = await supabaseAdmin
          .from("clients_v2")
          .insert({
            name: nazwa,
            phone: telefon,
            email: lead?.email ?? null,
            notes: `Awansowany z leada #${data.leadId}.`,
            created_by: context.siteUser,
          })
          .select("id")
          .single();
        if (error) throw new Error(error.message);
        return { ...wynik, crm_client_id: nowy?.id ?? null };
      } catch (blad) {
        console.error("[promote] lead awansowany, ale kartoteka nie zapisana:", blad);
        return { ...wynik, crm_client_id: null };
      }
    },
  );
