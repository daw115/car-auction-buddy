#!/bin/bash
# Wdrożenie dashboardu USA Car Finder.
#
# Dotąd nie było żadnego skryptu — release w /opt/usacar/releases/ powstał ręcznie
# i nie dało się go odtworzyć. Ten skrypt zamyka tę dziurę dla dashboardu.
#
#   usacar-deploy-dashboard.sh [git-ref]      # domyślnie feat/selfhost
#
# Kolejność jest celowa: wszystko, co może się wysypać (build, testy), dzieje się
# ZANIM katalog releases/ zostanie tknięty. Przy niepowodzeniu health-checku
# symlink wraca na poprzedni release.

set -euo pipefail

REF="${1:-feat/selfhost}"
ROOT=/opt/usacar-dashboard
BUILD="$ROOT/build"
PORT="${NITRO_PORT:-3000}"
KEEP=5

exec 9>/var/lock/usacar-deploy-dashboard.lock
flock -n 9 || { echo "Inne wdrożenie już trwa."; exit 1; }

export PATH="$HOME/.bun/bin:$PATH"
export NODE_OPTIONS=--max-old-space-size=4096

echo "==> pobieram $REF"
git -C "$BUILD" fetch --prune --quiet origin
git -C "$BUILD" checkout --quiet --detach "origin/$REF"
SHA="$(git -C "$BUILD" rev-parse --short HEAD)"
echo "    $SHA  $(git -C "$BUILD" log -1 --format=%s)"

cd "$BUILD"
echo "==> zależności"
nice -n 10 bun install --frozen-lockfile

echo "==> bramki jakości"
node scripts/check-server-imports.mjs
nice -n 10 bunx tsc --noEmit

echo "==> build"
nice -n 10 bun run build
[ -f .output/server/index.mjs ] || { echo "BŁĄD: brak .output/server/index.mjs"; exit 1; }
# nitro.json jest sformatowany (spacja po dwukropku), więc parsujemy, nie grepujemy.
PRESET="$(python3 -c 'import json;print(json.load(open(".output/nitro.json")).get("preset",""))')"
[ "$PRESET" = "node-server" ] \
  || { echo "BŁĄD: preset w .output/nitro.json to '$PRESET', oczekiwano node-server"; exit 1; }
# Gdyby kiedyś wróciła zależność ciągnąca runtime Workers — łapiemy to tutaj.
if grep -rql "cloudflare:workers" .output/server 2>/dev/null; then
  echo "BŁĄD: w .output/server jest cloudflare:workers — to nie zadziała na Node"; exit 1
fi

REL="$ROOT/releases/$SHA-$(date +%Y%m%d-%H%M%S)"
PREV="$(readlink -f "$ROOT/current" 2>/dev/null || true)"
echo "==> release $REL"
install -d "$REL"
rsync -a --delete .output/ "$REL"/

# Podmiana symlinka jest atomowa (rename), więc nie ma okna z połamanym current.
ln -sfn "$REL" "$ROOT/current.new"
mv -T "$ROOT/current.new" "$ROOT/current"

echo "==> restart usługi"
sudo -n systemctl restart usacar-dashboard.service

echo "==> health-check"
for i in $(seq 1 30); do
  # -fs bez -S: pierwsza proba prawie zawsze trafia w usluge, ktora jeszcze
  # wstaje, a "curl: (7) Failed to connect" tuz przed "OK" tylko myli.
  if curl -fs -o /dev/null --max-time 5 "http://127.0.0.1:$PORT/api/version" 2>/dev/null; then
    echo "    OK po ${i}×2s"
    RUNNING="$(curl -fs --max-time 5 "http://127.0.0.1:$PORT/api/version" 2>/dev/null \
               | grep -o '"short":"[^"]*"' | cut -d'"' -f4 || true)"
    echo "    wdrożone: ${RUNNING:-?}  (oczekiwano $SHA)"
    if [ -n "$RUNNING" ] && [ "$RUNNING" != "$SHA" ]; then
      echo "    UWAGA: dziala inna wersja niz wdrazana"
    fi
    # Przycinanie starych release'ów dopiero po potwierdzeniu, że nowy żyje.
    ls -1dt "$ROOT"/releases/*/ 2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r rm -rf
    exit 0
  fi
  sleep 2
done

echo "BŁĄD: health-check nie przeszedł — cofam na poprzedni release"
if [ -n "$PREV" ] && [ -d "$PREV" ]; then
  ln -sfn "$PREV" "$ROOT/current.new"
  mv -T "$ROOT/current.new" "$ROOT/current"
  sudo -n systemctl restart usacar-dashboard.service
  echo "    cofnięto na $PREV"
else
  echo "    brak poprzedniego release'u do cofnięcia"
fi
exit 1
