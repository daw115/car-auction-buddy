#!/bin/bash
# Watchdog dla usacar-api: sprawdza /health co X min, restart gdy fail.
#
# Strategie:
# 1. Sprawdza GET http://127.0.0.1:8000/health z timeoutem 10s
# 2. Liczy failed checks w /tmp/usacar-watchdog-fail-count
# 3. Po 2 z rzędu failed → restart usacar-api (uniknięcie false positives)
# 4. Po 3 z rzędu failed → restart także cloudflared (tunel zerwany)
# 5. Sukces zeruje counter
#
# Output → syslog (journalctl -t usacar-watchdog) + /var/log/usacar-watchdog.log
#
# Wymaga sudo bez hasła dla `systemctl restart` (już jest gdy user sudo NOPASSWD).
set -euo pipefail

HEALTH_URL="${USACAR_HEALTH_URL:-http://127.0.0.1:8000/health}"
TIMEOUT="${USACAR_WATCHDOG_TIMEOUT:-10}"
FAIL_COUNTER="/tmp/usacar-watchdog-fail-count"
LOG_FILE="/var/log/usacar-watchdog.log"
SERVICE_RESTART_THRESHOLD=2  # 2 failed checks z rzędu → restart usacar-api
TUNNEL_RESTART_THRESHOLD=3   # 3 failed → także restart cloudflared

log() {
    local msg="$1"
    local ts="$(date '+%Y-%m-%d %H:%M:%S')"
    echo "[$ts] $msg" | tee -a "$LOG_FILE" >&2
    logger -t usacar-watchdog "$msg"
}

# Read current counter (default 0)
fail_count=0
if [[ -f "$FAIL_COUNTER" ]]; then
    fail_count="$(cat "$FAIL_COUNTER" 2>/dev/null || echo 0)"
fi

# Probe health endpoint
http_code="$(curl -s -o /dev/null -w "%{http_code}" --max-time "$TIMEOUT" "$HEALTH_URL" 2>/dev/null || echo "TIMEOUT")"

if [[ "$http_code" == "200" ]]; then
    # Healthy — reset counter
    if [[ "$fail_count" -gt 0 ]]; then
        log "OK ($http_code) — sesja zdrowa po $fail_count failed checks (reset)"
        echo 0 > "$FAIL_COUNTER"
    fi
    exit 0
fi

# Failed — increment counter
fail_count=$((fail_count + 1))
echo "$fail_count" > "$FAIL_COUNTER"
log "FAIL ($http_code) — failed check $fail_count/$TUNNEL_RESTART_THRESHOLD"

# Decide action based on count
if [[ "$fail_count" -ge "$TUNNEL_RESTART_THRESHOLD" ]]; then
    log "RESTART (tunnel): $fail_count failed checks — restartuję usacar-api ORAZ cloudflared"
    sudo systemctl restart usacar-api || log "ERROR: systemctl restart usacar-api failed"
    sudo systemctl restart cloudflared || log "ERROR: systemctl restart cloudflared failed"
    echo 0 > "$FAIL_COUNTER"
elif [[ "$fail_count" -ge "$SERVICE_RESTART_THRESHOLD" ]]; then
    log "RESTART (service): $fail_count failed checks — restartuję usacar-api"
    sudo systemctl restart usacar-api || log "ERROR: systemctl restart usacar-api failed"
fi

exit 0
