// Lista publicznych ścieżek jest jedynym miejscem, w którym da się przypadkiem
// otworzyć panel na świat. Te testy pilnują, żeby wyjątek został wyjątkiem.

import { describe, expect, it } from "vitest";

import { PUBLIC_ROUTES, isPublicRoute } from "./public-routes";

describe("lista publicznych ścieżek", () => {
  it("wpuszcza checker VIN", () => {
    expect(isPublicRoute("/sprawdz-vin")).toBe(true);
  });

  it("toleruje końcowy ukośnik", () => {
    expect(isPublicRoute("/sprawdz-vin/")).toBe(true);
  });

  it.each([
    "/",
    "/inbox",
    "/clients",
    "/records",
    "/settings",
    "/settings/ai",
    "/database",
    "/dashboard",
    "/watchlist",
    "/calculator",
    "/dev/logs",
  ])("nie wpuszcza ekranu panelu: %s", (sciezka) => {
    expect(isPublicRoute(sciezka)).toBe(false);
  });

  it("dopasowuje DOKŁADNIE, nie prefiksowo", () => {
    // Gdyby dopasowanie szło przez startsWith, każda z tych ścieżek otworzyłaby
    // się bez hasła — a wystarczy, że ktoś doda route zaczynający się tak samo.
    expect(isPublicRoute("/sprawdz-vin-panel")).toBe(false);
    expect(isPublicRoute("/sprawdz-vin/klienci")).toBe(false);
    expect(isPublicRoute("/sprawdz")).toBe(false);
  });

  it("nie wpuszcza pustej ścieżki ani korzenia", () => {
    // Pusty string albo "/" na liście otworzyłby cały panel.
    expect(isPublicRoute("")).toBe(false);
    expect(isPublicRoute("/")).toBe(false);
  });

  it("lista jest krótka i świadoma", () => {
    // Nie jest to test stylu. Każda kolejna pozycja to kolejna strona bez hasła,
    // więc dopisanie czegokolwiek ma wymagać zmiany tego testu i chwili namysłu.
    expect([...PUBLIC_ROUTES]).toEqual(["/sprawdz-vin"]);
  });

  it("żadna publiczna ścieżka nie jest korzeniem ani pusta", () => {
    for (const sciezka of PUBLIC_ROUTES) {
      expect(sciezka.startsWith("/")).toBe(true);
      expect(sciezka.length).toBeGreaterThan(1);
    }
  });
});
