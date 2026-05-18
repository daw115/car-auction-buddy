#!/usr/bin/env bash
#
# Permanent fix dla niestabilnego reverse autossh tunelu (WSL2 → Mac:2222).
#
# Problem: autossh celuje w hardcoded LAN IP Maca (np. 192.168.0.158). Gdy Mac
# zmieni sieć/IP, tunel pada i deploy jest zablokowany aż ktoś ręcznie poprawi
# IP w ~/.config/systemd/user/autossh-mac-tunnel.service.
#
# Rozwiązanie: dołożyć ingress SSH do JUŻ DZIAŁAJĄCEGO named cloudflared tunelu
# (ten sam co serwuje moneybitches.organof.org). Mac łączy się przez
# `cloudflared access ssh` — niezależnie od LAN/IP, bez reverse tunelu.
#
# BEZPIECZEŃSTWO (nie psujemy produkcyjnego HTTP tunelu):
#   - backup configu przed zmianą
#   - `cloudflared tunnel ingress validate` przed restartem
#   - po restarcie sprawdza HTTP /health; gdy padł → automatyczny ROLLBACK
#   - idempotentny: ponowne uruchomienie nie duplikuje reguł
#
# Uruchom RAZ na WSL2:  bash scripts/setup-ssh-over-cloudflare.sh
# Dry-run (tylko pokazuje co zrobi):  DRY_RUN=1 bash scripts/setup-ssh-over-cloudflare.sh
#
set -euo pipefail

SSH_HOSTNAME="${SSH_HOSTNAME:-ssh.moneybitches.organof.org}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8000/health}"
DRY_RUN="${DRY_RUN:-0}"
# Po restarcie cloudflared named-tunel potrzebuje czasu na re-establish edge
# connection. Pojedynczy `sleep 6; curl` dawał FAŁSZYWY rollback (tunel
# wstawał >6s → /health chwilowo !=200 → cofnięcie ingressu SSH mimo że
# config był poprawny). Retry z backoffem: akceptuj na pierwszym 200.
HEALTH_RETRIES="${HEALTH_RETRIES:-10}"
HEALTH_INTERVAL="${HEALTH_INTERVAL:-6}"

log() { printf '[setup-ssh-cf] %s\n' "$*"; }
die() { printf '[setup-ssh-cf][ERROR] %s\n' "$*" >&2; exit 1; }
run() { if [ "$DRY_RUN" = "1" ]; then log "DRY: $*"; else eval "$@"; fi; }

command -v cloudflared >/dev/null 2>&1 || die "cloudflared nie znaleziony w PATH"

# --- 1. Wykryj config cloudflared ---
CFG=""
for c in /etc/cloudflared/config.yml /etc/cloudflared/config.yaml \
         "$HOME/.cloudflared/config.yml" "$HOME/.cloudflared/config.yaml"; do
  [ -f "$c" ] && CFG="$c" && break
done
[ -n "$CFG" ] || die "Nie znaleziono config.yml cloudflared (sprawdź /etc/cloudflared/ lub ~/.cloudflared/)"
log "Config cloudflared: $CFG"

TUNNEL_NAME="$(grep -E '^tunnel:' "$CFG" | head -1 | awk '{print $2}' | tr -d '\"' || true)"
[ -n "$TUNNEL_NAME" ] || die "Nie odczytałem nazwy tunelu z $CFG (klucz 'tunnel:')"
log "Tunel: $TUNNEL_NAME ; ingress hostname docelowy: $SSH_HOSTNAME"

# --- 2. Idempotencja: już skonfigurowane? ---
if grep -q "$SSH_HOSTNAME" "$CFG"; then
  log "Ingress dla $SSH_HOSTNAME już istnieje w configu — pomijam edycję configu."
