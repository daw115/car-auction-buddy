#!/usr/bin/env bash
# Odbudowa serwera USA Car Finder na świeżym Ubuntu (WSL2).
#
# Przebieg przeszedł realnie 10 października 2026 na Ubuntu 26.04 w WSL2, po
# wyczyszczeniu dysku. Kolejność i obejścia poniżej nie są teoretyczne — każde
# wynikło z błędu, który ten przebieg wywrócił.
#
# Idempotentny: można puścić ponownie po poprawce, nie zepsuje tego, co już stoi.
# Zakłada, że część windowsowa jest zrobiona (patrz ODBUDOWA-OD-ZERA.md), że
# `sudo -n` działa bez hasła i że katalog z kopią jest dostępny lokalnie.
#
# Użycie:
#   ./odbudowa.sh /home/dawid/backups/2026-08-10-0116
set -euo pipefail

KOPIA="${1:-}"
UZYTKOWNIK="${SUDO_USER:-$USER}"
DOM="/home/$UZYTKOWNIK"
REPO_BACK="$DOM/usacar"
REPO_PANEL="/opt/usacar-dashboard/build"
ADRES_REPO="https://github.com/daw115/car-auction-buddy.git"
GALAZ_BACK="feat/claude-code-provider"
GALAZ_PANEL="feat/selfhost"
# Ubuntu 26.04 ma w repozytoriach WYŁĄCZNIE Pythona 3.14, a przypięte wersje
# bibliotek są z epoki 3.11: pydantic 2.7.1 i lxml 5.2.2 nie mają dla 3.14
# gotowych paczek i kompilowałyby się ze źródeł, a playwright 1.44.0 ma w sobie
# sterownik, który o 3.14 nie wie. Przypinamy Pythona, nie ruszamy zależności.
PYTHON="3.12"

krok() { printf '\n\033[1m== %s\033[0m\n' "$*"; }
ok()   { printf '   ✓ %s\n' "$*"; }
uwaga(){ printf '   ! %s\n' "$*"; }

[ -n "$KOPIA" ] && [ -d "$KOPIA" ] || {
  echo "Podaj katalog z kopią: ./odbudowa.sh /home/dawid/backups/2026-08-10-0116" >&2
  exit 1
}
sudo -n true 2>/dev/null || {
  echo "Potrzebne sudo bez hasła — każdy krok leci nową sesją:" >&2
  echo '  echo "'"$UZYTKOWNIK"' ALL=(ALL) NOPASSWD:ALL" | sudo tee /etc/sudoers.d/'"$UZYTKOWNIK"'-nopasswd' >&2
  exit 1
}

krok "1/11 Pakiety systemowe"
# unzip: instalator buna milczy o tym wymaganiu do chwili, gdy go nie znajdzie.
sudo apt-get update -qq
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
    git curl unzip zstd sqlite3 rsync ca-certificates gnupg \
    nodejs docker.io docker-compose-v2 postgresql-client >/dev/null
ok "node $(node --version), docker $(docker --version | grep -o '[0-9.]*' | head -1)"

krok "2/11 Google Chrome i cloudflared"
# Chrome z repozytorium Google, nie chromium ze snapa: BROWSER_CHANNEL=chrome,
# a przy okazji ciągnie biblioteki, których brakuje chromium Playwrighta.
if ! command -v google-chrome >/dev/null; then
  curl -fsSL https://dl.google.com/linux/linux_signing_key.pub \
    | sudo gpg --dearmor -o /usr/share/keyrings/google-chrome.gpg
  echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome.gpg] https://dl.google.com/linux/chrome/deb/ stable main" \
    | sudo tee /etc/apt/sources.list.d/google-chrome.list >/dev/null
fi
if ! command -v cloudflared >/dev/null; then
  curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg \
    | sudo tee /usr/share/keyrings/cloudflare-main.gpg >/dev/null
  echo "deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared any main" \
    | sudo tee /etc/apt/sources.list.d/cloudflared.list >/dev/null
