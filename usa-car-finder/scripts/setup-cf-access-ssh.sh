#!/usr/bin/env bash
#
# Tworzy Cloudflare Zero Trust Access (self-hosted app + service-token policy)
# dla ssh.moneybitches.organof.org — żeby `cloudflared access ssh` działało
# NIEINTERAKTYWNIE (bez przeglądarkowego SSO). To brakujący element przez
# który CF-SSH dawał "tls: handshake failure": tunel ingress + DNS już są
# (setup-ssh-over-cloudflare.sh), ale edge nie wiedział że hostname to
# aplikacja SSH dopóki nie ma Access app.
#
# Po sukcesie wypisuje SERVICE TOKEN (Client-Id/Secret) do wklejenia po
# stronie klienta (Mac) — od tego momentu deploy/E2E w pełni autonomiczne.
#
# Uruchom RAZ na WSL2:
#   CF_API_TOKEN=xxxxx bash scripts/setup-cf-access-ssh.sh
#
# Token Cloudflare (My Profile → API Tokens → Create): uprawnienia
#   - Account › Access: Apps and Policies › Edit
#   - Account › Access: Service Tokens › Edit
#   (scope: konto z tym tunelem). Token NIE jest nigdzie zapisywany.
#
set -euo pipefail

SSH_HOSTNAME="${SSH_HOSTNAME:-ssh.moneybitches.organof.org}"
APP_NAME="${APP_NAME:-wsl2-ssh}"
TOKEN_NAME="${TOKEN_NAME:-wsl2-ssh-svc}"
CF_API="https://api.cloudflare.com/client/v4"

log() { printf '[cf-access-ssh] %s\n' "$*"; }
die() { printf '[cf-access-ssh][ERROR] %s\n' "$*" >&2; exit 1; }

command -v curl >/dev/null 2>&1 || die "curl nie znaleziony"
command -v jq   >/dev/null 2>&1 || die "jq nie znaleziony (sudo apt install -y jq)"
[ -n "${CF_API_TOKEN:-}" ] || die "Brak CF_API_TOKEN w env"

auth=(-H "Authorization: Bearer $CF_API_TOKEN" -H "Content-Type: application/json")

cf() {  # cf METHOD PATH [JSON_BODY]
  local m="$1" p="$2" b="${3:-}"
  if [ -n "$b" ]; then
    curl -s -X "$m" "${auth[@]}" -d "$b" "$CF_API$p"
  else
    curl -s -X "$m" "${auth[@]}" "$CF_API$p"
  fi
}

ok() { echo "$1" | jq -e '.success == true' >/dev/null 2>&1; }

# --- 1. Account ID (auto-discover) ---
ACCOUNTS="$(cf GET /accounts)"
ok "$ACCOUNTS" || die "Nie mogę pobrać kont (sprawdź uprawnienia tokena): $(echo "$ACCOUNTS" | jq -c '.errors')"
ACCOUNT_ID="${CF_ACCOUNT_ID:-$(echo "$ACCOUNTS" | jq -r '.result[0].id')}"
[ -n "$ACCOUNT_ID" ] && [ "$ACCOUNT_ID" != "null" ] || die "Nie ustaliłem ACCOUNT_ID"
log "Account: $ACCOUNT_ID"

# --- 2. Service token (idempotent po nazwie) ---
TOKS="$(cf GET "/accounts/$ACCOUNT_ID/access/service_tokens")"
ok "$TOKS" || die "Service tokens list fail: $(echo "$TOKS" | jq -c '.errors')"
EXIST_TOK_ID="$(echo "$TOKS" | jq -r --arg n "$TOKEN_NAME" '.result[]|select(.name==$n)|.id' | head -1)"
if [ -n "$EXIST_TOK_ID" ] && [ "$EXIST_TOK_ID" != "null" ]; then
  log "Service token '$TOKEN_NAME' już istnieje (id=$EXIST_TOK_ID)."
  log "UWAGA: sekret pokazywany jest tylko przy tworzeniu. Jeśli go nie masz,"
  log "       zmień TOKEN_NAME i uruchom ponownie aby wygenerować nowy."
  CLIENT_ID="$(echo "$TOKS" | jq -r --arg n "$TOKEN_NAME" '.result[]|select(.name==$n)|.client_id')"
  TOKEN_UUID="$(echo "$TOKS" | jq -r --arg n "$TOKEN_NAME" '.result[]|select(.name==$n)|.id')"
  CLIENT_SECRET="(istniejący — nieodczytywalny; użyj nowego TOKEN_NAME by wygenerować)"
