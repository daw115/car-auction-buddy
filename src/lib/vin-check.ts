/** Klient publicznej strony /sprawdz-vin.
 *
 *  Ta strona jako jedyna działa bez logowania, więc jej zapytania muszą chodzić
 *  pod własnym adresem (`/api/public/*`), a nie przez wspólny `/_serverFn/`.
 *  Powód jest po stronie sieci, nie kodu: przed panelem stoi Cloudflare Access,
 *  a wyjątek da się zrobić tylko po ścieżce. Otwarcie całego `/_serverFn/`
 *  wystawiłoby z powrotem na świat wszystkie funkcje panelu — łącznie z logowaniem.
 */

export type VinCheckResult = {
  vin: string;
  assembly_country: string;
  assembled_in_usa: boolean;
  duty_rate_pct: number;
  duty_free: boolean;
  duty_reason: string;
  excise_rate_pct: number;
  excise_reason: string;
  drivetrain: string;
  drivetrain_confident: boolean;
  assumptions: string[];
  usd_rate: number;
  landed_pln?: number;
  landed_if_duty_10_pln?: number;
  saving_pln?: number;
};

export type VinCheckInput = {
  vin: string;
  bid_usd?: number;
  state?: string;
  make?: string;
  model?: string;
  trim?: string;
  settlement?: "private" | "company";
};

export type PublicLeadInput = {
  message?: string;
  name?: string;
  phone?: string;
  email?: string;
  /** Pole-pułapka: człowiek go nie widzi, bot wypełnia wszystko, co znajdzie. */
  website?: string;
};

async function post<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    // Komunikat z serwera jest po polsku i pisany do klienta, nie do nas —
    // pokazujemy go wprost, a na wypadek odpowiedzi bez JSON-a mamy zapasowy.
    const tresc = await response.json().catch(() => null);
    throw new Error(
      (tresc as { error?: string } | null)?.error ??
        "Nie udało się połączyć z serwerem. Spróbuj ponownie za chwilę.",
    );
  }
  return response.json() as Promise<T>;
}

export const sprawdzVin = (dane: VinCheckInput) =>
  post<VinCheckResult>("/api/public/vin-check", dane);

/** Zgłoszenie po pełną kalkulację — dopiero tu klient zostawia kontakt. */
export const zglosLead = (dane: PublicLeadInput) => post<{ ok: boolean }>("/api/public/lead", dane);
