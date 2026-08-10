#!/bin/bash
# Uruchamia OSOBNĄ instancję Chrome (osobny profil, port debug 9223) z wtyczką
# BidWise, do której scraper Manheima podłącza się przez CDP.
#
# Dlaczego tak, a nie --load-extension:
#   * Chrome >=137 ignoruje --load-extension z linii poleceń,
#   * BidWise wczytana jako unpacked WYŁĄCZA SAMA SIEBIE po kilku sekundach
#     (zmierzone: popup 200 zaraz po starcie, po 10 s ERR_BLOCKED_BY_CLIENT,
#     w profilu state=0 disable_reasons=1 — DISABLE_USER_ACTION). Ma uprawnienie
#     `management`, więc może to zrobić.
#   Wniosek: wtyczka musi być zainstalowana normalnie, ze Chrome Web Store.
#
# Osobny profil jest konieczny — Chrome >=136 nie wpuszcza --remote-debugging-port
# na domyślny profil, a i tak nie da się użyć profilu zajętego przez działającą Chrome.
#
# Po uruchomieniu (jednorazowo):
#   1. Zainstaluj BidWise ze Web Store w tym oknie:
#      https://chromewebstore.google.com/detail/mapbnmkenejciggnkildgcohibbnhnmm
#   2. Zaloguj się w BidWise (OTP przejdzie normalnie).
#   3. Wejdź na https://search.manheim.com/results i upewnij się, że NIE
#      przekierowuje na site.manheim.com (czyli sesja żyje).
#   4. Zostaw to okno Chrome OTWARTE.
#   5. W .env ustaw:
#        MANHEIM_CHROME_CDP_URL=http://127.0.0.1:9223
#
# Kolejne uruchomienia: profil pamięta wtyczkę i sesję — wystarczy odpalić skrypt.

set -euo pipefail

if [ -n "${MANHEIM_CHROME_BIN:-}" ]; then
    CHROME="$MANHEIM_CHROME_BIN"
elif [ -x "/usr/bin/google-chrome" ]; then
    CHROME="/usr/bin/google-chrome"
elif [ -x "/usr/bin/google-chrome-stable" ]; then
    CHROME="/usr/bin/google-chrome-stable"
elif [ -x "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" ]; then
    CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
else
    echo "[ERROR] Nie znaleziono Google Chrome." >&2
    echo "        Ustaw MANHEIM_CHROME_BIN=/path/to/chrome." >&2
    exit 1
fi

PROFILE_DIR="${MANHEIM_CHROME_DEBUG_PROFILE:-$HOME/.chrome-manheim-debug-profile}"
DEBUG_PORT="${MANHEIM_CHROME_DEBUG_PORT:-9223}"
DEBUG_ADDR="${MANHEIM_CHROME_DEBUG_ADDR:-127.0.0.1}"

if [ ! -x "$CHROME" ]; then
    echo "[ERROR] Chrome pod '$CHROME' nie jest wykonywalny." >&2
    exit 1
fi

mkdir -p "$PROFILE_DIR"

cat <<EOF
================================================================
 manheim-chrome-debug — sesja Chrome dla Manheima (BidWise)
================================================================
 Chrome:    $CHROME
 Profil:    $PROFILE_DIR
 CDP URL:   http://$DEBUG_ADDR:$DEBUG_PORT

 1) Otworzy się okno Chrome (osobne od Twojego codziennego).
 2) Przy pierwszym uruchomieniu zainstaluj BidWise ze Web Store
    i zaloguj się w niej.
 3) Sprawdź, że search.manheim.com pokazuje wyszukiwarkę,
    a nie site.manheim.com.
 4) Zostaw to okno otwarte.
 5) W .env: MANHEIM_CHROME_CDP_URL=http://$DEBUG_ADDR:$DEBUG_PORT
 6) W INNYM terminalu:

    cd "$(pwd)"
    python3 scripts/manheim_probe.py BMW X5

================================================================
EOF

exec "$CHROME" \
    --remote-debugging-port="$DEBUG_PORT" \
    --remote-debugging-address="$DEBUG_ADDR" \
    --user-data-dir="$PROFILE_DIR" \
    "https://chromewebstore.google.com/detail/mapbnmkenejciggnkildgcohibbnhnmm" \
    "https://search.manheim.com/results"
