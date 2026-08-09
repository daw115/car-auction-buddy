#!/bin/bash
# Watchdog dla usacar: sprawdza backend i dashboard, restartuje przy awarii.
#
# Strategie (osobne liczniki dla kazdej uslugi):
# 1. Sprawdza endpoint z timeoutem
# 2. Liczy nieudane proby w /tmp/usacar-watchdog-fail-<usluga>
# 3. Po 2 z rzedu -> restart uslugi (unika falszywych alarmow)
# 4. Po 3 z rzedu -> restart takze cloudflared (zerwany tunel)
# 5. Sukces zeruje licznik
#
# Dashboard sondowany przez /api/version, NIE /api/health. /api/health wola
# Postgresa i FastAPI, wiec chory backend restartowalby zdrowy dashboard.
#
# Output -> syslog (journalctl -t usacar-watchdog) + /var/log/usacar-watchdog.log

set -euo pipefail

TIMEOUT="${USACAR_WATCHDOG_TIMEOUT:-10}"
LOG_FILE="/var/log/usacar-watchdog.log"
SERVICE_RESTART_THRESHOLD=2
TUNNEL_RESTART_THRESHOLD=3

log() {
    local msg="$1"
    local ts
    ts="$(date '+%Y-%m-%d %H:%M:%S')"
    echo "[$ts] $msg" | tee -a "$LOG_FILE" >&2
    logger -t usacar-watchdog "$msg"
}

# check <nazwa-uslugi> <url>
check() {
    local svc="$1" url="$2"
    local counter="/tmp/usacar-watchdog-fail-$svc"
    local fail_count=0
    [[ -f "$counter" ]] && fail_count="$(cat "$counter" 2>/dev/null || echo 0)"

    # curl przy braku polaczenia sam wypisuje 000 i konczy sie bledem, wiec
    # `|| echo 000` dokleilo by drugie 000 (stary skrypt logowal "000TIMEOUT").
    local http_code
    http_code="$(curl -s -o /dev/null -w '%{http_code}' --max-time "$TIMEOUT" "$url" 2>/dev/null)" || true
    [[ -z "$http_code" ]] && http_code="000"

    if [[ "$http_code" == "200" ]]; then
        if [[ "$fail_count" -gt 0 ]]; then
            log "$svc OK (200) — zdrowy po $fail_count nieudanych probach (reset)"
            echo 0 > "$counter"
        fi
        return 0
    fi

    fail_count=$((fail_count + 1))
    echo "$fail_count" > "$counter"
    log "$svc FAIL ($http_code) — proba $fail_count/$TUNNEL_RESTART_THRESHOLD"

    if [[ "$fail_count" -ge "$TUNNEL_RESTART_THRESHOLD" ]]; then
        log "$svc RESTART (+tunel): restartuje $svc ORAZ cloudflared"
        systemctl restart "$svc" || log "ERROR: restart $svc nieudany"
        systemctl restart cloudflared || log "ERROR: restart cloudflared nieudany"
        echo 0 > "$counter"
    elif [[ "$fail_count" -ge "$SERVICE_RESTART_THRESHOLD" ]]; then
        log "$svc RESTART: restartuje $svc"
        systemctl restart "$svc" || log "ERROR: restart $svc nieudany"
    fi
    return 0
}

check usacar-api       "${USACAR_HEALTH_URL:-http://127.0.0.1:8000/health}"
check usacar-dashboard "${USACAR_DASHBOARD_URL:-http://127.0.0.1:3000/api/version}"

exit 0
