// Kalkulator importu nie zna prawa i nie powinien.
//
// Od 1 lipca 2026 cło zależy od kraju montażu: auto złożone w USA wchodzi na 0%,
// reszta na 10%, a rozstrzyga pierwszy znak VIN-u. Ten plik miał tę stawkę wpisaną
// na sztywno, więc brokerowi wyceniał każde auto z cłem — na egzemplarzu za 15 tys.
// dolarów to ponad dziewięć tysięcy złotych za dużo. Stawki przychodzą teraz
// z backendu (`pricing/tariff.py`), a testy pilnują obu kierunków tej zmiany.

import { describe, expect, it } from "vitest";

import { calculateCost, type CostInputs } from "@/lib/cost-calculator";

const FX = { usd_pln: 4.0, usd_eur: 0.92 };
const AUTO: CostInputs = {
  car_price_usd: 15_000,
  estimated_repair_usd: 0,
  state: "NJ",
  engine_cc: 2000,
  fuel: "gasoline",
};

describe("stawki podatkowe", () => {
  it("bez VIN-u liczy drożej, bo zaniżona wycena wraca do klienta jako dopłata", () => {
    const wynik = calculateCost(AUTO, FX);
    expect(wynik.customs_duty_usd).toBeGreaterThan(0);
    expect(wynik.notes.join(" ")).toContain("Zdekoduj VIN");
  });

  it("bierze stawkę z backendu, gdy ją dostanie", () => {
    const wynik = calculateCost({ ...AUTO, duty_rate_pct: 0, excise_rate_pct: 3.1 }, FX);
    expect(wynik.customs_duty_usd).toBe(0);
    expect(wynik.excise_rate_pct).toBe(3.1);
  });

  it("różnica między 0% a 10% jest tym, co broker mógłby przepłacić w wycenie", () => {
    const zCłem = calculateCost(AUTO, FX);
    const bezCła = calculateCost({ ...AUTO, duty_rate_pct: 0, excise_rate_pct: 3.1 }, FX);
    expect(zCłem.total_pln - bezCła.total_pln).toBeGreaterThan(5_000);
  });

  it("stawka akcyzy z backendu wygrywa z lokalną tabelą", () => {
    // Lokalna tabela nie zna preferencji dla hybryd do 3500 cm³ ani interpretacji
    // dla miękkich hybryd — dlatego ma ustępować, a nie „poprawiać" backend.
    const lokalna = calculateCost({ ...AUTO, engine_cc: 3000, fuel: "hybrid" }, FX);
    const zBackendu = calculateCost(
      { ...AUTO, engine_cc: 3000, fuel: "hybrid", excise_rate_pct: 1.55 },
      FX,
    );
    expect(lokalna.excise_rate_pct).not.toBe(1.55);
    expect(zBackendu.excise_rate_pct).toBe(1.55);
  });
});