else
  # --- 3. Backup ---
  BACKUP="${CFG}.bak.$(date +%s)"
  run "cp '$CFG' '$BACKUP'"
  log "Backup configu: $BACKUP"

  # --- 4. Wstrzyknij regułę ingress PRZED catch-all (http_status:404) ---
  # Zakłada standardowy blok 'ingress:' z regułą service: http_status:404 na końcu.
  if ! grep -qE '^\s*ingress:' "$CFG"; then
    die "Config nie ma bloku 'ingress:' — pomijam (ręczna konfiguracja wymagana)"
  fi
  TMP="$(mktemp)"
  awk -v host="$SSH_HOSTNAME" '
    /^\s*- service:\s*http_status:404/ && !done {
      print "  - hostname: " host;
      print "    service: ssh://localhost:22";
      done=1
    }
    { print }
  ' "$CFG" > "$TMP"
  run "cp '$TMP' '$CFG'"
  rm -f "$TMP"
  log "Dodano ingress: $SSH_HOSTNAME → ssh://localhost:22"
fi

# --- 5. Walidacja configu ZANIM ruszymy produkcyjny tunel ---
if [ "$DRY_RUN" != "1" ]; then
  cloudflared tunnel ingress validate >/dev/null 2>&1 \
    || die "cloudflared ingress validate FAILED — config NIE zostanie zastosowany (przywróć $BACKUP)"
  log "cloudflared ingress validate OK"
fi

# --- 6. DNS route (cloudflared jest już auth'owany na tym hoście) ---
run "cloudflared tunnel route dns '$TUNNEL_NAME' '$SSH_HOSTNAME' || true"

# --- 7. Restart + weryfikacja że produkcyjny HTTP nadal żyje ---
# Retry health zamiast pojedynczego sleep — eliminuje fałszywy rollback gdy
# cloudflared re-establish edge wolniej niż 6s (przyczyna poprzedniej porażki).
if [ "$DRY_RUN" != "1" ]; then
  sudo systemctl restart cloudflared
  code="000"
  for attempt in $(seq 1 "$HEALTH_RETRIES"); do
    sleep "$HEALTH_INTERVAL"
    code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 8 "$HEALTH_URL" || echo 000)"
    if [ "$code" = "200" ]; then
      log "PROD HTTP /health = 200 (próba $attempt/$HEALTH_RETRIES) — tunel HTTP nienaruszony ✓"
      break
    fi
    log "health=$code (próba $attempt/$HEALTH_RETRIES) — czekam na re-establish cloudflared..."
  done
  if [ "$code" != "200" ]; then
    log "PROD HEALTH = $code po $HEALTH_RETRIES próbach — ROLLBACK configu"
    [ -n "${BACKUP:-}" ] && cp "$BACKUP" "$CFG" && sudo systemctl restart cloudflared
    die "Rollback wykonany (HTTP tunel realnie padł). SSH-over-CF NIE aktywowane."
  fi
  # Sanity: potwierdź że ingress SSH faktycznie jest w działającym configu
  # (gdyby idempotency/edycja zawiodła — lepiej wiedzieć teraz niż przy ssh).
  if ! grep -q "$SSH_HOSTNAME" "$CFG"; then
    die "Config nie zawiera $SSH_HOSTNAME po restarcie — ingress nieaktywny (sprawdź $CFG)"
  fi
  log "Ingress SSH potwierdzony w configu ($SSH_HOSTNAME) ✓"
fi

cat <<EOF

================================================================
 GOTOWE. SSH-over-Cloudflare aktywny: $SSH_HOSTNAME
================================================================
 Na MACU (jednorazowo) dodaj do ~/.ssh/config:

   Host wsl2-cf
       HostName $SSH_HOSTNAME
       User dawid
       IdentityFile ~/.ssh/id_ed25519_to_wsl2
       ProxyCommand cloudflared access ssh --hostname %h

 Wymaga na Macu: brew install cloudflared (raz).
 Potem deploy działa zawsze, niezależnie od LAN/IP:
   ssh wsl2-cf 'cd ~/usacar/usa-car-finder && git pull'

 Stary reverse autossh tunel (2222) staje się zbędny.
================================================================
EOF
