"""
Mountaineer Pulse - Depth Chart Loader
======================================
Football comes from Ourlads every run (see ourlads.py). Basketball and baseball come
from depth_chart.json, which is still curated by hand.

For football, depth_chart.json holds OVERRIDES, not the chart. Ourlads decides who
plays where and in what order; an override adds what Ourlads is slow on or doesn't say:

  * an injury -- "status": "out" (or questionable/doubtful), with a note, and optionally
    the Pulse hit (pulse_delta + out_since). Ourlads often keeps a hurt player on the
    two-deep for days, or moves him to its reserve list, which the app doesn't show. If
    he's not at the override's position on Ourlads, he's put back there at the
    override's rank, struck through, so the fill-in reads as "proj. start".
  * a note or alert on a player who is on Ourlads' chart.
  * "pin": true -- keep a row Ourlads doesn't list (the fullback).

An override that is active, unpinned, and matches nothing on Ourlads is stale; it's
reported and skipped. If Ourlads can't be read, the football rows already in the
database are left as they are rather than blanked.

Run:  python sync_depth.py
"""

import hashlib
import json
import os
import sys
import unicodedata

from dotenv import load_dotenv
from supabase import create_client

import ourlads

load_dotenv()

SB_URL = os.getenv("SUPABASE_URL")
SB_KEY = os.getenv("SUPABASE_SECRET_KEY")
HERE = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(HERE, "depth_chart.json")

VALID_STATUS = {"active", "questionable", "doubtful", "out"}

# The order the app lists football positions in: quarterback first, then out from the
# ball, the way the hand-kept chart always read. Ourlads orders them by where they line
# up (receivers first), which scatters the position-group headers in the Full Depth list.
FB_ORDER = ["QB", "RB", "FB", "WR-X", "WR-Y", "WR-Z", "TE", "LT", "LG", "C", "RG", "RT",
            "DE", "NT", "DT", "BAN", "WLB", "MLB", "LCB", "RCB", "NB", "FS", "SS",
            "PK", "KO", "PT", "H", "LS", "PR", "KR"]
UNIT_OF = {p: "Offense" for p in FB_ORDER[:12]} | {p: "Defense" for p in FB_ORDER[12:23]} \
    | {p: "Special Teams" for p in FB_ORDER[23:]}
# A position code Ourlads adds that isn't listed above still shows, after the known ones
# in its unit, in Ourlads' order.
UNIT_BASE = {"Offense": 100, "Defense": 200, "Special Teams": 300}

# Fields an override carries onto the Ourlads row it matches.
OVERRIDE_FIELDS = ("status", "note", "alert", "pulse_delta", "out_since", "keep_despite_out")


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


def pos_order(position: str, unit: str | None, ourlads_row: int = 0) -> int:
    if position in FB_ORDER:
        return FB_ORDER.index(position) + 1
    return UNIT_BASE.get(unit or "", 400) + ourlads_row