else
  NEW="$(cf POST "/accounts/$ACCOUNT_ID/access/service_tokens" "{\"name\":\"$TOKEN_NAME\"}")"
  ok "$NEW" || die "Tworzenie service token fail: $(echo "$NEW" | jq -c '.errors')"
  CLIENT_ID="$(echo "$NEW" | jq -r '.result.client_id')"
  CLIENT_SECRET="$(echo "$NEW" | jq -r '.result.client_secret')"
  TOKEN_UUID="$(echo "$NEW" | jq -r '.result.id')"
  log "Service token utworzony: $TOKEN_NAME"
fi
[ -n "$TOKEN_UUID" ] && [ "$TOKEN_UUID" != "null" ] || die "Brak service token UUID (id)"

# --- 3. Self-hosted Access app dla SSH hostname (idempotent po domenie) ---
APPS="$(cf GET "/accounts/$ACCOUNT_ID/access/apps")"
ok "$APPS" || die "Apps list fail: $(echo "$APPS" | jq -c '.errors')"
APP_ID="$(echo "$APPS" | jq -r --arg d "$SSH_HOSTNAME" '.result[]|select(.domain==$d)|.id' | head -1)"
APP_BODY="$(jq -n --arg n "$APP_NAME" --arg d "$SSH_HOSTNAME" \
  '{name:$n,domain:$d,type:"self_hosted",session_duration:"24h",
    app_launcher_visible:false,skip_interstitial:true,
    http_only_cookie_attribute:true}')"
if [ -n "$APP_ID" ] && [ "$APP_ID" != "null" ]; then
  R="$(cf PUT "/accounts/$ACCOUNT_ID/access/apps/$APP_ID" "$APP_BODY")"
  ok "$R" || die "App update fail: $(echo "$R" | jq -c '.errors')"
  log "Access app zaktualizowana (id=$APP_ID)"
else
  R="$(cf POST "/accounts/$ACCOUNT_ID/access/apps" "$APP_BODY")"
  ok "$R" || die "App create fail: $(echo "$R" | jq -c '.errors')"
  APP_ID="$(echo "$R" | jq -r '.result.id')"
  log "Access app utworzona (id=$APP_ID)"
fi

# --- 4. Policy: pozwól TYLKO temu service tokenowi ---
# UWAGA: reguła service_token wymaga UUID tokenu (.id), NIE client_id.
POL_BODY="$(jq -n --arg tid "$TOKEN_UUID" \
  '{name:"allow-svc-token",decision:"non_identity",
    include:[{service_token:{token_id:$tid}}]}')"
POLS="$(cf GET "/accounts/$ACCOUNT_ID/access/apps/$APP_ID/policies")"
POL_ID="$(echo "$POLS" | jq -r '.result[]|select(.name=="allow-svc-token")|.id' | head -1)"
if [ -n "$POL_ID" ] && [ "$POL_ID" != "null" ]; then
  R="$(cf PUT "/accounts/$ACCOUNT_ID/access/apps/$APP_ID/policies/$POL_ID" "$POL_BODY")"
  ok "$R" || die "Policy update fail: $(echo "$R" | jq -c '.errors')"
  log "Policy zaktualizowana"
else
  R="$(cf POST "/accounts/$ACCOUNT_ID/access/apps/$APP_ID/policies" "$POL_BODY")"
  ok "$R" || die "Policy create fail: $(echo "$R" | jq -c '.errors')"
  log "Policy utworzona (allow service token)"
fi

cat <<EOF

================================================================
 GOTOWE — Cloudflare Access SSH aktywny dla $SSH_HOSTNAME
================================================================
 CF_ACCESS_CLIENT_ID    = $CLIENT_ID
 CF_ACCESS_CLIENT_SECRET= $CLIENT_SECRET

 Klient (Mac) łączy się NIEINTERAKTYWNIE:
   ssh -o ProxyCommand="cloudflared access ssh --hostname %h \\
        --service-token-id $CLIENT_ID \\
        --service-token-secret <SECRET>" \\
       -i ~/.ssh/id_ed25519_to_wsl2 dawid@$SSH_HOSTNAME

 (cloudflared >=2024 czyta też env CF_ACCESS_CLIENT_ID/SECRET.)
 Skopiuj SECRET teraz — Cloudflare NIE pokaże go ponownie.
================================================================
EOF
