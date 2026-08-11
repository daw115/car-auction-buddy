// Ścieżki renderowane POZA bramką hasła — jedyne miejsce, gdzie ten wyjątek się definiuje.
//
// DOPASOWANIE JEST DOKŁADNE, NIE PREFIKSOWE. To nie jest szczegół stylistyczny:
// przy `startsWith` wpisanie tu "/sprawdz" otworzyłoby także "/sprawdz-cokolwiek",
// a pusty string albo "/" otworzyłby cały panel. Zbiór z dokładnym porównaniem nie
// da się rozszerzyć przez przypadek.
//
// Wolno tu wpisać wyłącznie stronę, która nie pokazuje żadnych danych z panelu.
// `/sprawdz-vin` spełnia ten warunek: czyta wyłącznie publiczny endpoint backendu
// (`/api/public/vin-check`), który sam nie wymaga tokena i nie zna żadnego klienta.
export const PUBLIC_ROUTES: ReadonlySet<string> = new Set(["/sprawdz-vin"]);

/** Czy ta ścieżka ma się renderować bez bramki hasła i bez panelu bocznego. */
export function isPublicRoute(pathname: string): boolean {
  // Końcowy ukośnik normalizujemy, bo router bywa wywoływany z obiema wersjami,
  // a "/sprawdz-vin/" i "/sprawdz-vin" to ta sama strona.
  const normalized = pathname.length > 1 ? pathname.replace(/\/+$/, "") : pathname;
  return PUBLIC_ROUTES.has(normalized);
}
