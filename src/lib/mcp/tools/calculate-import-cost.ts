import { defineTool } from "@lovable.dev/mcp-js";
import { z } from "zod";
import { calculateCost, classifyRegion, type FuelType } from "@/lib/cost-calculator";

const FuelEnum = z.enum(["gasoline", "diesel", "hybrid", "electric", "lpg", "other"]);

export default defineTool({
  name: "calculate_import_cost",
  title: "Kalkulator kosztu importu auta USA→PL",
  description:
    "Deterministycznie liczy szacunkowy całkowity koszt importu auta z aukcji w USA do Polski (transport, cło, akcyza, VAT, homologacja, marża brokera). Zwraca rozbicie w USD, PLN i EUR. Brak dostępu do prywatnych danych aplikacji — czysta kalkulacja.",
  inputSchema: {
    car_price_usd: z.number().describe("Cena auta w USD (kwota zakupu z aukcji)."),
    estimated_repair_usd: z.number().optional().describe("Szacunkowy koszt naprawy w USD."),
    state: z
      .string()
      .optional()
      .describe("Dwuliterowy kod stanu USA (np. 'NY', 'CA'), używany do doboru stawki transportu."),
    engine_cc: z.number().optional().describe("Pojemność silnika w cm³ (decyduje o stawce akcyzy)."),
    fuel: FuelEnum.optional().describe("Typ paliwa; wpływa na akcyzę (electric=0%, hybrid<=2000cc=0%)."),
    weight_kg: z.number().optional().describe("Masa auta w kg (informacyjnie)."),
    broker_margin_pct: z.number().optional().describe("Marża brokera w %; domyślnie 8."),
    exchange_rate_buffer_pct: z
      .number()
      .optional()
      .describe("Bufor na wahania kursu w %; domyślnie 3."),
    transport_override_usd: z
      .number()
      .optional()
      .describe("Nadpisanie kosztu transportu USA→PL w USD."),
    fx_usd_pln: z.number().describe("Kurs USD→PLN (np. 4.05)."),
    fx_usd_eur: z.number().describe("Kurs USD→EUR (np. 0.92)."),
  },
  annotations: { readOnlyHint: true, idempotentHint: true, openWorldHint: false },
  handler: (input) => {
    const breakdown = calculateCost(
      {
        car_price_usd: input.car_price_usd,
        estimated_repair_usd: input.estimated_repair_usd,
        state: input.state ?? null,
        engine_cc: input.engine_cc ?? null,
        fuel: input.fuel as FuelType | undefined,
        weight_kg: input.weight_kg ?? null,
        broker_margin_pct: input.broker_margin_pct,
        exchange_rate_buffer_pct: input.exchange_rate_buffer_pct,
        transport_override_usd: input.transport_override_usd ?? null,
      },
      { usd_pln: input.fx_usd_pln, usd_eur: input.fx_usd_eur },
    );
    return {
      content: [{ type: "text", text: JSON.stringify(breakdown, null, 2) }],
      structuredContent: breakdown as unknown as Record<string, unknown>,
    };
  },
});
