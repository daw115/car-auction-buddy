import { z } from "zod";

/**
 * Schema kryteriów wyszukiwania wysyłanych do scrapera / analizy AI.
 *
 * UWAGA: Zod domyślnie strip-uje nieznane pola. `searched_by` MUSI być tu
 * zadeklarowane, inaczej zostanie cicho wycięte i do backendu poleci null.
 */
export const criteriaSchema = z.object({
  make: z.string().min(1).max(80),
  model: z.string().max(80).nullable().optional(),
  year_from: z.number().int().min(1900).max(2100).nullable().optional(),
  year_to: z.number().int().min(1900).max(2100).nullable().optional(),
  budget_usd: z.number().min(0).max(1_000_000).nullable().optional(),
  max_odometer_mi: z.number().int().min(0).max(1_000_000).nullable().optional(),
  fuel_type: z.enum(["Gas", "Hybrid", "Diesel", "Electric"]).nullable().optional(),
  excluded_damage_types: z.array(z.string().max(40)).max(20).optional(),
  max_results: z.number().int().min(1).max(100).optional(),
  sources: z.array(z.string().max(20)).max(5).optional(),
  // Kto uruchomił wyszukiwanie (Dawid/Janek/Iga/Monte z PasswordGate).
  searched_by: z.string().max(40).nullable().optional(),
});

export type Criteria = z.infer<typeof criteriaSchema>;

export const KNOWN_CRITERIA_KEYS = [
  "make", "model", "year_from", "year_to", "budget_usd", "max_odometer_mi",
  "fuel_type", "excluded_damage_types", "max_results", "sources", "searched_by",
] as const;

/**
 * Parsuje kryteria z czytelnym komunikatem błędu i wykrywa utratę pól.
 * - Rzuca błąd, gdy walidacja Zod nie przeszła (z listą pól i powodami).
 * - Rzuca błąd, gdy pole było w surowym inpucie ale zostało wycięte/zniekształcone
 *   przez walidację (np. searched_by zbyt długie, zły typ, nieznane pole).
 *
 * @param onUnknownKeys opcjonalny callback wołany z listą nieznanych pól (do logowania).
 */
export function parseCriteria(
  raw: unknown,
  onUnknownKeys?: (keys: string[]) => void,
): Criteria {
  if (!raw || typeof raw !== "object") {
    throw new Error(`Walidacja kryteriów: oczekiwano obiektu, otrzymano ${typeof raw}.`);
  }
  const rawObj = raw as Record<string, unknown>;
  const rawKeys = Object.keys(rawObj);
  const unknownKeys = rawKeys.filter((k) => !(KNOWN_CRITERIA_KEYS as readonly string[]).includes(k));

  let parsed: Criteria;
  try {
    parsed = criteriaSchema.parse(raw);
  } catch (e) {
    if (e instanceof z.ZodError) {
      const issues = e.issues
        .map((i) => `• ${i.path.join(".") || "(root)"} — ${i.message}`)
        .join("\n");
      throw new Error(`Walidacja kryteriów wyszukiwania nie powiodła się:\n${issues}`);
    }
    throw e;
  }

  // Wykrywanie "cichych strat" — pole z wartością w raw, brak w wyniku.
  const lost: Array<{ key: string; raw: unknown }> = [];
  for (const k of KNOWN_CRITERIA_KEYS) {
    const rv = rawObj[k];
    const pv = (parsed as Record<string, unknown>)[k];
    const rawHasValue = rv != null && rv !== "";
    const parsedMissing = pv == null || pv === "";
    if (rawHasValue && parsedMissing) {
      lost.push({ key: k, raw: rv });
    }
  }
  if (lost.length > 0) {
    const detail = lost.map((l) => `${l.key} (typ: ${typeof l.raw})`).join(", ");
    throw new Error(
      `Walidacja kryteriów: utracono pola po walidacji: [${detail}]. ` +
      `Sprawdź czy UI przesyła wartości w poprawnym typie/zakresie.`,
    );
  }

  if (unknownKeys.length > 0 && onUnknownKeys) {
    onUnknownKeys(unknownKeys);
  }

  return parsed;
}
