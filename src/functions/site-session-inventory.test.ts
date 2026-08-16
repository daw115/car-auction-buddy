import { readdirSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const PRIVATE_FUNCTION_MODULES = [
  "ai-providers.functions.ts",
  "backend.functions.ts",
  "clients.functions.ts",
  "default-criteria.functions.ts",
  "external.functions.ts",
  "intake.functions.ts",
  "pipeline-filters.functions.ts",
  "sales.functions.ts",
  "watches.functions.ts",
  "watchlist.functions.ts",
];

// Pusto — i tak ma zostać. Publiczny checker VIN był tu do sierpnia 2026 jako
// `vin-check.functions.ts`; przeniósł się na własne trasy `/api/public/vin-check`
// i `/api/public/lead`, bo przed panelem stanął Cloudflare Access, a wyjątek robi
// się po ścieżce. Wszystkie server functions dzielą adres `/_serverFn/`, więc
// otwarcie go dla checkera otworzyłoby z powrotem także logowanie do panelu.
// Reguła „publiczne sięga tylko po /api/public/" przeniosła się niżej, do testu
// tras publicznych — nie zniknęła.
const PUBLIC_FUNCTION_MODULES: string[] = [];

// Moduły bez ani jednej funkcji serwerowej — same middleware i helpery.
const INFRASTRUCTURE_MODULES = [
  "dev-logging-middleware.functions.ts",
  "site-session-middleware.functions.ts",
  "site-auth.functions.ts", // ma własne, ostrzejsze testy niżej
];

describe("każdy moduł funkcji serwerowych jest sklasyfikowany", () => {
  // Inwentarz na ręcznej liście nie zauważa nowego pliku — a nowy plik bez middleware
  // to jest dokładnie ta pomyłka, której ten test ma pilnować. Zdarzyła się:
  // `vin-check.functions.ts` i `clients.functions.ts` nie były na żadnej liście
  // i przechodziły niesprawdzone. Dlatego czytamy katalog, a nie listę.
  it("nie ma modułu poza listami", () => {
    const wszystkie = readdirSync(resolve("src/functions"))
      .filter((f) => f.endsWith(".functions.ts"))
      .sort();
    const sklasyfikowane = new Set([
      ...PRIVATE_FUNCTION_MODULES,
      ...PUBLIC_FUNCTION_MODULES,
      ...INFRASTRUCTURE_MODULES,
    ]);
    const nieznane = wszystkie.filter((f) => !sklasyfikowane.has(f));
    expect(
      nieznane,
      `Nowy moduł funkcji serwerowych bez klasyfikacji: ${nieznane.join(", ")}. ` +
        "Dopisz go do PRIVATE (z siteSessionMiddleware), PUBLIC (z uzasadnieniem) " +
        "albo INFRASTRUCTURE.",
    ).toEqual([]);
  });

  it.each(PUBLIC_FUNCTION_MODULES)("moduł publiczny %s sięga tylko po /api/public/", (filename) => {
    const source = readFileSync(resolve("src/functions", filename), "utf8");
    const sciezki = source.match(/path:\s*["'`]([^"'`]+)/g) ?? [];
    expect(sciezki.length).toBeGreaterThan(0);
    for (const sciezka of sciezki) {
      expect(sciezka).toContain("/api/public/");
    }
  });
});

// Trasy, które Cloudflare Access przepuszcza bez pytania o tożsamość. Każda nowa
// pozycja w katalogu jest tu wykrywana automatycznie — lista pisana ręcznie nie
// zauważyłaby pliku dołożonego obok, a to jest dokładnie ta pomyłka, która kosztuje
// najwięcej: trasa bez logowania sięgająca po dane panelu.
describe("publiczne trasy nie sięgają poza /api/public/ backendu", () => {
  const katalog = resolve("src/routes/api/public");
  // Bez podkatalogu hooks/ — te trasy broni własny sekret w nagłówku i NIE ma ich
  // na liście wyjątków Cloudflare Access, więc z internetu i tak są nieosiągalne.
  // Tutaj chodzi wyłącznie o trasy, które Access przepuszcza anonimowo.
  const publiczne = readdirSync(katalog, { recursive: true, encoding: "utf8" }).filter(
    (f) => f.endsWith(".ts") && !f.includes(".test.") && !f.includes("hooks"),
  );

  it("katalog nie jest pusty", () => {
    expect(publiczne.length).toBeGreaterThan(0);
  });

  it.each(publiczne)("%s woła backend wyłącznie pod /api/public/", (plik) => {
    const source = readFileSync(resolve(katalog, plik), "utf8");
    for (const sciezka of source.match(/path:\s*["'`]([^"'`]+)/g) ?? []) {
      expect(sciezka).toContain("/api/public/");
    }
    // Bramka sesji na trasie publicznej byłaby sprzecznością — ale bramka na dane
    // panelu już nie. Pilnujemy, żeby nikt nie sięgnął stąd po supabaseAdmin.
    expect(source).not.toContain("supabaseAdmin");
  });
});

// Zostaje jedna. /api/records i /api/reports/pdf szły jeszcze prosto do Supabase
// z czasów Lovable — panel od dawna czyta rekordy i raporty z backendu na Ubuntu,
// więc obie trasy usunięto zamiast pilnować ich strażnika.
const PRIVATE_RAW_ROUTES = ["src/routes/api/config.ts"];

describe("site session protection inventory", () => {
  it.each(PRIVATE_FUNCTION_MODULES)("protects every server function in %s", (filename) => {
    const source = readFileSync(resolve("src/functions", filename), "utf8");
    const definitions = source.match(/createServerFn\(\{ method: "(?:GET|POST)" \}\)/g) ?? [];
    const protectedDefinitions =
      source.match(
        // siteSessionMiddleware musi być w tablicy, ale nie musi być sam —
        // telemetria (devRequestLogger) dokłada się obok i nie jest bramką.
        /createServerFn\(\{ method: "(?:GET|POST)" \}\)\s*\.middleware\(\[[^\]]*\bsiteSessionMiddleware\b[^\]]*\]\)/g,
      ) ?? [];
    expect(definitions.length).toBeGreaterThan(0);
    expect(protectedDefinitions).toHaveLength(definitions.length);
  });

  it.each(PRIVATE_RAW_ROUTES)("guards private raw route %s", (filename) => {
    const source = readFileSync(resolve(filename), "utf8");
    expect(source).toContain("siteSessionGuard");
    expect(source).toContain("if (unauthorized) return unauthorized");
  });

  it("keeps only bootstrap authentication server functions public", () => {
    const source = readFileSync(resolve("src/functions/site-auth.functions.ts"), "utf8");
    const exportedFunctions =
      source.match(/export const siteUser(?:HasPassword|Login|SetPassword|Session|Logout)/g) ?? [];
    expect(exportedFunctions).toHaveLength(5);
    expect(source).not.toContain("FALLBACK_MASTER_PASSWORD");
  });

  // These handlers are public by design — they are what an unauthenticated
  // visitor calls to get in. That makes SITE_MASTER_PASSWORD the only thing
  // standing between the internet and the app, so every handler that checks it
  // must also be rate limited and must compare in constant time.
  // siteUserDeletePassword shipped without either and could be brute-forced
  // without ever tripping a counter.
  it("rate limits and constant-time compares every master-password handler", () => {
    const source = readFileSync(resolve("src/functions/site-auth.functions.ts"), "utf8");
    const blocks = source.split(/^export const /m).slice(1);
    const gated = blocks.filter((b) => b.includes("SITE_MASTER_PASSWORD"));

    expect(gated.length).toBeGreaterThan(0);
    for (const block of gated) {
      const name = block.slice(0, block.indexOf(" "));
      expect(block, `${name} must check the lockout before comparing`).toContain(
        "checkLoginRateLimit(",
      );
      expect(block, `${name} must count a wrong master password`).toContain(
        "registerFailedAttempt(",
      );
      expect(block, `${name} must not compare the master password with !==`).not.toMatch(
        /!==\s*expectedMaster/,
      );
    }
  });
});
