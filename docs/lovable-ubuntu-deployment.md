# Deployment: Lovable BFF ↔ Cloudflare Access ↔ Ubuntu FastAPI

## Architektura

```
Browser (użytkownik operatora)
   │
   │ HTTPS + HttpOnly session cookie (SITE_SESSION_SECRET)
   ▼
Lovable BFF (TanStack Start server functions + server routes)
   │
   │ HTTPS
   │ Headers:
   │   Authorization: Bearer <UBUNTU_API_BEARER_TOKEN>
   │   CF-Access-Client-Id: <CF_ACCESS_CLIENT_ID>
   │   CF-Access-Client-Secret: <CF_ACCESS_CLIENT_SECRET>
   │   X-Request-Id: <uuid>
   ▼
Cloudflare Access (Tunnel + Service Token gate)
   │
   ▼
FastAPI na Ubuntu/WSL2
   ⚑ nasłuchuje wyłącznie na 127.0.0.1:8000
   ⚑ nie ma publicznego host:port
   │
   ▼
Lokalne pliki SQLite w ~/usacar/usa-car-finder/data/
```

## Zasady bezpieczeństwa

1. **Port 8000 nigdy nie jest publiczny.** FastAPI bindowany wyłącznie do `127.0.0.1:8000`. Publiczna dostępność wyłącznie przez `cloudflared` z wymuszonym Access.
2. **CF Access service token i UBUNTU_API_BEARER_TOKEN są server-only.** Nie mogą trafić do bundla klienta, do `VITE_*`, do logów, do treści błędów zwracanych do przeglądarki.
3. **Browser nigdy nie zna `UBUNTU_API_BASE_URL`** ani żadnych tokenów. Cała komunikacja z Ubuntu przechodzi przez server functions Lovable.
4. **Sesja użytkownika GUI** trzymana jest w signed HttpOnly cookie (`car_auction_session`), `SameSite=Lax`, `Secure` w produkcji. Brak danych auth w `localStorage`.
5. **Cloudflare Access wymusza service token** — request bez `CF-Access-Client-Id/Secret` dostaje 403 na krawędzi Cloudflare, zanim dotknie tunelu.

## Zmienne środowiskowe (nazwy, bez wartości)

### Nowe (Ubuntu API, server-only)

| Nazwa                     | Wymagane | Opis                                                                                |
| ------------------------- | -------- | ----------------------------------------------------------------------------------- |
| `UBUNTU_API_BASE_URL`     | tak      | Kanoniczny HTTPS URL do FastAPI za CF Access (bez slash na końcu, bez credentials). |
| `UBUNTU_API_BEARER_TOKEN` | tak      | Bearer token wystawiany przez backend Ubuntu.                                       |
| `CF_ACCESS_CLIENT_ID`     | tak      | Service token Cloudflare Access — client id.                                        |
| `CF_ACCESS_CLIENT_SECRET` | tak      | Service token Cloudflare Access — client secret.                                    |

### Sesja PasswordGate (już istnieją)

| Nazwa                      | Wymagane | Opis                                             |
| -------------------------- | -------- | ------------------------------------------------ |
| `SITE_SESSION_SECRET`      | tak      | HMAC secret do podpisu cookie sesji (≥32 znaki). |
| `SITE_SESSION_TTL_SECONDS` | nie      | TTL sesji (default 3600, zakres 300–86400).      |
| `SITE_MASTER_PASSWORD`     | tak      | Hasło nadrzędne do zarządzania profilami.        |

### Legacy (do wygaszenia po migracji ekranów)

| Nazwa               | Status | Notatka                                                                                  |
| ------------------- | ------ | ---------------------------------------------------------------------------------------- |
| `API_BASE_URL`      | legacy | Obecny proxy do produkcyjnego FastAPI (bez CF Access). Zastąpi go `UBUNTU_API_BASE_URL`. |
| `API_BEARER_TOKEN`  | legacy | Bearer do `API_BASE_URL`. Zastąpi go `UBUNTU_API_BEARER_TOKEN`.                          |
| `SCRAPER_BASE_URL`  | legacy | Legacy zewnętrzny scraper (nie Ubuntu).                                                  |
| `SCRAPER_API_TOKEN` | legacy | Token do zewnętrznego scrapera.                                                          |

> Zmiennych legacy **nie usuwamy** dopóki żaden ekran nie zostanie w pełni przełączony na Ubuntu API. Współistnienie jest zamierzone.

