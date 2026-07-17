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
import unicodedata

from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

SB_URL = os.getenv("SUPABASE_URL")
SB_KEY = os.getenv("SUPABASE_SECRET_KEY")
HERE = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(HERE, "depth_chart.json")

VALID_STATUS = {"active", "questionable", "doubtful", "out"}


def norm_name(name: str) -> str:
    """Loose key so depth entries and roster_moves match despite accents/punctuation."""
    s = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode()
    return " ".join(s.lower().replace(".", " ").replace("'", "").replace("-", " ").split())


def departed_keys(sb) -> set[tuple[str, str]]:
    """(sport_id, normalized name) for players with a CONFIRMED departure — so a drafted/
    transferred/graduated player can't linger in the depth chart. 'draft-pending' is NOT
    confirmed (decision still open), so those players stay. This is what makes marking a
    player out in roster_moves cascade to the depth chart automatically. Relies on
    sync_moves.py running earlier in the pipeline so roster_moves is already current."""
    rows = sb.table("roster_moves").select("player_name,sport_id,direction,category").eq(
        "direction", "out").execute().data or []
    return {
        (r["sport_id"], norm_name(r["player_name"]))
        for r in rows
        if r.get("category") != "draft-pending" and r.get("player_name")
    }


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

    gone = departed_keys(sb)
    dropped = []
    rows = []
    for e in entries:
        name = (e.get("player_name") or "").strip()
        pos = (e.get("position") or "").strip()
        if not name or not pos:
            print(f"  skipping invalid entry: {e}")
            continue
        # Cascade: a confirmed departure removes the player from the depth chart, even if
        # they're still listed in depth_chart.json (keeps movement/roster/depth in sync).
        if (e.get("sport_id"), norm_name(name)) in gone:
            dropped.append(f"{name} ({e.get('sport_id')})")
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
    if dropped:
        print(f"   dropped {len(dropped)} departed: {', '.join(dropped)}")
    print("\n[OK] Depth chart synced to Supabase.")


if __name__ == "__main__":
    main()
