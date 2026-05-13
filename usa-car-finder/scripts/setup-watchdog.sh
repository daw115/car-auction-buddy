#!/bin/bash
# One-time setup watchdog dla usacar-api na WSL2.
#
# Robi:
# 1. Kopiuje watchdog script do /usr/local/bin/
# 2. Tworzy systemd service (oneshot) + timer (co 2 min)
# 3. Enabluje + uruchamia timer
#
# Wymaga sudo. Idempotentny — można uruchamiać wielokrotnie.

set -euo pipefail

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
WATCHDOG_SRC="$SCRIPT_DIR/usacar-watchdog.sh"
WATCHDOG_BIN="/usr/local/bin/usacar-watchdog.sh"
SERVICE_FILE="/etc/systemd/system/usacar-watchdog.service"
TIMER_FILE="/etc/systemd/system/usacar-watchdog.timer"

if [[ ! -f "$WATCHDOG_SRC" ]]; then
    echo "[ERROR] $WATCHDOG_SRC nie istnieje. Uruchom skrypt z katalogu repo." >&2
    exit 1
fi

echo "=== Instalacja watchdog binary ==="
sudo cp "$WATCHDOG_SRC" "$WATCHDOG_BIN"
sudo chmod 755 "$WATCHDOG_BIN"
echo "  -> $WATCHDOG_BIN"

echo ""
echo "=== Tworzenie systemd service (oneshot) ==="
sudo tee "$SERVICE_FILE" > /dev/null <<'EOF'
[Unit]
Description=USA Car Finder API watchdog (one-shot health probe)
After=usacar-api.service cloudflared.service

[Service]
Type=oneshot
ExecStart=/usr/local/bin/usacar-watchdog.sh
# Run as root żeby móc systemctl restart (alternativnie: NOPASSWD sudo dla dawid)
User=root
EOF
echo "  -> $SERVICE_FILE"

echo ""
echo "=== Tworzenie systemd timer (co 2 min) ==="
sudo tee "$TIMER_FILE" > /dev/null <<'EOF'
[Unit]
Description=USA Car Finder API watchdog timer (probe co 2 min)
Requires=usacar-watchdog.service

[Timer]
# Pierwszy run 2 min po starcie (żeby pozwolić uvicorn się załadować)
OnBootSec=2min
# Następne co 2 min
OnUnitActiveSec=2min
AccuracySec=10s
Persistent=true

[Install]
WantedBy=timers.target
EOF
echo "  -> $TIMER_FILE"

echo ""
echo "=== Reload + enable + start timer ==="
sudo systemctl daemon-reload
sudo systemctl enable usacar-watchdog.timer
sudo systemctl restart usacar-watchdog.timer
echo ""
sudo systemctl status usacar-watchdog.timer --no-pager | head -10

echo ""
echo "=== Tworzenie /var/log/usacar-watchdog.log ==="
sudo touch /var/log/usacar-watchdog.log
sudo chmod 644 /var/log/usacar-watchdog.log

echo ""
echo "=== Test run watchdog ==="
sudo systemctl start usacar-watchdog.service
sleep 2
sudo systemctl status usacar-watchdog.service --no-pager | head -10
echo ""
echo "Last entries from /var/log/usacar-watchdog.log:"
tail -5 /var/log/usacar-watchdog.log 2>/dev/null || echo "(log file pusty — to OK przy pierwszym uruchomieniu)"

echo ""
echo "=== Setup ZAKOŃCZONY ==="
echo ""
echo "Monitorowanie:"
echo "  Status timer:        sudo systemctl status usacar-watchdog.timer"
echo "  Logi watchdog:       tail -f /var/log/usacar-watchdog.log"
echo "  Następne uruchomienia: sudo systemctl list-timers usacar-watchdog.timer"
echo "  Manual probe:        sudo /usr/local/bin/usacar-watchdog.sh"
echo ""
echo "Konfiguracja (override w drop-in):"
echo "  sudo systemctl edit usacar-watchdog.service"
echo "    [Service]"
echo "    Environment=USACAR_HEALTH_URL=http://127.0.0.1:8000/health"
echo "    Environment=USACAR_WATCHDOG_TIMEOUT=10"
echo ""
echo "Aby wyłączyć:"
echo "  sudo systemctl stop usacar-watchdog.timer"
echo "  sudo systemctl disable usacar-watchdog.timer"
