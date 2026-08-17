/** Werdykt budżetowy lota — liczony w backendzie, tutaj tylko odczytywany.
 *
 *  Backend dokleja go do `lot.raw_data.unified_score` (scoring/unified.py), więc
 *  jedzie tą samą drogą co reszta lota i nie wymaga osobnego zapytania. Kwoty
 *  są w złotówkach pod drzwi, bo tak klient podaje budżet — cena aukcyjna w USD
 *  nie mówi nic o tym, czy auto się mieści.
 */

export type BudgetVerdict = {
  over: boolean;
  priceUsd: number | null;
  ceilingUsd: number | null;
  landedPln: number | null;
  budgetPln: number | null;
  gapPln: number | null;
  note: string;
};

function num(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function record(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

/** Odczytuje werdykt z lota. Zwraca null, gdy klient nie podał budżetu. */
export function budgetVerdictOf(lot: unknown): BudgetVerdict | null {
  const raw = record(record(lot)?.raw_data);
  const unified = record(raw?.unified_score);
  if (!unified) return null;

  const budget = record(unified.budget);
  if (!budget) {
    // Starsze rekordy nie mają rozbicia, ale flaga wystarczy do wyszarzenia.
    return unified.over_budget === true
      ? {
          over: true,
          priceUsd: null,
          ceilingUsd: null,
          landedPln: null,
          budgetPln: null,
          gapPln: null,
          note: "ponad budżet klienta",
        }
      : null;
  }

  return {
    over: budget.over === true || unified.over_budget === true,
    priceUsd: num(budget.price_usd),
    ceilingUsd: num(budget.ceiling_usd),
    landedPln: num(budget.landed_pln),
    budgetPln: num(budget.budget_pln),
    gapPln: num(budget.gap_pln),
    note: typeof budget.note === "string" ? budget.note : "",
  };
}

export function isOverBudget(lot: unknown): boolean {
  return budgetVerdictOf(lot)?.over === true;
}

/** Etykieta na badge — mówi o ile, a nie tylko że. */
export function overBudgetLabel(verdict: BudgetVerdict): string {
  if (verdict.note) return verdict.note;
  if (verdict.gapPln && verdict.gapPln > 0) {
    return `ponad budżet o ${verdict.gapPln.toLocaleString("pl-PL", { maximumFractionDigits: 0 })} zł`;
  }
  return "ponad budżet";
}

/** Cena pod drzwi do pokazania brokerowi obok ceny aukcyjnej. */
export function landedLabel(verdict: BudgetVerdict | null): string | null {
  if (!verdict?.landedPln) return null;
  return `${verdict.landedPln.toLocaleString("pl-PL", { maximumFractionDigits: 0 })} zł pod drzwi`;
}