def football_entries(chart: dict, overrides: list[dict]) -> tuple[list[dict], list[str]]:
    """Ourlads' two-deep with the curated overrides applied. Returns depth_chart.json-shaped
    entries (for the loop in main) and lines worth reading in the Actions log."""
    report: list[str] = []
    reserves = {norm_name(r["player_name"]): r for r in chart["rows"] if r["unit"] == "Reserves"}
    by_pos: dict[str, list[dict]] = {}
    for r in chart["rows"]:
        if r["unit"] == "Reserves":
            continue
        unit = UNIT_OF.get(r["position"], r["unit"])
        by_pos.setdefault(r["position"], []).append({
            "sport_id": "football", "season": None, "unit": unit,
            "position": r["position"], "pos_order": pos_order(r["position"], unit, r["row"]),
            "rank": r["rank"], "player_name": r["player_name"],
            "class_year": r["class_year"], "status": "active",
        })

    overridden: set[str] = set()
    for o in overrides:
        name, pos = (o.get("player_name") or "").strip(), (o.get("position") or "").strip()
        if not name or not pos:
            report.append(f"skipped an override with no player or position: {o}")
            continue
        key = norm_name(name)
        status = (o.get("status") or "active").lower()
        slot = by_pos.setdefault(pos, [])
        hit = next((e for e in slot if norm_name(e["player_name"]) == key), None)
        if hit:
            for f in OVERRIDE_FIELDS:
                if o.get(f) is not None:
                    hit[f] = o[f]
            if status in ("out", "doubtful"):
                # Worth a look, not an error: Ourlads is often days behind on an injury,
                # but this is also how it looks once he's healthy and the override is stale.
                report.append(f"{name} is still on Ourlads at {pos} #{hit['rank']} but marked "
                              f"{status} here — clear it in depth_chart.json once he's back")
        elif status != "active" or o.get("pin"):
            # Not at this position on Ourlads (hurt players usually drop to its reserve
            # list). Put him back where the override says, pushing the rest down one.
            rank = max(1, min(int(o.get("rank") or 1), len(slot) + 1))
            for e in slot:
                if e["rank"] >= rank:
                    e["rank"] += 1
            unit = o.get("unit") or UNIT_OF.get(pos)
            placed = {"sport_id": "football", "season": None, "unit": unit, "position": pos,
                      "pos_order": pos_order(pos, unit), "rank": rank, "player_name": name,
                      "class_year": o.get("class_year"), "status": "active"}
            if key in reserves:
                placed["class_year"] = reserves[key]["class_year"] or placed["class_year"]
            for f in OVERRIDE_FIELDS:
                if o.get(f) is not None:
                    placed[f] = o[f]
            slot.append(placed)
        else:
            report.append(f"override for {name} at {pos} matches nothing on Ourlads — "
                          "ignored (stale? remove it, or add \"pin\": true to keep the row)")
            continue
        overridden.add(key)
        # An injury is the player's, not the slot's: the punt returner who's out at
        # receiver is out on punt returns too. Only the status spreads -- the note and
        # Pulse hit stay on the one row, or compute_pulse would count him once per spot.
        if status != "active":
            for e in (x for rows in by_pos.values() for x in rows):
                if norm_name(e["player_name"]) == key and e["status"] == "active":
                    e["status"] = status

    unlisted = [r["player_name"] for k, r in reserves.items() if k not in overridden]
    if unlisted:
        report.append(f"on Ourlads' reserve list, not shown: {', '.join(unlisted)} "
                      "(add an override with a position and status to show him)")

    entries = []
    for slot in by_pos.values():
        slot.sort(key=lambda e: e["rank"])
        for i, e in enumerate(slot, start=1):
            e["rank"] = i
            entries.append(e)
    entries.sort(key=lambda e: (e["pos_order"], e["rank"]))
    return entries, report


def die(msg: str) -> None:
    print(f"\n[X] {msg}")
    sys.exit(1)


def main() -> None:
    if not SB_URL or not SB_KEY:
        die("Missing SUPABASE_URL or SUPABASE_SECRET_KEY in .env")
    with open(DATA_FILE, encoding="utf-8") as f:
        curated = json.load(f)

    overrides = [e for e in curated if e.get("sport_id") == "football"]
    entries = [e for e in curated if e.get("sport_id") != "football"]
    football_ok = False
    try:
        chart = ourlads.parse(ourlads.fetch())
        problem = ourlads.looks_complete(chart)
        if problem:
            print(f"  [!] Ourlads page read, but it doesn't look like a full chart: {problem}")
        else:
            fb, report = football_entries(chart, overrides)
            entries += fb
            football_ok = True
            print(f"Ourlads two-deep, updated {chart['updated'] or '(no date on page)'}: "
                  f"{len(fb)} football rows")
            for line in report:
                print(f"   - {line}")
    except Exception as e:  # noqa: BLE001 -- any failure here means "keep yesterday's"
        print(f"  [!] Couldn't read Ourlads ({type(e).__name__}: {e})")
    if not football_ok:
        print("  [!] Football depth chart left as it was; basketball and baseball still sync.")

    sb = create_client(SB_URL, SB_KEY)
    # Rebuilt each run so reorders/removals take effect. Football only when Ourlads gave
    # us a whole chart to replace it with.
    q = sb.table("depth_chart").delete().neq("id", "___none___")
    if not football_ok:
        q = q.neq("sport_id", "football")
    q.execute()

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
        # Exception: `keep_despite_out` pins an undecided player (e.g. an eligibility case that
        # could still return) on the chart on purpose — show them, flagged, rather than drop them.
        if (e.get("sport_id"), norm_name(name)) in gone and not e.get("keep_despite_out"):
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
            # What this injury costs the Pulse, and from when. Both optional and both
            # curated -- an entry with no pulse_delta shows on the depth card and moves
            # the score not at all. See the note in schema.sql.
            "pulse_delta": int(e.get("pulse_delta") or 0),
            "out_since": e.get("out_since") or None,
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
    if not football_ok:
        # Non-zero so the step goes yellow in Actions; the workflow carries on regardless.
        die("Depth chart synced, except football (Ourlads unreadable — see above).")
    print("\n[OK] Depth chart synced to Supabase.")


if __name__ == "__main__":
    main()
