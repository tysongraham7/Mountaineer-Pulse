"""
Mountaineer Pulse - Football Transfer Portal Loader (CFBD)
=========================================================
Pulls WVU football transfer-portal moves from the College Football Data API
and writes them into the roster_moves table (which feeds the Team -> Movement
tab). Each move carries the player's OTHER school (where they came from for an
incoming transfer, where they went for an outgoing one).

This is the authoritative, grounded source for football portal moves. The
curated roster_moves.json still owns the things CFBD's portal feed does NOT
cover -- high-school recruits, NFL-draft departures, and basketball/baseball.

CFBD "portal" rows managed here use ids prefixed "pt-", so re-running fully
refreshes them (players who withdraw drop off) without touching curated rows.
To avoid showing a player twice, any curated football row that matches a CFBD
portal move by name+direction is deleted (CFBD's data wins -- it has schools).

Prereqs: .env has CFBD_API_KEY, SUPABASE_URL, SUPABASE_SECRET_KEY.
Run:  python sync_transfers.py
"""

import hashlib
import os
import sys

import requests
from dotenv import load_dotenv
from supabase import create_client

from names import canonical, same_person

load_dotenv()

CFBD_KEY = os.getenv("CFBD_API_KEY")
SB_URL = os.getenv("SUPABASE_URL")
SB_KEY = os.getenv("SUPABASE_SECRET_KEY")

BASE = "https://api.collegefootballdata.com"
TEAM = "West Virginia"
SEASONS = [2026]          # portal cycle(s) to show (this past Dec/Jan + spring)
SPORT = "football"


def die(msg: str) -> None:
    print(f"\n[X] {msg}")
    sys.exit(1)


def cfbd(path: str, params: dict) -> list:
    headers = {"Authorization": f"Bearer {CFBD_KEY}"}
    r = requests.get(f"{BASE}{path}", headers=headers, params=params, timeout=30)
    if r.status_code != 200:
        die(f"CFBD {path} failed: HTTP {r.status_code} - {r.text[:200]}")
    return r.json()


def main() -> None:
    for name, val in [("CFBD_API_KEY", CFBD_KEY), ("SUPABASE_URL", SB_URL),
                      ("SUPABASE_SECRET_KEY", SB_KEY)]:
        if not val:
            die(f"Missing {name} in .env")

    sb = create_client(SB_URL, SB_KEY)

    # The scraped roster is the naming authority -- it's what's on the jersey. CFBD
    # sends legal names ("Ezekiel Durham-Campbell" for #18 Zeke), and an exact-string
    # join would file him as a second player: duplicated on the roster, and cut off
    # from his previous-school stats, which attach by roster id.
    roster_names = [
        f"{p.get('first_name') or ''} {p.get('last_name') or ''}".strip()
        for p in (sb.table("players").select("first_name,last_name")
                  .eq("sport_id", SPORT).execute().data or [])
    ]
    renamed = []

    rows = []
    seen = set()
    for season in SEASONS:
        for d in cfbd("/player/portal", {"year": season}):
            origin = d.get("origin")
            dest = d.get("destination")
            if origin != TEAM and dest != TEAM:
                continue
            first = (d.get("firstName") or "").strip()
            last = (d.get("lastName") or "").strip()
            name = f"{first} {last}".strip()
            if not name:
                continue
            # Only incoming players are on our roster; a departure's name has no
            # local authority to reconcile against.
            direction = "in" if dest == TEAM else "out"
            if direction == "in":
                roster_spelling = canonical(name, roster_names)
                if roster_spelling and roster_spelling != name:
                    renamed.append(f"{name} -> {roster_spelling}")
                    name = roster_spelling
            other_school = origin if direction == "in" else dest

            note_parts = []
            if d.get("stars"):
                note_parts.append(f"{d['stars']}★")
            if d.get("eligibility"):
                note_parts.append(f"{d['eligibility']} eligibility")

            move_date = d.get("transferDate")
            if move_date:
                move_date = move_date[:10]  # roster_moves.move_date is a DATE

            uid = "pt-" + hashlib.md5(
                f"{season}|{name}|{origin}|{dest}".encode()
            ).hexdigest()[:16]

            rows.append({
                "id": uid,
                "sport_id": SPORT,
                "player_name": name,
                "position": d.get("position") or None,
                "class_year": None,
                "direction": direction,
                "category": "transfer",
                "status": "committed" if direction == "in" else "entered",
                "other_school": other_school or None,
                "move_date": move_date,
                "source_name": "Transfer Portal",
                "source_url": None,
                "notes": " · ".join(note_parts) or None,
            })
            seen.add((name, direction))

    # Refresh CFBD-managed rows: wipe old "pt-" football rows, then insert fresh.
    sb.table("roster_moves").delete().eq("sport_id", SPORT).like("id", "pt-%").execute()
    if rows:
        sb.table("roster_moves").upsert(rows).execute()

    # De-dupe: drop any curated football row that CFBD now covers. Matching by name
    # variant, not exact string -- a curated "Jaire Rawlison" and CFBD's "Jaire
    # Rawlinson" are one cornerback, and an exact compare kept both.
    removed = 0
    existing = sb.table("roster_moves").select("id,player_name,direction").eq(
        "sport_id", SPORT).execute().data or []
    for r in existing:
        if str(r["id"]).startswith("pt-"):
            continue
        if any(d == r["direction"] and same_person(n, r["player_name"]) for n, d in seen):
            sb.table("roster_moves").delete().eq("id", r["id"]).execute()
            removed += 1

    ins = sum(1 for r in rows if r["direction"] == "in")
    outs = sum(1 for r in rows if r["direction"] == "out")
    print(f"roster_moves -> {len(rows)} football portal moves  (+{ins} in / -{outs} out)")
    if renamed:
        print(f"              reconciled {len(renamed)} name(s) to the roster spelling:")
        for r in renamed:
            print(f"                 {r}")
    if removed:
        print(f"              removed {removed} curated duplicate(s) now covered by CFBD")
    print("\n[OK] Football transfers synced to Supabase.")


if __name__ == "__main__":
    main()
