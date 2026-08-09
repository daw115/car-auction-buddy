#!/usr/bin/env python3
"""Wystawia tokeny JWT, których PostgREST używa zamiast kluczy Supabase.

    PGRST_JWT_SECRET=... ./mint-jwt.py [lata_waznosci]

Wypisuje dwa tokeny HS256 z claimem `role`:
  service_role -> SUPABASE_SERVICE_ROLE_KEY  (obchodzi RLS, używa go supabaseAdmin)
  anon         -> SUPABASE_PUBLISHABLE_KEY   (hook cases-refresh)

Bez zależności zewnętrznych — sam hmac ze standardowej biblioteki.
Domyślna ważność to 2 lata, nie 10: token bez realnego terminu to dług,
który nikt nigdy nie spłaca. Datę wygaśnięcia zapisz w runbooku.
"""

import base64
import hashlib
import hmac
import json
import os
import sys
import time


def b64(raw: bytes) -> bytes:
    return base64.urlsafe_b64encode(raw).rstrip(b"=")


def mint(secret: bytes, role: str, valid_seconds: int) -> str:
    header = b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    now = int(time.time())
    payload = b64(
        json.dumps(
            {"role": role, "iss": "usacar-selfhost", "iat": now, "exp": now + valid_seconds},
            separators=(",", ":"),
        ).encode()
    )
    signing_input = header + b"." + payload
    signature = b64(hmac.new(secret, signing_input, hashlib.sha256).digest())
    return (signing_input + b"." + signature).decode()


def main() -> int:
    secret = os.environ.get("PGRST_JWT_SECRET", "")
    if len(secret) < 32:
        print("PGRST_JWT_SECRET musi mieć co najmniej 32 znaki.", file=sys.stderr)
        return 1

    years = float(sys.argv[1]) if len(sys.argv) > 1 else 2.0
    valid_seconds = int(years * 365 * 24 * 3600)
    expires_at = time.strftime("%Y-%m-%d", time.gmtime(time.time() + valid_seconds))

    raw = secret.encode()
    print(f"# tokeny wygasają {expires_at} — wpisz tę datę do runbooka")
    print(f"SUPABASE_SERVICE_ROLE_KEY={mint(raw, 'service_role', valid_seconds)}")
    print(f"SUPABASE_PUBLISHABLE_KEY={mint(raw, 'anon', valid_seconds)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
