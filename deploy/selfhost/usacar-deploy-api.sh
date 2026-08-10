#!/bin/bash
# Wdrożenie backendu USA Car Finder (FastAPI).
#
# Release w /opt/usacar/releases/ powstał kiedyś ręcznie i nic nie zapisywało jak.
# Ten skrypt to zamyka, na tych samych zasadach co wdrożenie dashboardu.
#
#   usacar-deploy-api.sh [git-ref]        # domyślnie feat/claude-code-provider
#
# Trzy rzeczy, które muszą zostać jak są — inaczej aplikacja gubi dane:
#
# 1. WorkingDirectory usługi zostaje /home/dawid/usacar/usa-car-finder.
#    KAŻDA ścieżka danych w backendzie to "./data/...", liczone od cwd. Zmiana
#    cwd na katalog release'u odcięłaby aplikację od 848 MB stanu (rekordy,
#    joby, ustawienia, raporty klientów).
# 2. Release dostaje .env jako SYMLINK do pliku w katalogu domowym, nie kopię.
#    Tak działa obecny release i dzięki temu zmiana konfiguracji nie wymaga
#    nowego wdrożenia.
# 3. Kod jedzie z /opt (read-only), dane z katalogu domowego. Ten rozdział jest
#    celowy — release ma być niemodyfikowalny.

set -euo pipefail

REF="${1:-feat/claude-code-provider}"
SRC=/home/dawid/usacar                      # checkout gita (i katalog danych)
ROOT=/opt/usacar
VENV=/home/dawid/usacar/usa-car-finder/venv
ENV_FILE=/home/dawid/usacar/usa-car-finder/.env
KEEP=5

exec 9>/var/lock/usacar-deploy-api.lock
flock -n 9 || { echo "Inne wdrożenie już trwa."; exit 1; }

echo "==> pobieram $REF"
git -C "$SRC" fetch --prune --quiet origin
git -C "$SRC" checkout --quiet -B deploy/api "origin/$REF"
SHA="$(git -C "$SRC" rev-parse --short HEAD)"
echo "    $SHA  $(git -C "$SRC" log -1 --format=%s)"

cd "$SRC/usa-car-finder"

echo "==> zależności"
# Ten venv nie ma binarki `pip`, tylko `pip3`/`pip3.12` — `python -m pip`
# działa niezależnie od tego, które shimy zostały zainstalowane.
"$VENV/bin/python" -m pip install -q -r requirements.txt

echo "==> bramki jakości"
# Sam import modułu wyłapuje to, czego składnia nie widzi — brakujący moduł,
# literówkę w imporcie, zły dekorator. Bez tego wdrożylibyśmy backend, który
# wywala się dopiero przy starcie usługi.
"$VENV/bin/python" -c "import compileall,sys; sys.exit(0 if compileall.compile_dir('.', quiet=2, rx=__import__('re').compile(r'venv|__pycache__|node_modules')) else 1)"
"$VENV/bin/python" -c "import api.main" >/dev/null

REL="$ROOT/releases/$SHA-$(date +%Y%m%d-%H%M%S)"
PREV="$(readlink -f "$ROOT/current" 2>/dev/null || true)"
echo "==> release $REL"
sudo -n install -d -o root -g root "$REL"
sudo -n rsync -a --delete \
    --exclude venv --exclude data --exclude logs --exclude __pycache__ \
    --exclude '.env' --exclude playwright_profiles --exclude .git \
    "$SRC/usa-car-finder/" "$REL/usa-car-finder/"

# .env jako symlink — patrz nagłówek, punkt 2.
sudo -n ln -sfn "$ENV_FILE" "$REL/usa-car-finder/.env"
sudo -n chmod -R a-w "$REL"

sudo -n ln -sfn "$REL" "$ROOT/current.new"
sudo -n mv -T "$ROOT/current.new" "$ROOT/current"

echo "==> restart usługi"
sudo -n systemctl restart usacar-api.service

echo "==> health-check"
for i in $(seq 1 30); do
  if curl -fs -o /dev/null --max-time 5 "http://127.0.0.1:8000/health" 2>/dev/null; then
    echo "    OK po ${i}×2s"
    RUNNING="$(readlink -f "$ROOT/current" | sed 's|.*/||')"
    echo "    wdrożone: $RUNNING"
    ls -1dt "$ROOT"/releases/*/ 2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r sudo -n rm -rf
    exit 0
  fi
  sleep 2
done

echo "BŁĄD: health-check nie przeszedł — cofam na poprzedni release"
if [ -n "$PREV" ] && [ -d "$PREV" ]; then
  sudo -n ln -sfn "$PREV" "$ROOT/current.new"
  sudo -n mv -T "$ROOT/current.new" "$ROOT/current"
  sudo -n systemctl restart usacar-api.service
  echo "    cofnięto na $PREV"
else
  echo "    brak poprzedniego release'u — usługa może nie wstać"
fi
exit 1