## Cloudflare Access — service token

1. W Cloudflare Zero Trust utwórz **Service Token** (nazwa np. `lovable-bff-prod`).
2. Skopiuj `Client ID` i `Client Secret` — wartości pojawiają się tylko raz.
3. W Access → Applications utwórz aplikację dla hostname tunelu Ubuntu i dodaj **Include: Service Auth = lovable-bff-prod**.
4. Wartości `Client ID` / `Client Secret` zapisz w Lovable jako sekrety `CF_ACCESS_CLIENT_ID` / `CF_ACCESS_CLIENT_SECRET`. **Nie** commituj ich, nie umieszczaj w `.env.example`, nie loguj.

## Healthcheck

BFF wystawia `/api/health` z sekcją `services.ubuntuApi`:

```json
{
  "ok": true,
  "services": {
    "database": "ok",
    "scraper": "unconfigured",
    "ai": "ok",
    "ubuntuApi": {
      "status": "ok",
      "latencyMs": 87,
      "requestId": "d3a…"
    }
  }
}
```

Reguły:

- Status `unconfigured` (brak envów) **nie** wymusza HTTP 503 na całym `/api/health`, dopóki żaden ekran produkcyjny nie zależy od Ubuntu API.
- Status `down` przy skonfigurowanym Ubuntu API również nie wymusza 503 w tej fazie migracji — pojawi się jako degradacja w diagnostyce.

## Rollback

1. **Rollback konfiguracyjny**: usunięcie `UBUNTU_API_BASE_URL` (i innych `UBUNTU_*` / `CF_ACCESS_*`) przełącza klient w stan `unconfigured`. Ekrany produkcyjne dalej korzystają z legacy (Supabase + `API_BASE_URL`), bez wpływu na użytkownika.
2. **Rollback ekranu**: jeśli ekran został przełączony na Ubuntu API i pojawił się regres, przywracamy commit ekranu — legacy code path pozostaje w repo do zakończenia migracji.
3. **Awaryjny rollback tokenów**: patrz sekcja „Rotacja tokenów".

## Rotacja tokenów

### `UBUNTU_API_BEARER_TOKEN`

1. Wygeneruj nowy bearer na Ubuntu (procedura backendu).
2. Zapisz w Lovable Cloud secrets → `UBUNTU_API_BEARER_TOKEN` (przez UI).
3. Poczekaj na deploy Workera z nową wartością (weryfikacja przez `/api/health` → `ubuntuApi.status = "ok"`).
4. Unieważnij stary bearer na Ubuntu.

### CF Access service token (`CF_ACCESS_CLIENT_ID` + `CF_ACCESS_CLIENT_SECRET`)

1. W Cloudflare utwórz nowy service token i dodaj go do polityki Access aplikacji (obok starego).
2. Zaktualizuj oba sekrety w Lovable.
3. Zweryfikuj `/api/health`.
4. Usuń stary service token z polityki Access i skasuj go w Cloudflare.

### `SITE_SESSION_SECRET`

1. Wygeneruj nową wartość (≥32 znaki: `openssl rand -hex 32`).
2. Zapisz w Lovable Cloud secrets.
3. Uwaga: rotacja unieważnia wszystkie aktywne sesje PasswordGate — użytkownicy zalogują się ponownie.

## Weryfikacja po deployu

- `GET /api/health` → status 200, `ok: true`, sekcja `ubuntuApi` obecna.
- `GET /api/diagnostics` (za sesją PasswordGate) → wszystkie envy Ubuntu API oznaczone jako obecne.
- Zewnętrznie: `curl https://<tunnel-host> ` bez CF-Access-\* → oczekiwane 403 z krawędzi Cloudflare (dowód, że backend nie jest bezpośrednio dostępny).
- Na Ubuntu: `ss -tlnp | grep :8000` → wyłącznie `127.0.0.1:8000`.

## Co pozostaje po stronie backendu Ubuntu

- Implementacja/potwierdzenie wszystkich endpointów z `docs/ubuntu-api-contract.md`.
- Utrzymanie kontraktu formatu błędu (`{ error: { code, message, request_id } }`).
- Rate limit na `/auth/*`.
- Publikacja OpenAPI/JSON Schema dla request/response, żeby Lovable mógł uzupełnić walidatory `validate` w server functions.
