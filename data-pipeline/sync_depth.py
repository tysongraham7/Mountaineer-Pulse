"""
Mountaineer Pulse - Depth Chart Loader
======================================
Loads the curated projected depth chart from depth_chart.json into Supabase.
Edit depth_chart.json (reorder ranks, set status to 'out'/'questionable' for
injuries, add positions) and re-run to update.

Run:  python sync_depth.py
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
DATA_FILE = os.path.join(HERE, "depth_chart.json")

VALID_STATUS = {"active", "questionable", "doubtful", "out"}


def die(msg: str) -> None:
    print(f"\n[X] {msg}")
    sys.exit(1)


def main() -> None:
    if not SB_URL or not SB_KEY:
        die("Missing SUPABASE_URL or SUPABASE_SECRET_KEY in .env")
    with open(DATA_FILE, encoding="utf-8") as f:
        entries = json.load(f)

    sb = create_client(SB_URL, SB_KEY)
    # Fully curated table — rebuild it each run so reorders/removals take effect.
    sb.table("depth_chart").delete().neq("id", "___none___").execute()

    rows = []
    for e in entries:
        name = (e.get("player_name") or "").strip()
        pos = (e.get("position") or "").strip()
        if not name or not pos:
            print(f"  skipping invalid entry: {e}")
            continue
        status = (e.get("status") or "active").lower()
        if status not in VALID_STATUS:
            status = "active"
        season = e.get("season")
        uid = hashlib.md5(f"{e.get('sport_id')}|{season}|{pos}|{name}".encode()).hexdigest()
        rows.append({
            "id": uid,
            "sport_id": e.get("sport_id"),
            "season": season,
            "unit": e.get("unit") or None,
            "position": pos,
            "pos_order": e.get("pos_order") or 0,
            "rank": e.get("rank") or 1,
            "player_name": name,
            "class_year": e.get("class_year") or None,
            "status": status,
            "note": e.get("note") or None,
            "alert": e.get("alert") or None,
        })

    if rows:
        sb.table("depth_chart").upsert(rows).execute()

    by_sport: dict[str, int] = {}
    injured = sum(1 for r in rows if r["status"] != "active")
    for r in rows:
        by_sport[r["sport_id"]] = by_sport.get(r["sport_id"], 0) + 1
    print(f"depth_chart -> upserted {len(rows)} entries ({injured} with injury status)")
    for k, v in sorted(by_sport.items()):
        print(f"   {k:<10} {v}")
    print("\n[OK] Depth chart synced to Supabase.")


if __name__ == "__main__":
    main()
