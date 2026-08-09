#!/bin/bash
# Nocny backup USA Car Finder.
#
# Obejmuje wszystko, czego nie da sie odtworzyc z gita:
#   - bazy SQLite backendu (rekordy, joby, ustawienia, kolejka, cache)
#   - katalog client_searches (raporty wygenerowane dla klientow)
#   - Postgres dashboardu (hasla logowania, watchlista, logi operacji)
#   - konfiguracje z sekretami (env, unity systemd, cloudflared)
#
# SQLite kopiowany przez VACUUM INTO, nie cp. Zwykle cp na zywej bazie potrafi
# zlapac plik w polowie transakcji i dac uszkodzona kopie; VACUUM INTO robi
# spojny zrzut bez zatrzymywania aplikacji.
#
# Uruchamiany przez usacar-backup.timer (raz na dobe). Log w journalctl -u usacar-backup.

set -euo pipefail

DEST_ROOT="${USACAR_BACKUP_ROOT:-/home/dawid/backups}"
KEEP_DAYS="${USACAR_BACKUP_KEEP_DAYS:-14}"
DATA_DIR=/home/dawid/usacar/usa-car-finder/data
VENV_PY=/home/dawid/usacar/usa-car-finder/venv/bin/python
DB_ENV=/opt/usacar-db/.env

STAMP="$(date +%Y-%m-%d-%H%M)"
DEST="$DEST_ROOT/$STAMP"

# Backup zawiera sekrety i hashe hasel — nikt poza wlascicielem nie ma tu wstepu.
install -d -m 700 "$DEST_ROOT"
install -d -m 700 "$DEST"
umask 077

fail=0
note() { echo "[backup] $*"; }
warn() { echo "[backup] UWAGA: $*" >&2; fail=1; }

# --- 1. SQLite backendu --------------------------------------------------
install -d -m 700 "$DEST/sqlite"
shopt -s nullglob
for db in "$DATA_DIR"/*.db; do
  name="$(basename "$db")"
  if "$VENV_PY" - "$db" "$DEST/sqlite/$name" <<'PY'
import sqlite3, sys
src, dst = sys.argv[1], sys.argv[2]
con = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
try:
    con.execute("VACUUM INTO ?", (dst,))
finally:
    con.close()
PY
  then
    note "sqlite $name -> $(du -h "$DEST/sqlite/$name" | cut -f1)"
  else
    warn "nie udalo sie skopiowac $name"
  fi
done
shopt -u nullglob

# --- 2. Raporty klientow -------------------------------------------------
if [ -d "$DATA_DIR/client_searches" ]; then
  if tar -C "$DATA_DIR" -cf - client_searches | zstd -q -3 -o "$DEST/client_searches.tar.zst"; then
    note "client_searches -> $(du -h "$DEST/client_searches.tar.zst" | cut -f1)"
  else
    warn "nie udalo sie spakowac client_searches"
  fi
fi

# --- 3. Postgres dashboardu ----------------------------------------------
if [ -r "$DB_ENV" ]; then
  # shellcheck disable=SC1090
  set -a; . "$DB_ENV"; set +a
  if PGPASSWORD="$POSTGRES_PASSWORD" pg_dump \
        --no-owner --no-privileges \
        "postgres://postgres@127.0.0.1:5433/postgres" \
      | zstd -q -3 -o "$DEST/postgres.sql.zst"; then
    note "postgres -> $(du -h "$DEST/postgres.sql.zst" | cut -f1)"
  else
    warn "pg_dump nieudany"
  fi
else
  warn "brak $DB_ENV — pomijam Postgres"
fi

# --- 4. Konfiguracja z sekretami -----------------------------------------
tar -cf - --ignore-failed-read \
    /etc/usacar/dashboard.env \
    /home/dawid/usacar/usa-car-finder/.env \
    /opt/usacar-db/.env \
    /opt/usacar-db/compose.yaml \
    /opt/usacar-db/Caddyfile \
    /etc/systemd/system/usacar-dashboard.service \
    /etc/systemd/system/usacar-api.service \
    /etc/systemd/system/usacar-api.service.d \
    /etc/cloudflared/config.yml \
    2>/dev/null | zstd -q -3 -o "$DEST/config.tar.zst" \
  && note "config -> $(du -h "$DEST/config.tar.zst" | cut -f1)" \
  || warn "backup konfiguracji nieudany"

chmod -R go-rwx "$DEST"

# --- 5. Retencja ---------------------------------------------------------
# Kasujemy dopiero na koncu i tylko gdy dzisiejszy backup sie udal — inaczej
# seria nieudanych przebiegow po cichu zjadlaby wszystkie dobre kopie.
if [ "$fail" -eq 0 ]; then
  find "$DEST_ROOT" -mindepth 1 -maxdepth 1 -type d -mtime "+$KEEP_DAYS" -print -exec rm -rf {} + \
    | while read -r old; do note "usuwam stary backup $(basename "$old")"; done
else
  note "byly bledy — retencja pominieta, nic nie kasuje"
fi

note "gotowe: $DEST ($(du -sh "$DEST" | cut -f1)), wolne na dysku: $(df -h "$DEST_ROOT" | awk 'NR==2{print $4}')"
exit "$fail"
