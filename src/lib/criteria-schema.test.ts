import { describe, it, expect, vi } from "vitest";
import { parseCriteria, criteriaSchema } from "./criteria-schema";

describe("criteriaSchema / parseCriteria", () => {
  describe("searched_by — krytyczne dla atrybucji wyszukiwań", () => {
    it("zachowuje searched_by przy poprawnej wartości string", () => {
      const result = parseCriteria({ make: "BMW", searched_by: "Dawid" });
      expect(result.searched_by).toBe("Dawid");
    });

    it.each(["Dawid", "Janek", "Iga", "Monte"])(
      "zachowuje searched_by = %s (wszyscy użytkownicy PasswordGate)",
      (user) => {
        const result = parseCriteria({ make: "BMW", searched_by: user });
        expect(result.searched_by).toBe(user);
      },
    );

    it("zachowuje searched_by w pełnym payloadzie z scrapera", () => {
      const raw = {
        make: "Audi",
        model: "A4",
        year_from: 2018,
        year_to: 2022,
        budget_usd: 25000,
        max_odometer_mi: 80000,
        fuel_type: "Gas" as const,
        excluded_damage_types: ["FLOOD"],
        max_results: 50,
        sources: ["copart"],
        searched_by: "Iga",
      };
      const result = parseCriteria(raw);
      expect(result.searched_by).toBe("Iga");
      expect(result.make).toBe("Audi");
      expect(result.budget_usd).toBe(25000);
    });

    it("akceptuje searched_by = null (jawnie nieprzypisane)", () => {
      const result = parseCriteria({ make: "BMW", searched_by: null });
      expect(result.searched_by).toBeNull();
    });

    it("akceptuje brak searched_by (pole opcjonalne)", () => {
      const result = parseCriteria({ make: "BMW" });
      expect(result.searched_by).toBeUndefined();
    });

    it("rzuca błąd, gdy searched_by przekracza 40 znaków (nie strip-uje cicho)", () => {
      const tooLong = "x".repeat(41);
      expect(() => parseCriteria({ make: "BMW", searched_by: tooLong })).toThrow(
        /Walidacja kryteriów wyszukiwania nie powiodła się[\s\S]*searched_by/,
      );
    });

    it("rzuca błąd, gdy searched_by ma zły typ (number zamiast string)", () => {
      expect(() => parseCriteria({ make: "BMW", searched_by: 42 })).toThrow(
        /Walidacja kryteriów wyszukiwania nie powiodła się[\s\S]*searched_by/,
      );
    });

    it("schema NIE strip-uje searched_by bez błędu (regresja: cicha utrata pola)", () => {
      // Test bezpośrednio na czystym Zod: gdyby ktoś usunął `searched_by` ze
      // schematu, ten test by padł — Zod cicho wyciąłby pole i poszłoby null
      // do backendu (oryginalny bug).
      const parsed = criteriaSchema.parse({ make: "BMW", searched_by: "Dawid" });
      expect(parsed).toHaveProperty("searched_by", "Dawid");
    });
  });

  describe("wykrywanie utraty pól", () => {
    it("nie zgłasza utraty dla searched_by gdy wartość poprawna", () => {
      expect(() => parseCriteria({ make: "BMW", searched_by: "Dawid" })).not.toThrow();
    });
  });

  describe("nieznane pola", () => {
    it("woła callback z nieznanymi kluczami i zachowuje znane", () => {
      const onUnknown = vi.fn();
      const result = parseCriteria(
        { make: "BMW", searched_by: "Dawid", random_field: "x" },
        onUnknown,
      );
      expect(onUnknown).toHaveBeenCalledWith(["random_field"]);
      expect(result.searched_by).toBe("Dawid");
    });

    it("nie woła callbacka, gdy wszystkie pola są znane", () => {
      const onUnknown = vi.fn();
      parseCriteria({ make: "BMW", searched_by: "Dawid" }, onUnknown);
      expect(onUnknown).not.toHaveBeenCalled();
    });
  });

  describe("walidacja podstawowa", () => {
    it("rzuca czytelny błąd dla braku make", () => {
      expect(() => parseCriteria({ searched_by: "Dawid" })).toThrow(
        /Walidacja kryteriów wyszukiwania/,
      );
    });

    it("rzuca błąd dla nie-obiektu", () => {
      expect(() => parseCriteria(null)).toThrow(/oczekiwano obiektu/);
      expect(() => parseCriteria("string")).toThrow(/oczekiwano obiektu/);
    });
  });
});
