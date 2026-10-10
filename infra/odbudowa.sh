#!/usr/bin/env bash
# Odbudowa serwera USA Car Finder na świeżym Ubuntu (WSL2).
#
# Idempotentny: można puścić ponownie po poprawce, nie zepsuje tego, co już stoi.
# Zakłada, że część windowsowa jest zrobiona (patrz ODBUDOWA-OD-ZERA.md) i że
# katalog z kopią zapasową jest dostępny lokalnie.
#
# Użycie:
#   ./odbudowa.sh /sciezka/do/kopii/2026-08-10-0116
set -euo pipefail

KOPIA="${1:-}"
DOM="/home/${SUDO_USER:-$USER}"
REPO_BACK="$DOM/usacar"
GALAZ_BACK="feat/claude-code-provider"
GALAZ_PANEL="feat/selfhost"

krok() { printf '\n\033[1m== %s\033[0m\n' "$*"; }
ok()   { printf '   ✓ %s\n' "$*"; }
uwaga(){ printf '   ! %s\n' "$*"; }

[ -n "$KOPIA" ] && [ -d "$KOPIA" ] || {
  echo "Podaj katalog z kopią: ./odbudowa.sh /sciezka/do/2026-08-10-0116" >&2
  exit 1
}

krok "1/8 Pakiety systemowe"
sudo apt-get update -qq
sudo apt-get install -y -qq python3-venv python3-pip git curl zstd sqlite3 \
    docker-compose-v2 postgresql-client ca-certificates >/dev/null
ok "zainstalowane"

krok "2/8 Docker"
sudo systemctl enable --now docker >/dev/null 2>&1 || true
sudo usermod -aG docker "${SUDO_USER:-$USER}" 2>/dev/null || true
ok "$(docker --version 2>/dev/null || echo 'docker wymaga przelogowania sesji')"

krok "3/8 Konfiguracja i sekrety z kopii"
# Rozpakowujemy do katalogu tymczasowego i kopiujemy wybiórczo — tar z kopii ma
# ścieżki bezwzględne i rozpakowanie go wprost do / nadpisałoby rzeczy systemowe.
TMP=$(mktemp -d)
zstd -dc "$KOPIA/config.tar.zst" | tar -C "$TMP" -xf -
sudo install -d -m 755 /etc/usacar /etc/cloudflared /opt/usacar-db
sudo install -m 600 -o root -g root "$TMP/etc/usacar/dashboard.env" /etc/usacar/dashboard.env
sudo install -m 644 "$TMP/etc/cloudflared/config.yml" /etc/cloudflared/config.yml
sudo install -m 600 "$TMP/opt/usacar-db/.env" /opt/usacar-db/.env
sudo install -m 644 "$TMP/opt/usacar-db/compose.yaml" "$TMP/opt/usacar-db/Caddyfile" /opt/usacar-db/
ok "dashboard.env, cloudflared/config.yml, usacar-db"

krok "4/8 Repozytoria"
if [ ! -d "$REPO_BACK/.git" ]; then
  uwaga "Brak $REPO_BACK — sklonuj backend ręcznie i uruchom skrypt ponownie:"
  uwaga "  git clone --branch $GALAZ_BACK <adres-repo> $REPO_BACK"
  exit 1
fi
git -C "$REPO_BACK" fetch -q origin "$GALAZ_BACK" && git -C "$REPO_BACK" checkout -q "$GALAZ_BACK"
ok "backend na $(git -C "$REPO_BACK" describe --tags --always)"

krok "5/8 Środowisko Pythona i Playwright"
cd "$REPO_BACK/usa-car-finder"
[ -d venv ] || python3 -m venv venv
./venv/bin/python -m pip install -q --upgrade pip
./venv/bin/python -m pip install -q -r requirements.txt
./venv/bin/python -m playwright install chromium >/dev/null 2>&1 || uwaga "playwright install chromium: sprawdź osobno"
ok "venv gotowy"

krok "6/8 Dane z kopii"
install -d data playwright_profiles
install -m 600 "$KOPIA/.env" .env 2>/dev/null || \
  install -m 600 "$TMP/home/dawid/usacar/usa-car-finder/.env" .env
for b in app jobs llm_cache market_price_cache settings watch_queue; do
  [ -f "$KOPIA/sqlite/$b.db" ] && install -m 644 "$KOPIA/sqlite/$b.db" "data/$b.db"
done
# Raporty klientów: osobny katalog, bo serwuje je /artifacts/{filename}.
[ -f "$KOPIA/client_searches.tar.zst" ] && \
  zstd -dc "$KOPIA/client_searches.tar.zst" | tar -C data -xf - 2>/dev/null || true
ok "bazy: $(ls data/*.db 2>/dev/null | wc -l | tr -d ' '), raporty: $(find data -name '*_analysis.json' 2>/dev/null | wc -l | tr -d ' ')"

krok "7/8 Baza Postgres"
cd /opt/usacar-db && sudo docker compose up -d >/dev/null 2>&1 || uwaga "compose: sprawdź osobno"
sleep 5
if [ -f "$KOPIA/postgres.sql.zst" ]; then
  zstd -dc "$KOPIA/postgres.sql.zst" | psql "postgres://postgres@127.0.0.1:5433/postgres" >/dev/null 2>&1 \
    && ok "zrzut Postgresa wczytany" || uwaga "zrzut Postgresa: wczytaj ręcznie"
fi

krok "8/8 Usługi systemd"
INFRA="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
sudo install -m 644 "$INFRA/usacar-api.service" "$INFRA/usacar-dashboard.service" /etc/systemd/system/
if [ -d "$INFRA/usacar-api.service.d" ]; then
  sudo install -d /etc/systemd/system/usacar-api.service.d
  sudo install -m 644 "$INFRA/usacar-api.service.d/"*.conf /etc/systemd/system/usacar-api.service.d/
fi
sudo install -m 755 "$INFRA/usacar-deploy-api.sh" "$INFRA/usacar-deploy-dashboard.sh" /usr/local/bin/ 2>/dev/null || true
sudo touch /var/log/usacar-api.log && sudo chown "${SUDO_USER:-$USER}" /var/log/usacar-api.log
sudo systemctl daemon-reload
sudo systemctl enable --now usacar-api >/dev/null 2>&1 || uwaga "usacar-api nie wstał — journalctl -u usacar-api"
ok "usacar-api: $(systemctl is-active usacar-api 2>/dev/null)"

rm -rf "$TMP"

cat <<'KONIEC'

== Zostało do zrobienia ręcznie ==

  1. Panel:      usacar-deploy-dashboard.sh feat/selfhost
  2. Tunel:      cloudflared tunnel login   (poświadczenia przepadły z dyskiem)
  3. Claude:     claude /login              (jako dawid, subskrypcja nie klucz API)
  4. Giełdy:     zaloguj Copart, IAAI, Manheim — sesje z kopii bywają nieważne

Sprawdzenie:
  curl -s localhost:8000/version
  systemctl is-active usacar-api usacar-dashboard cloudflared docker
KONIEC
