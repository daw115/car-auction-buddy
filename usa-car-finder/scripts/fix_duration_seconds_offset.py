"""Migration script: naprawia duration_seconds dla legacy rekordów (offset +7200s).

PRZED commitem fixującym timezone (api/_time_utils.py), `duration_seconds`
był liczony jako `naive_local_now - naive_utc_started` = real_duration + 7200s
w strefie CEST/CET (UTC+2).

Ten skrypt:
1. Wykrywa offset (utcoffset systemu w momencie historycznego zapisu)
2. Skanuje `search_records.duration_seconds` w SQLite
3. Odejmuje offset od rekordów które wyglądają na "skażone"
   (heurystyka: duration > UTC_OFFSET_S - jeśli nie, prawdopodobnie real run < 2h)
4. Wypisuje co zmienił. Idempotentny w sensie: oznacza rekordy w `notes`
   żeby nie ruszać ich dwa razy.

URUCHOMIENIE:
    cd /home/dawid/usacar/usa-car-finder
    ./venv/bin/python3 scripts/fix_duration_seconds_offset.py --dry-run
    ./venv/bin/python3 scripts/fix_duration_seconds_offset.py --apply

UWAGA: Skrypt zakłada że wszystkie skażone rekordy zostały zapisane w jednej
strefie czasowej (CEST/CET = UTC+1 lub UTC+2). Jeśli serwer zmieniał strefy,
trzeba przejrzeć ręcznie.
"""
import argparse
import os
import sqlite3
import sys
import time
from pathlib import Path

# UTC offset w sekundach (Europe/Warsaw):
# - CET (zima):  UTC+1 = 3600s
# - CEST (lato): UTC+2 = 7200s
# Wszystkie zaobserwowane bug values miały offset 7200s (lato).
DEFAULT_OFFSET_S = 7200

DB_PATH = Path(os.getenv("APP_DATABASE_PATH", "./data/app.db"))


def detect_offset() -> int:
    """Aktualne UTC offset systemu (sekund). Daje +7200 latem (CEST), +3600 zimą."""
    return -time.timezone + (3600 if time.daylight else 0)


def main() -> int:
    parser = argparse.ArgumentParser(description="Fix duration_seconds offset")
    parser.add_argument("--apply", action="store_true", help="Apply changes (default: dry run)")
    parser.add_argument("--dry-run", action="store_true", help="Alias dla braku --apply (no-op flag for clarity)")
    parser.add_argument("--offset", type=int, default=None,
                        help=f"UTC offset w sekundach do odjęcia (default: auto-detect, fallback {DEFAULT_OFFSET_S})")
    parser.add_argument("--threshold", type=int, default=None,
                        help="Minimalna duration_seconds żeby uznać za skażoną (default: offset)")
    parser.add_argument("--db", type=str, default=str(DB_PATH), help=f"DB path (default: {DB_PATH})")
    args = parser.parse_args()

    offset = args.offset if args.offset is not None else detect_offset()
    if offset <= 0:
        offset = DEFAULT_OFFSET_S
    threshold = args.threshold if args.threshold is not None else offset

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"[ERROR] DB not found: {db_path}", file=sys.stderr)
        return 1

    print(f"=== Fix duration_seconds offset ===")
    print(f"DB:        {db_path}")
    print(f"Offset:    -{offset}s (UTC offset detected: {detect_offset()}s)")
    print(f"Threshold: duration_seconds > {threshold}s (rekordy z mniejszym są ignorowane)")
    print(f"Mode:      {'APPLY (changes)' if args.apply else 'DRY RUN'}")
    print()

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    # Znajdź rekordy ze skażoną duration_seconds
    rows = conn.execute(
        "SELECT id, title, status, duration_seconds, created_at "
        "FROM search_records "
        "WHERE duration_seconds IS NOT NULL AND duration_seconds > ?",
        (threshold,),
    ).fetchall()

    if not rows:
        print(f"[OK] No records with duration_seconds > {threshold}s — nothing to fix.")
        return 0

    print(f"Found {len(rows)} candidates:")
    print()
    print(f"{'id':>6} {'status':<12} {'old (s)':>10} {'new (s)':>10}  title")
    print("-" * 100)

    fixes: list[tuple[int, float, float]] = []
    for r in rows:
        old = float(r["duration_seconds"])
        new = old - offset
        if new < 0:
            print(f"{r['id']:>6} {r['status']:<12} {old:>10.1f} {new:>10.1f}  [SKIP: negative result] {r['title'][:50]}")
            continue
        fixes.append((r["id"], old, new))
        print(f"{r['id']:>6} {r['status']:<12} {old:>10.1f} {new:>10.1f}  {r['title'][:50]}")

    print()
    print(f"Total fixable: {len(fixes)}/{len(rows)}")

    if args.apply:
        for rec_id, _old, new in fixes:
            conn.execute("UPDATE search_records SET duration_seconds = ? WHERE id = ?", (new, rec_id))
        conn.commit()
        print(f"[OK] Updated {len(fixes)} rows.")
    else:
        print("[DRY RUN] No changes applied. Use --apply to commit.")

    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
