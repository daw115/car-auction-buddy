# Self-hosting — dashboard na własnym serwerze Ubuntu (WSL2)

Komplet plików potrzebnych do odtworzenia wdrożenia. Wcześniej nie było
żadnego skryptu — release powstawał ręcznie i nie dało się go powtórzyć.

## Architektura

```
Internet
   │  https://moneybitches.organof.org        ← JEDYNE publiczne wejście
   ▼
cloudflared  (ingress → 127.0.0.1:3000)
   ▼
127.0.0.1:3000   usacar-dashboard.service   (TanStack Start / Nitro node-server)
   │   ├─ PasswordGate (scrypt + sesja HttpOnly)
   │   ├─ 127.0.0.1:3001 → Caddy → PostgREST → Postgres   (Docker)
   │   └─ server functions → http://127.0.0.1:8000
   ▼
127.0.0.1:8000   usacar-api.service  (FastAPI, niedostępny z internetu)
   └─ 127.0.0.1:9222  Chrome CDP (scraper)
```

## Pliki

| Plik                                   | Cel na serwerze                             |
| -------------------------------------- | ------------------------------------------- |
| `usacar-dashboard.service`             | `/etc/systemd/system/`                      |
| `usacar-deploy-dashboard.sh`           | `/usr/local/bin/`                           |
| `usacar-watchdog.sh`                   | `/usr/local/bin/`                           |
| `usacar-backup.{sh,service,timer}`     | `/usr/local/bin/` + `/etc/systemd/system/`  |
| `usacar-db/compose.yaml` + `Caddyfile` | `/opt/usacar-db/`                           |
| `usacar-db/00-roles.sql`               | jednorazowo, przed migracjami               |
| `usacar-db/mint-jwt.py`                | wystawia tokeny zastępujące klucze Supabase |

Konfiguracja: `/etc/usacar/dashboard.env` (`0600 root:root`) oraz
`/opt/usacar-db/.env` (`0600`). Żaden z nich nie jest w repo.

## Postawienie od zera

```bash
# 1. Narzędzia. UWAGA: CPU tego serwera (i5-3210M) NIE ma AVX2 — standardowy
#    bun wysypuje się przez SIGILL. Instalator sam dobiera wariant baseline,
#    ale zweryfikuj, że `bun --version` w ogóle odpowiada.
curl -fsSL https://bun.sh/install | bash -s "bun-v1.2.14" && ~/.bun/bin/bun --version
sudo apt install -y nodejs docker-compose-v2 postgresql-client

# 2. Baza
sudo install -d -o "$USER" /opt/usacar-db && cp usacar-db/* /opt/usacar-db/
cd /opt/usacar-db
umask 077 && { echo "POSTGRES_PASSWORD=$(openssl rand -hex 24)";
               echo "AUTHENTICATOR_PASSWORD=$(openssl rand -hex 24)";
               echo "PGRST_JWT_SECRET=$(openssl rand -hex 32)"; } > .env
docker compose up -d
# role -> migracje (POMIŃ 20260430142325_*, to pg_cron/pg_net; nic ich nie używa)
# -> mint-jwt.py -> wartości do /etc/usacar/dashboard.env

# 3. Dashboard
sudo install -d -o "$USER" /opt/usacar-dashboard/releases
git clone --branch feat/selfhost <repo> /opt/usacar-dashboard/build
sudo install -m 644 usacar-dashboard.service /etc/systemd/system/
sudo install -m 755 usacar-deploy-dashboard.sh usacar-watchdog.sh /usr/local/bin/
sudo systemctl daemon-reload && sudo systemctl enable --now usacar-dashboard
```

## Wdrożenie kolejnej wersji

```bash
usacar-deploy-dashboard.sh feat/selfhost
```

Bramki (build, `tsc`, granica klient/serwer) idą **przed** dotknięciem
`releases/`, a przy nieudanym health-checku symlink `current` wraca na
poprzedni release.

## Backup

`usacar-backup.timer` uruchamia się codziennie o 03:30 (`Persistent=true`, więc
nadrabia, gdy serwer był wyłączony). Zrzut trafia do `/home/dawid/backups/<data>/`,
retencja 14 dni, ~20 MB na przebieg.

Obejmuje wszystko, czego nie da się odtworzyć z gita: bazy SQLite backendu,
`client_searches`, zrzut Postgresa i konfigurację z sekretami. SQLite kopiowany
przez `VACUUM INTO`, nie `cp` — zwykłe kopiowanie żywej bazy potrafi złapać plik
w połowie transakcji.

Retencja czyści stare katalogi **tylko gdy bieżący przebieg się powiódł**,
inaczej seria awarii po cichu zjadłaby wszystkie dobre kopie.

Odtworzenie:

```bash
B=/home/dawid/backups/<data>
zstd -dc $B/client_searches.tar.zst | tar -C /tmp/restore -xf -   # raporty
zstd -dc $B/postgres.sql.zst | psql "postgres://postgres@127.0.0.1:5433/postgres"
cp $B/sqlite/app.db /home/dawid/usacar/usa-car-finder/data/       # przy zatrzymanym usacar-api
```

Sprawdzone realnie: `PRAGMA integrity_check` = ok na każdej bazie, liczby wierszy
zgodne z oryginałem (92 rekordy, 93 joby, 4 ustawienia, 3 wpisy kolejki,
201 lookupów), 1350 plików raportów, 12 tabel w zrzucie Postgresa.

> **Kopia leży na tym samym dysku co dane.** Chroni przed skasowaniem pliku
> i błędem aplikacji, nie przed awarią dysku ani utratą maszyny. Ściągaj
> okresowo poza serwer:
> `scp -r wsl2-cf:/home/dawid/backups/<data> .`

## Pułapki, które kosztowały czas

- **`postgres:18` montuje `/var/lib/postgresql`, nie `/var/lib/postgresql/data`.**
  Stara ścieżka = kontener odmawia startu.
- **Caddy nie jest ozdobnikiem.** `@supabase/supabase-js` twardo skleja
  `${SUPABASE_URL}/rest/v1`, a PostgREST serwuje z korzenia.
- **`service_role` musi mieć `BYPASSRLS`.** Migracja lockdown nakłada
  `FORCE ROW LEVEL SECURITY` bez polityk — bez tego `supabaseAdmin` nic nie
  odczyta ani nie zapisze.
- **`NITRO_HOST=127.0.0.1` jest obowiązkowe.** Domyślnie Nitro słucha na
  wszystkich interfejsach, a maszyna ma też interfejs Tailscale.
- **`UBUNTU_API_*` i `CF_ACCESS_*` muszą zostać puste.** `selectBackendTransport()`
  zwraca `"legacy"` tylko gdy wszystkie cztery są puste; ustawienie jednej to
  fail-closed 500 na każdym wywołaniu backendu.
- **Obie pary — `API_*` i `SCRAPER_*` — muszą wskazywać backend.** Brak drugiej
  cicho wyłącza kolejkę, parser wiadomości klienta i strumień logów SSE.
- **Restart `cloudflared` zrywa SSH**, jeśli łączysz się przez ten sam tunel.
  Wraca po ~10 s.
