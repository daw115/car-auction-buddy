import type { AuctionSource } from "@/lib/auction-sources";

// Shared types used by both client UI and server functions.
// Mirror the structure of usa-car-finder/parser/models.py (CarLot, ClientCriteria, AIAnalysis).

export type CarLot = {
  source: AuctionSource;
  lot_id: string;
  url?: string;
  vin?: string | null;
  full_vin?: string | null;
  year?: number | null;
  make?: string | null;
  model?: string | null;
  trim?: string | null;
  odometer_mi?: number | null;
  odometer_km?: number | null;
  fuel_type?: string | null;
  raw_data?: Record<string, string | number | boolean | null | undefined> | null;
  damage_primary?: string | null;
  damage_secondary?: string | null;
  title_type?: string | null;
  current_bid_usd?: number | null;
  buy_now_price_usd?: number | null;
  seller_reserve_usd?: number | null;
  seller_type?: string | null;
  location_state?: string | null;
  location_city?: string | null;
  auction_date?: string | null;
  keys?: boolean | null;
  airbags_deployed?: boolean | null;
  images?: string[];
  enriched_by_extension?: boolean;
};

export type SearchTarget = {
  make: string;
  model?: string | null;
};

export type ClientCriteria = {
  make: string;
  model?: string | null;
  year_from?: number | null;
  year_to?: number | null;
  budget_usd?: number | null;
  max_odometer_mi?: number | null;
  fuel_type?: "Gas" | "Hybrid" | "Diesel" | "Electric" | null;
  excluded_damage_types?: string[];
  max_results?: number;
  sources?: AuctionSource[];
  /** Dodatkowe pary marka+model. Klient rzadko podaje jeden model — w notatkach
   *  z rozmów pada "karoq kodiaq, vw tiguan". */
  targets?: SearchTarget[];
  /** Segment z pierwszej rozmowy ("suv"). Kontekst dla agenta, nie filtr: samo
   *  nadwozie niczego nie zawęzi w wyszukiwaniu pełnotekstowym Copart/IAAI. */
  segment?: string | null;
  /** Budżet "pod klucz" w Polsce, tak jak podaje go klient ("50/60 tys").
   *  Sufit ceny aukcyjnej liczy backend — zależy od stanu USA i formy zakupu. */
  budget_pln_from?: number | null;
  budget_pln_to?: number | null;
  /** Forma zakupu przesuwa sufit o ~1400 USD przy 50 tys. zł. */
  settlement?: "private" | "company";
};

export type AIAnalysis = {
  lot_id: string;
  score: number;
  recommendation: "POLECAM" | "RYZYKO" | "ODRZUĆ" | string;
  red_flags: string[];
  estimated_repair_usd?: number | null;
  estimated_total_cost_usd?: number | null;
  client_description_pl: string;
  ai_notes?: string | null;
};

export type AnalyzedLot = {
  lot: CarLot;
  analysis: AIAnalysis;
  is_top_recommendation?: boolean;
  included_in_report?: boolean;
  auto_reports?: {
    client_hybrid_url?: string;
    client_url?: string;
    client_short_url?: string;
    broker_hybrid_url?: string;
    broker_url?: string;
  };
};
