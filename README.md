# Car Auction Buddy

Aplikacja webowa do scrapowania, analizy i raportowania ofert pojazdów z aukcji (Copart / IAAI).

Szczegółowy przewodnik dla kontrybutorów → [`CLAUDE.md`](CLAUDE.md).

---

## Server Functions — architektura RPC

### Dlaczego `src/functions/` może importować z `@/server/*`?

Projekt rozdziela kod serwerowy na dwie warstwy:

| Warstwa | Katalog | Może importować `@/server/*`? | Dostępna z klienta? |
|---------|---------|-------------------------------|---------------------|
| **Helpery server-only** | `src/server/*.server.ts` | ✅ | ❌ — Vite blokuje import w bundlu klienta |
| **RPC wrappery** | `src/functions/*.functions.ts` | ✅ | ✅ — `createServerFn` zamienia ciało na stub fetch |
| **Kod klienta** | `src/components/`, `src/routes/`, `src/hooks/`, `src/lib/` | ❌ — ESLint + CI blokują | ✅ |

Pliki `*.functions.ts` są **jedynym mostem** między klientem a serwerem. TanStack Start w czasie builda:

1. Wyodrębnia ciało `.handler()` do osobnego chunk'a serwerowego.
2. W bundlu klienta zastępuje je stubem, który robi `fetch()` do serwera.

Dzięki temu `src/functions/` bezpiecznie importuje helpery z `@/server/*.server.ts`, a komponenty importują wyłącznie z `src/functions/`.

### Jak poprawnie utworzyć nową funkcję RPC

1. **Helper server-only** — logika, dostęp do DB, sekrety:

   ```ts
   // src/server/orders.server.ts
   import { supabaseAdmin } from "@/integrations/supabase/client.server";

   export async function fetchOrders(clientId: string) {
     const { data, error } = await supabaseAdmin
       .from("orders")
       .select("*")
       .eq("client_id", clientId);
     if (error) throw new Error(error.message);
     return data ?? [];
   }
   ```

2. **RPC wrapper** — cienka warstwa z walidacją:

   ```ts
   // src/functions/orders.functions.ts
   import { createServerFn } from "@tanstack/react-start";
   import { z } from "zod";
   import { fetchOrders } from "@/server/orders.server";

   export const listOrders = createServerFn({ method: "GET" })
     .inputValidator(z.object({ clientId: z.string().uuid() }).parse)
     .handler(async ({ data }) => fetchOrders(data.clientId));
   ```

3. **Komponent** — importuje tylko z `src/functions/`:

   ```tsx
   // src/routes/orders.tsx
   import { listOrders } from "@/functions/orders.functions";

   export const Route = createFileRoute("/orders")({
     loader: () => listOrders({ data: { clientId: "..." } }),
     component: OrdersPage,
   });
   ```

### Zasady

- **Nigdy** nie importuj `@/server/*` w komponentach, hookach ani `src/lib/` — ESLint (`no-restricted-imports`) i CI (`scripts/check-server-imports.mjs`) to zablokują.
- Łańcuch `createServerFn().inputValidator().handler()` musi być ciągły — nie przerywaj go.
- `process.env.*` czytaj **wewnątrz** `.handler()`, nie na poziomie modułu.
- Nie definiuj helperów w `*.functions.ts` — przenieś je do `*.server.ts` (unikasz problemów z `tss-serverfn-split`).
