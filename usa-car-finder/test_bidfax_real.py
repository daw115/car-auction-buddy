"""Realny test bidfax lookupu.

DWA TRYBY:

1. CDP attach (REKOMENDOWANE — obchodzi Cloudflare):
     # Terminal 1:
     bash bidfax_chrome_debug.sh
     # → otworzy Chrome, wejdź na bidfax.info, przejdź CF, zostaw otwarte

     # Terminal 2:
     BIDFAX_CHROME_CDP_URL=http://localhost:9222 python3 test_bidfax_real.py

2. Persistent profile (eksperymentalne — może blokować CF):
     python3 test_bidfax_real.py
     # (wymaga uprzedniego `python3 bidfax_warmup.py`)
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

os.environ.setdefault("BIDFAX_ENRICHMENT_ENABLED", "true")
os.environ.setdefault("BIDFAX_HEADLESS", "false")
os.environ.setdefault("BIDFAX_DEBUG_SCREENSHOTS", "true")
os.environ.setdefault(
    "CHROME_EXECUTABLE_PATH",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
)

from scraper.bidfax import lookup_with_cache  # noqa: E402

if os.getenv("BIDFAX_CHROME_CDP_URL"):
    print(f"[test] tryb CDP attach: {os.environ['BIDFAX_CHROME_CDP_URL']}")
else:
    print("[test] tryb persistent profile (jeśli CF blokuje — użyj CDP, patrz docstring)")

# 2 prawdziwe lot ID z poprzedniego runu Toyota Camry.
LOT_IDS = sys.argv[1:] or ["48483906", "49196666"]


async def main() -> int:
    print(f"[test] lookup {len(LOT_IDS)} lots: {LOT_IDS}")
    print("[test] timeout 300s na całość")
    try:
        result = await asyncio.wait_for(
            lookup_with_cache(
                LOT_IDS,
                Path("data/bidfax_cache.json"),
                makes={lot: "Toyota" for lot in LOT_IDS},
                delay=3.0,
            ),
            timeout=300,
        )
    except asyncio.TimeoutError:
        print("[test] TIMEOUT after 300s")
        return 1

    print()
    print("=" * 60)
    print("RESULTS")
    print("=" * 60)
    any_real = False
    for q, (price, vin, url) in result.items():
        marker = "  " if price == "In Progress" else "✓ "
        print(f"{marker}{q}: price={price!r}")
        if vin:
            print(f"    vin={vin}")
        if url:
            print(f"    url={url}")
        if price != "In Progress":
            any_real = True

    print()
    if any_real:
        print("[test] SUCCESS — bidfax zwrócił przynajmniej 1 finalną cenę")
        return 0
    print("[test] Wszystko In Progress — może bidfax nie ma tych lotów (są wciąż aktywne)")
    print("[test] Sprawdź logs/bidfax_*.html dla snapshotów odpowiedzi")
    return 0  # nie błąd — bidfax po prostu może nie indeksować świeżych lotów


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
