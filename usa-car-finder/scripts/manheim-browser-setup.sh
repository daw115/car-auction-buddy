#!/bin/bash
# Jednorazowa instalacja zaplecza dla przeglądarki Manheima na Ubuntu.
#
# Po co wirtualny ekran: sesję Manheima trzyma wtyczka BidWise, a rozszerzenia
# Chromium nie działają bez wyświetlacza. Xvfb daje ekran bez pulpitu, x11vnc
# pozwala się do niego podłączyć na czas logowania (OTP) i instalacji wtyczek.
#
# Wymaga sudo. Uruchom RAZ:
#     bash scripts/manheim-browser-setup.sh
set -euo pipefail

PACKAGES=(xvfb x11vnc openbox)

echo "== Instaluję: ${PACKAGES[*]}"
sudo apt-get update -qq
sudo apt-get install -y "${PACKAGES[@]}"

if ! command -v google-chrome >/dev/null 2>&1; then
    echo "[ERROR] Brak google-chrome. Zainstaluj Chrome i uruchom ponownie." >&2
    exit 1
fi

echo
echo "== Zainstalowane:"
printf '   Xvfb    %s\n' "$(command -v Xvfb)"
printf '   x11vnc  %s\n' "$(command -v x11vnc)"
printf '   openbox %s\n' "$(command -v openbox)"
printf '   chrome  %s\n' "$(google-chrome --version)"

cat <<'EOF'

== Dalej ==

1. Uruchom sesję przeglądarki:
       bash scripts/manheim-browser-run.sh

2. Z Maca zestaw tunel do VNC (VNC NIE jest wystawiony na świat):
       ssh -L 5900:127.0.0.1:5900 wsl2-cf

3. Podłącz się przeglądarką ekranu (na macOS: Cmd+K w Finderze):
       vnc://127.0.0.1:5900

4. W otwartym Chrome zrób RAZ:
   a) zainstaluj BidWise ze Web Store i zaloguj się,
   b) chrome://extensions → Developer mode → Load unpacked
      → extensions/manheim-collector,
   c) wejdź na https://search.manheim.com/results i wykonaj jedno wyszukiwanie
      (rozszerzenie musi podpatrzeć kształt żądania),
   d) zostaw kartę Manheima otwartą.

   Uwaga: Chrome >=137 nie wczytuje rozszerzeń z --load-extension, dlatego
   kolektor instalujemy klikając w UI. W profilu zostaje na stałe.

5. Włącz usługę, żeby sesja wstawała po restarcie:
       sudo cp scripts/usacar-manheim-browser.service /etc/systemd/system/
       sudo systemctl daemon-reload
       sudo systemctl enable --now usacar-manheim-browser

6. W /etc/usacar (albo .env backendu):
       MANHEIM_BACKEND_ENABLED=true
       MANHEIM_SOURCE_MODE=collector
EOF