fi
sudo apt-get update -qq
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq google-chrome-stable cloudflared >/dev/null
ok "$(google-chrome --version), $(cloudflared --version | cut -d' ' -f1-3)"

krok "3/11 Repozytoria"
# Repozytorium jest publiczne, więc klon nie wymaga żadnych poświadczeń.
[ -d "$REPO_BACK/.git" ] || git clone -q --branch "$GALAZ_BACK" "$ADRES_REPO" "$REPO_BACK"
sudo install -d -o "$UZYTKOWNIK" -g "$UZYTKOWNIK" /opt/usacar /opt/usacar/releases \
     /opt/usacar-dashboard /opt/usacar-dashboard/releases /opt/usacar-db
[ -d "$REPO_PANEL/.git" ] || git clone -q --branch "$GALAZ_PANEL" "$ADRES_REPO" "$REPO_PANEL"
git -C "$REPO_BACK" fetch -q --tags origin
git -C "$REPO_PANEL" fetch -q --tags origin
ok "backend $(git -C "$REPO_BACK" describe --tags --always), panel $(git -C "$REPO_PANEL" describe --tags --always)"

krok "4/11 Python $PYTHON i zależności"
# uv, bo apt nie da 3.12. Instaluje się do ~/.local/bin, bez roota.
command -v "$DOM/.local/bin/uv" >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null 2>&1
UV="$DOM/.local/bin/uv"
"$UV" python install "$PYTHON" >/dev/null
cd "$REPO_BACK/usa-car-finder"
[ -x venv/bin/python ] || "$UV" venv --python "$PYTHON" venv >/dev/null
# `uv venv` NIE wkłada do środowiska pip-a. Pierwsze podejście w tym przebiegu
# poleciało przez `python -m pip install -r requirements.txt`, wypisało
# "No module named pip" i wyszło z kodem 0 — instalacja bez jednej paczki,
# uznana za udaną. pip wkładamy jawnie, bo liczy na niego skrypt wdrożeniowy.
"$UV" pip install -q --python venv/bin/python pip -r requirements.txt
ok "$(./venv/bin/python -V), paczek: $(./venv/bin/python -m pip list 2>/dev/null | wc -l)"

krok "5/11 Chromium Playwrighta"
# BEZ --with-deps: lista zależności w 1.44.0 zna jeszcze libasound2, które w
# 26.04 nazywa się libasound2t64. apt odmawia, playwright przerywa pobieranie
# przeglądarki i kończy komunikatem "Failed to install browsers". Biblioteki
# wchodzą z Chrome w kroku 2, więc chromium potrzebuje tylko samego pobrania.
[ -d "$DOM/.cache/ms-playwright" ] || ./venv/bin/python -m playwright install chromium
ok "chromium: $(ls "$DOM/.cache/ms-playwright" 2>/dev/null | tr '\n' ' ')"

krok "6/11 Konfiguracja i sekrety z kopii"
# Rozpakowujemy do katalogu tymczasowego i kopiujemy wybiórczo — tar z kopii ma
# ścieżki bezwzględne i rozpakowanie go wprost do / nadpisałoby rzeczy systemowe.
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
zstd -dc "$KOPIA/config.tar.zst" | tar -C "$TMP" -xf - 2>/dev/null
sudo install -d -m 755 /etc/usacar /etc/cloudflared
sudo install -m 600 -o root -g root "$TMP/etc/usacar/dashboard.env" /etc/usacar/dashboard.env
sudo install -m 644 -o root -g root "$TMP/etc/cloudflared/config.yml" /etc/cloudflared/config.yml
install -m 600 "$TMP/opt/usacar-db/.env" /opt/usacar-db/.env
install -m 644 "$TMP/opt/usacar-db/compose.yaml" "$TMP/opt/usacar-db/Caddyfile" /opt/usacar-db/
install -m 644 "$REPO_PANEL/deploy/selfhost/usacar-db/00-roles.sql" \
               "$REPO_PANEL/deploy/selfhost/usacar-db/mint-jwt.py" /opt/usacar-db/
