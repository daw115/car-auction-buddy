// Link do WhatsAppa musi nieść treść, którą broker widzi TERAZ.
//
// Pole w oknie „Wiadomość do klienta" jest edytowalne, a przycisk prowadził do
// adresu zbudowanego raz, przy generowaniu. Broker poprawiał kwotę albo zdanie,
// klikał „Otwórz WhatsApp" i wysyłał klientowi wersję SPRZED poprawki — nie
// widząc różnicy, bo w oknie miał przed oczami swój poprawiony tekst.

import { describe, expect, it } from "vitest";

/** Ta sama logika co w komponencie: podmieniamy sam parametr `text`, resztę
 *  adresu (w tym znormalizowany numer) zostawiamy backendowi. */
function linkZTrescia(waMeUrl: string | null, text: string): string | null {
  if (!waMeUrl || !text) return waMeUrl;
  try {
    const adres = new URL(waMeUrl);
    adres.searchParams.set("text", text);
    return adres.toString();
  } catch {
    return waMeUrl;
  }
}

describe("link do WhatsAppa", () => {
  const bazowy = "https://wa.me/48600100200?text=Stara%20tre%C5%9B%C4%87";

  it("niesie poprawioną treść, nie tę sprzed edycji", () => {
    const link = linkZTrescia(bazowy, "Poprawiona treść, 95 000 zł");
    expect(decodeURIComponent(new URL(link!).searchParams.get("text")!)).toBe(
      "Poprawiona treść, 95 000 zł",
    );
  });

  it("nie rusza numeru — normalizację zna backend", () => {
    expect(new URL(linkZTrescia(bazowy, "cokolwiek")!).pathname).toBe("/48600100200");
  });

  it("zostawia adres bez zmian, gdy nie ma czego wysłać", () => {
    expect(linkZTrescia(bazowy, "")).toBe(bazowy);
    expect(linkZTrescia(null, "treść")).toBeNull();
  });

  it("przy niepoprawnym adresie oddaje oryginał zamiast wywalać okno", () => {
    expect(linkZTrescia("to nie jest url", "treść")).toBe("to nie jest url");
  });
});
