#!/bin/bash
# Uruchamia OSOBNĄ instancję Chrome (osobny profil, port debug 9222)
# do której Playwright może się podłączyć przez CDP.
#
# Po uruchomieniu (jedna Chrome obsługuje BIDFAX + AUTOHELPERBOT):
#   1. Wejdź w Chrome na bidfax.info → kliknij CF Turnstile jeśli się pojawi
#   2. Otwórz NOWĄ kartę → autohelperbot.com → kliknij CF Turnstile
#      (oraz zaloguj się do AHB jeśli wymaga — sesja zapamięta się w profilu)
#   3. Zostaw Chrome OTWARTE
#   4. W .env produkcji ustaw:
#        BIDFAX_CHROME_CDP_URL=http://<host_ip>:9222   (bidfax enrichment)
#        AHB_CHROME_CDP_URL=http://<host_ip>:9222       (AHB enrichment)
#      (AHB_CHROME_CDP_URL może być puste — wtedy fallback do BIDFAX_CHROME_CDP_URL)
#
# Profil zapamiętuje CF clearance cookies — kolejne uruchomienia idą bez challenge'a.
# Cookie CF ważne ~1-7 dni — gdy AHB znów zwraca "security verification",
# wróć do tej Chrome i kliknij CF ponownie (bez restartu backendu).
#
# Cross-platform: auto-detect Chrome dla Linux/WSL2 i macOS. Override BIDFAX_CHROME_BIN
# żeby wskazać własną ścieżkę.

set -euo pipefail

# Pozwól użytkownikowi wskazać własną ścieżkę
if [ -n "${BIDFAX_CHROME_BIN:-}" ]; then
    CHROME="$BIDFAX_CHROME_BIN"
elif [ -x "/usr/bin/google-chrome" ]; then
    CHROME="/usr/bin/google-chrome"
elif [ -x "/usr/bin/google-chrome-stable" ]; then
    CHROME="/usr/bin/google-chrome-stable"
elif [ -x "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" ]; then
    CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
else
    echo "[ERROR] Nie znaleziono Google Chrome." >&2
    echo "        Sprawdziłem: /usr/bin/google-chrome, /usr/bin/google-chrome-stable," >&2
    echo "        /Applications/Google Chrome.app/Contents/MacOS/Google Chrome" >&2
    echo "        Ustaw BIDFAX_CHROME_BIN=/path/to/chrome żeby wskazać własną ścieżkę." >&2
    exit 1
fi

PROFILE_DIR="${BIDFAX_CHROME_DEBUG_PROFILE:-$HOME/.chrome-bidfax-debug-profile}"
DEBUG_PORT="${BIDFAX_CHROME_DEBUG_PORT:-9222}"
DEBUG_ADDR="${BIDFAX_CHROME_DEBUG_ADDR:-127.0.0.1}"

if [ ! -x "$CHROME" ]; then
    echo "[ERROR] Chrome pod '$CHROME' nie jest wykonywalny." >&2
    exit 1
fi

mkdir -p "$PROFILE_DIR"

cat <<EOF
================================================================
 bidfax-chrome-debug — osobna sesja Chrome dla bidfax
================================================================
 Chrome:    $CHROME
 Profil:    $PROFILE_DIR
 CDP port:  $DEBUG_PORT
 CDP addr:  $DEBUG_ADDR
 CDP URL:   http://$DEBUG_ADDR:$DEBUG_PORT

 1) Zaraz otworzy się okno Chrome.
 2) Wejdź na https://bidfax.info
 3) Jeśli CF Turnstile — kliknij checkbox (powinien działać).
 4) Zostaw Chrome otwarte.
 5) W INNYM terminalu odpal test:

    cd "$(pwd)"
    BIDFAX_ENRICHMENT_ENABLED=true \\
    BIDFAX_CHROME_CDP_URL=http://$DEBUG_ADDR:$DEBUG_PORT \\
    python3 test_bidfax_real.py

 UWAGA dla WSL2:
   * Chrome wewnątrz WSL2 wymaga WSLg/X11. Najczęściej preferowana ścieżka
     to Chrome na hoście Windows z --remote-debugging-port=9222
     --remote-debugging-address=0.0.0.0, wtedy z WSL2 podłącz się przez
     IP hosta (cat /etc/resolv.conf | grep nameserver) zamiast 127.0.0.1.

================================================================
EOF

exec "$CHROME" \
    --remote-debugging-port="$DEBUG_PORT" \
    --remote-debugging-address="$DEBUG_ADDR" \
    --user-data-dir="$PROFILE_DIR" \
    "https://bidfax.info" \
    "https://autohelperbot.com/en/"