install -m 600 "$TMP/home/dawid/usacar/usa-car-finder/.env" "$REPO_BACK/usa-car-finder/.env"
ok "dashboard.env, cloudflared/config.yml, usacar-db, .env backendu"

krok "7/11 Dane z kopii"
cd "$REPO_BACK/usa-car-finder"
install -d data playwright_profiles logs
for b in app jobs llm_cache market_price_cache settings watch_queue; do
  [ -f "$KOPIA/sqlite/$b.db" ] && install -m 644 "$KOPIA/sqlite/$b.db" "data/$b.db"
done
# Raporty klientów: osobny katalog, bo serwuje je /artifacts/{filename}.
[ -f "$KOPIA/client_searches.tar.zst" ] && zstd -dc "$KOPIA/client_searches.tar.zst" | tar -C data -xf -
./venv/bin/python - <<'PY'
import glob, sqlite3
for p in sorted(glob.glob("data/*.db")):
    c = sqlite3.connect(p)
    stan = c.execute("PRAGMA integrity_check").fetchone()[0]
    c.close()
    print(f"   {'✓' if stan == 'ok' else '!'} {p}: {stan}")
PY
ok "raporty: $(find data -name '*_analysis.json' 2>/dev/null | wc -l | tr -d ' ')"

krok "8/11 Postgres w Dockerze"
sudo systemctl enable --now docker >/dev/null 2>&1 || true
sudo usermod -aG docker "$UZYTKOWNIK" 2>/dev/null || true
cd /opt/usacar-db
set -a; . ./.env; set +a
sudo -n docker compose up -d >/dev/null
for i in $(seq 1 60); do
  sudo -n docker compose exec -T postgres pg_isready -U postgres -d postgres >/dev/null 2>&1 && break
  sleep 2
done
export PGPASSWORD="$POSTGRES_PASSWORD"
BAZA="postgres://postgres@127.0.0.1:5433/postgres"
# Role PRZED zrzutem: zrzut nie zawiera CREATE ROLE, a nadaje im uprawnienia.
psql "$BAZA" -q -v ON_ERROR_STOP=1 -v authenticator_password="'$AUTHENTICATOR_PASSWORD'" -f 00-roles.sql
if [ -f "$KOPIA/postgres.sql.zst" ]; then
  zstd -dc "$KOPIA/postgres.sql.zst" | psql "$BAZA" -q -v ON_ERROR_STOP=1
fi
ok "tabel: $(psql "$BAZA" -tAc "select count(*) from pg_tables where schemaname='public'" | tr -d ' ')"

krok "9/11 bun"
# Wariant baseline: CPU tego serwera (i5-3210M) nie ma AVX2, standardowy bun
# wysypuje się przez SIGILL. Instalator dobiera wariant sam, ale sprawdzamy.
[ -x "$DOM/.bun/bin/bun" ] || curl -fsSL https://bun.sh/install | bash -s "bun-v1.2.14" >/dev/null 2>&1
"$DOM/.bun/bin/bun" --version >/dev/null || { uwaga "bun nie odpowiada (SIGILL?) — panel się nie zbuduje"; exit 1; }
ok "bun $("$DOM/.bun/bin/bun" --version)"

krok "10/11 Jednostki systemd"
INFRA="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PANEL_INFRA="$REPO_PANEL/deploy/selfhost"
SKRYPTY="$REPO_BACK/usa-car-finder/scripts"
sudo install -m 644 "$INFRA/usacar-api.service" /etc/systemd/system/
sudo install -m 644 "$PANEL_INFRA/usacar-dashboard.service" \
                    "$PANEL_INFRA/usacar-backup.service" \
                    "$PANEL_INFRA/usacar-backup.timer" /etc/systemd/system/
sudo install -m 644 "$SKRYPTY/usacar-watch.service" "$SKRYPTY/usacar-watch.timer" \
                    "$SKRYPTY/usacar-manheim-browser.service" /etc/systemd/system/
