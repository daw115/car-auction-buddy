#!/bin/bash
# Sesja przeglądarki Manheima na wirtualnym ekranie (Ubuntu, bez pulpitu).
#
# Xvfb  — ekran bez fizycznego wyświetlacza; rozszerzenia Chromium nie działają
#         headless, a sesję Manheima trzyma wtyczka BidWise.
# openbox — minimalny menedżer okien; bez niego Chrome bywa bez ramki i część
#         okien dialogowych (logowanie, instalacja wtyczki) jest nieklikalna.
# x11vnc — podgląd tylko na 127.0.0.1, żeby operator mógł raz zalogować BidWise.
#         Z zewnątrz wchodzisz tunelem SSH, nie po sieci.
#
# Uruchamiane przez systemd (usacar-manheim-browser.service) albo ręcznie.
set -euo pipefail

DISPLAY_NUM="${MANHEIM_DISPLAY:-:99}"
SCREEN="${MANHEIM_SCREEN:-1600x1000x24}"
VNC_PORT="${MANHEIM_VNC_PORT:-5900}"
PROFILE_DIR="${MANHEIM_CHROME_PROFILE_DIR:-$HOME/.chrome-manheim-profile}"
START_URL="${MANHEIM_START_URL:-https://search.manheim.com/results}"

command -v Xvfb >/dev/null || { echo "[ERROR] Brak Xvfb — uruchom scripts/manheim-browser-setup.sh" >&2; exit 1; }
command -v google-chrome >/dev/null || { echo "[ERROR] Brak google-chrome" >&2; exit 1; }

mkdir -p "$PROFILE_DIR"

cleanup() {
    # Kolejność odwrotna do startu; błędy przy zamykaniu nie mają znaczenia.
    [[ -n "${CHROME_PID:-}" ]] && kill "$CHROME_PID" 2>/dev/null || true
    [[ -n "${VNC_PID:-}"    ]] && kill "$VNC_PID"    2>/dev/null || true
    [[ -n "${WM_PID:-}"     ]] && kill "$WM_PID"     2>/dev/null || true
    [[ -n "${XVFB_PID:-}"   ]] && kill "$XVFB_PID"   2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "[manheim-browser] Xvfb $DISPLAY_NUM ($SCREEN)"
Xvfb "$DISPLAY_NUM" -screen 0 "$SCREEN" -nolisten tcp &
XVFB_PID=$!
export DISPLAY="$DISPLAY_NUM"

# Xvfb potrzebuje chwili, zanim przyjmie klientów.
for _ in {1..30}; do
    xdpyinfo -display "$DISPLAY_NUM" >/dev/null 2>&1 && break
    sleep 0.3
done

command -v openbox >/dev/null && { openbox & WM_PID=$!; }

# Hasło, gdy plik istnieje. macOS Screen Sharing odbija się od serwera bez
# uwierzytelniania ("Connection failed"), więc -nopw jest tu pułapką, nie
# ułatwieniem. Utworzenie hasła: x11vnc -storepasswd HASLO ~/.vnc/passwd
VNC_PASSWD="${MANHEIM_VNC_PASSWD:-$HOME/.vnc/passwd}"
if [[ -f "$VNC_PASSWD" ]]; then
    VNC_AUTH=(-rfbauth "$VNC_PASSWD")
    echo "[manheim-browser] x11vnc na 127.0.0.1:$VNC_PORT (hasło z $VNC_PASSWD)"
else
    VNC_AUTH=(-nopw)
    echo "[manheim-browser] x11vnc na 127.0.0.1:$VNC_PORT (BEZ hasła — macOS może odmówić)"
fi
x11vnc -display "$DISPLAY_NUM" -localhost -rfbport "$VNC_PORT" -forever -shared "${VNC_AUTH[@]}" -quiet &
VNC_PID=$!

echo "[manheim-browser] Chrome, profil $PROFILE_DIR"
# --no-sandbox: WSL2 bez user namespaces przewraca się na sandboxie Chrome.
# --no-first-run/--no-default-browser-check: bez tego wita nas kreator, który
# na wirtualnym ekranie tylko przeszkadza.
google-chrome \
    --user-data-dir="$PROFILE_DIR" \
    --no-sandbox \
    --no-first-run \
    --no-default-browser-check \
    --disable-features=Translate \
    --window-size=1600,1000 \
    "$START_URL" &
CHROME_PID=$!

cat <<EOF

[manheim-browser] Gotowe. Z Maca:
    ssh -L $VNC_PORT:127.0.0.1:$VNC_PORT wsl2-cf
    vnc://127.0.0.1:$VNC_PORT

Przy pierwszym uruchomieniu: zainstaluj BidWise ze Web Store, zaloguj się,
doładuj extensions/manheim-collector (Load unpacked) i zrób jedno wyszukiwanie.
EOF

wait "$CHROME_PID"
