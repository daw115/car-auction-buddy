// Deterministyczny kalkulator kosztu importu auta z USA do Polski.
// Używany w analizie AI (override pola estimated_total_cost_usd) i w narzędziu /calculator.
// Wszystkie wartości można nadpisać preset'em per-klient (cost_presets).

export type FuelType = "gasoline" | "diesel" | "hybrid" | "electric" | "lpg" | "other";

export type CostInputs = {
  car_price_usd: number;
  estimated_repair_usd?: number;
  state?: string | null; // np. "NY"
  engine_cc?: number | null; // pojemność silnika w cm³
  fuel?: FuelType;
  weight_kg?: number | null;
  // Override'y per klient
  broker_margin_pct?: number; // domyślnie 8
  exchange_rate_buffer_pct?: number; // bufor na wahania kursu, domyślnie 3
  transport_override_usd?: number | null;
};

export type CostBreakdown = {
  car_price_usd: number;
  repair_usd: number;
  transport_usa_to_pl_usd: number;
  port_fees_usd: number;
  customs_duty_usd: number; // 10% (cło)
  excise_tax_usd: number; // akcyza 3.1% lub 18.6%
  vat_usd: number; // 23%
  homologation_usd: number; // ~500 USD
  broker_margin_usd: number;
  subtotal_usd: number;
  total_usd: number;
  total_pln: number;
  total_eur: number;
  fx_usd_pln: number;
  fx_usd_eur: number;
  region: "EAST" | "MID" | "WEST" | "UNKNOWN";
  excise_rate_pct: number;
  notes: string[];
};

// Stan → region transportowy (zgodnie z system promptem)
const EAST_STATES = new Set(["NY", "NJ", "PA", "CT", "MA", "RI", "VT", "NH", "ME", "MD", "DE", "VA", "NC", "SC", "GA", "FL"]);
const MID_STATES = new Set(["OH", "MI", "IN", "IL", "WI", "MN", "IA", "MO", "KY", "TN", "AL", "MS", "LA", "AR"]);
const WEST_STATES = new Set(["CA", "OR", "WA", "NV", "AZ", "UT", "CO", "NM", "TX"]);

export function classifyRegion(state?: string | null): CostBreakdown["region"] {
  if (!state) return "UNKNOWN";
  const s = state.toUpperCase().trim();
  if (EAST_STATES.has(s)) return "EAST";
  if (MID_STATES.has(s)) return "MID";
  if (WEST_STATES.has(s)) return "WEST";
  return "UNKNOWN";
}

// Średnie koszty transportu USA→PL (port-port + transport lądowy w USA)
const TRANSPORT_USD: Record<CostBreakdown["region"], number> = {
  EAST: 1500,
  MID: 1700,
  WEST: 2000,
  UNKNOWN: 1800,
};

const PORT_FEES_USD = 350; // opłaty portowe + dokumenty + transport PL
const HOMOLOGATION_USD = 500; // homologacja + tłumaczenia + rejestracja

// Akcyza w PL:
// - 3.1% jeśli pojemność silnika ≤ 2000 cm³
// - 18.6% jeśli > 2000 cm³
// - elektryki: 0%
// - hybrydy plug-in do 2000cm³: 0%, > 2000: 9.3% (uproszczenie)
function exciseRatePct(engine_cc?: number | null, fuel?: FuelType): number {
  if (fuel === "electric") return 0;
  const cc = engine_cc ?? 2000;
  if (fuel === "hybrid" && cc <= 2000) return 0;
  if (fuel === "hybrid") return 9.3;
  return cc > 2000 ? 18.6 : 3.1;
}

export function calculateCost(input: CostInputs, fx: { usd_pln: number; usd_eur: number }): CostBreakdown {
  const notes: string[] = [];
  const region = classifyRegion(input.state);
  const transport = input.transport_override_usd ?? TRANSPORT_USD[region];
  if (input.transport_override_usd != null) notes.push(`Transport: override ${input.transport_override_usd} USD`);
  else notes.push(`Transport ${region}: ${transport} USD (średnia)`);

  const repair = Math.max(0, input.estimated_repair_usd ?? 0);
  const carPrice = Math.max(0, input.car_price_usd);

  // Cło 10% liczone od (cena auta + transport) — uproszczenie zgodne z praktyką
  const dutyBase = carPrice + transport;
  const customs = dutyBase * 0.1;

  // Akcyza od (cena + transport + cło)
  const excisePct = exciseRatePct(input.engine_cc, input.fuel);
  const exciseBase = carPrice + transport + customs;
  const excise = exciseBase * (excisePct / 100);
  notes.push(`Akcyza ${excisePct}% (silnik: ${input.engine_cc ?? "?"} cm³, paliwo: ${input.fuel ?? "?"})`);

  // VAT 23% od (cena + transport + cło + akcyza)
  const vatBase = carPrice + transport + customs + excise;
  const vat = vatBase * 0.23;

  const margin_pct = input.broker_margin_pct ?? 8;
  const subtotalBeforeMargin = carPrice + repair + transport + PORT_FEES_USD + customs + excise + vat + HOMOLOGATION_USD;
  const margin = subtotalBeforeMargin * (margin_pct / 100);
  notes.push(`Marża brokera ${margin_pct}%`);

  const total = subtotalBeforeMargin + margin;

  const buffer = (input.exchange_rate_buffer_pct ?? 3) / 100;
  const usd_pln = fx.usd_pln * (1 + buffer);
  const usd_eur = fx.usd_eur * (1 + buffer);
  notes.push(`Bufor kursowy +${(input.exchange_rate_buffer_pct ?? 3)}%`);

  return {
    car_price_usd: carPrice,
    repair_usd: repair,
    transport_usa_to_pl_usd: transport,
    port_fees_usd: PORT_FEES_USD,
    customs_duty_usd: Math.round(customs),
    excise_tax_usd: Math.round(excise),
    vat_usd: Math.round(vat),
    homologation_usd: HOMOLOGATION_USD,
    broker_margin_usd: Math.round(margin),
    subtotal_usd: Math.round(subtotalBeforeMargin),
    total_usd: Math.round(total),
    total_pln: Math.round(total * usd_pln),
    total_eur: Math.round(total * usd_eur),
    fx_usd_pln: Number(usd_pln.toFixed(4)),
    fx_usd_eur: Number(usd_eur.toFixed(4)),
    region,
    excise_rate_pct: excisePct,
    notes,
  };
}

// Lista stanów do dropdown'u
export const US_STATES: { code: string; name: string; region: CostBreakdown["region"] }[] = [
  ...Array.from(EAST_STATES).map((c) => ({ code: c, name: c, region: "EAST" as const })),
  ...Array.from(MID_STATES).map((c) => ({ code: c, name: c, region: "MID" as const })),
  ...Array.from(WEST_STATES).map((c) => ({ code: c, name: c, region: "WEST" as const })),
].sort((a, b) => a.code.localeCompare(b.code));