sudo install -d /etc/systemd/system/usacar-api.service.d
sudo install -m 644 "$INFRA/usacar-api.service.d/"*.conf /etc/systemd/system/usacar-api.service.d/
# Skrypty wdrożeniowe żyją w repo PANELU, nie backendu.
sudo install -m 755 "$PANEL_INFRA/usacar-deploy-api.sh" "$PANEL_INFRA/usacar-deploy-dashboard.sh" \
                    "$PANEL_INFRA/usacar-backup.sh" /usr/local/bin/
# Dwa różne skrypty nazywają się usacar-watchdog.sh i celują w ten sam plik.
# Ten z repo panelu pilnuje backendu I panelu, z osobnymi licznikami; ten z
# backendu zna tylko API. Instalujemy nowszy, kolejność ma znaczenie.
sudo install -m 755 "$PANEL_INFRA/usacar-watchdog.sh" /usr/local/bin/usacar-watchdog.sh
sudo install -m 644 "$INFRA/usacar-watchdog.service" "$INFRA/usacar-watchdog.timer" \
                    "$INFRA/cloudflared.service" /etc/systemd/system/
install -d "$DOM/.config/systemd/user"
install -m 644 "$SKRYPTY/ahb-cdp-chrome.service" "$DOM/.config/systemd/user/"
for log in usacar-api usacar-watch usacar-manheim-browser usacar-watchdog; do
  sudo touch "/var/log/$log.log" && sudo chown "$UZYTKOWNIK" "/var/log/$log.log"
done
sudo loginctl enable-linger "$UZYTKOWNIK" >/dev/null 2>&1 || true
sudo systemctl daemon-reload
sudo systemctl enable usacar-api usacar-dashboard >/dev/null
sudo systemctl enable --now usacar-watch.timer usacar-backup.timer usacar-watchdog.timer >/dev/null
XDG_RUNTIME_DIR="/run/user/$(id -u "$UZYTKOWNIK")" systemctl --user enable --now ahb-cdp-chrome >/dev/null 2>&1 \
  || uwaga "ahb-cdp-chrome nie wstał (WSLg?) — Bidfax będzie milczał"
ok "jednostki zainstalowane, timery włączone"

krok "11/11 Wdrożenia i weryfikacja"
# Przez skrypty produkcyjne, nie ręcznie: bramki jakości i health-check są ich
# częścią, a usacar-api.service czyta kod z /opt/usacar/current.
usacar-deploy-api.sh "$GALAZ_BACK"
usacar-deploy-dashboard.sh "$GALAZ_PANEL"
echo
echo "   backend: $(curl -fs --max-time 5 localhost:8000/version || echo NIE_ODPOWIADA)"
echo "   panel:   $(curl -fs --max-time 5 localhost:3000/api/version || echo NIE_ODPOWIADA)"
echo "   baza:    HTTP $(curl -s -o /dev/null -w '%{http_code}' --max-time 5 localhost:3001/rest/v1/)"
echo "   usługi:  $(systemctl is-active usacar-api usacar-dashboard docker | tr '\n' ' ')"

cat <<'KONIEC'

== Zostało do zrobienia ręcznie ==

  1. Tunel:   cloudflared tunnel login       (poświadczenia nie są w kopii)
              cloudflared tunnel token --cred-file \
                /etc/cloudflared/99e0969c-9300-4a2e-a857-c54ff1b7273e.json \
                99e0969c-9300-4a2e-a857-c54ff1b7273e
              sudo systemctl enable --now cloudflared
  2. Claude:  claude /login                  (subskrypcja, nie klucz API)
  3. Giełdy:  zaloguj Copart, IAAI, Manheim — sesje z kopii bywają nieważne
  4. Bidfax:  przejdź Cloudflare w Chrome na 127.0.0.1:9222 (profil CDP)
  5. Panel:   sprawdź hasło z dashboard.env w przeglądarce

Kopia poza serwer — ta jedna rzecz zdecydowała o tym, ile dało się odzyskać:
  scp -r dawid@<serwer>:/home/dawid/backups/<data> .
KONIEC
