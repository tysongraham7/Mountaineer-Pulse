"""
Mountaineer Pulse - Roster Movement Loader
==========================================
Loads curated transfer portal moves from roster_moves.json into Supabase.
Edit roster_moves.json (add confirmed entries/commits) and re-run this to update.

Run:  python sync_moves.py
"""

import hashlib
import json
import os
import sys

from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

SB_URL = os.getenv("SUPABASE_URL")
SB_KEY = os.getenv("SUPABASE_SECRET_KEY")
HERE = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(HERE, "roster_moves.json")


def die(msg: str) -> None:
    print(f"\n[X] {msg}")
    sys.exit(1)


def main() -> None:
    if not SB_URL or not SB_KEY:
        die("Missing SUPABASE_URL or SUPABASE_SECRET_KEY in .env")
    with open(DATA_FILE, encoding="utf-8") as f:
        moves = json.load(f)

    sb = create_client(SB_URL, SB_KEY)
    rows = []
    for m in moves:
        name = m.get("player_name", "").strip()
        direction = m.get("direction", "").strip().lower()
        if not name or direction not in ("in", "out"):
            print(f"  skipping invalid entry: {m}")
            continue
        uid = hashlib.md5(f"{m.get('sport_id')}|{name}|{direction}".encode()).hexdigest()
        rows.append({
            "id": uid,
            "sport_id": m.get("sport_id"),
            "player_name": name,
            "position": m.get("position") or None,
            "class_year": m.get("class_year") or None,
            "direction": direction,
            "category": m.get("category") or "transfer",
            "status": m.get("status") or None,
            "other_school": m.get("other_school") or None,
            "move_date": m.get("move_date") or None,
            "source_name": m.get("source_name") or None,
            "source_url": m.get("source_url") or None,
            "notes": m.get("notes") or None,
        })

    # Rebuild curated rows so entries removed from the JSON also drop from the DB.
    # CFBD football portal rows (ids prefixed "pt-") are owned by sync_transfers.py,
    # so leave those alone.
    sb.table("roster_moves").delete().not_.like("id", "pt-%").execute()
    if rows:
        sb.table("roster_moves").upsert(rows).execute()

    ins = sum(1 for r in rows if r["direction"] == "in")
    outs = sum(1 for r in rows if r["direction"] == "out")
    print(f"roster_moves -> upserted {len(rows)} moves  (+{ins} in / -{outs} out)")
    print("\n[OK] Roster movement synced to Supabase.")


if __name__ == "__main__":
    main()
