"""
Mountaineer Pulse - Football Player Season Stats (CFBD)
=======================================================
Pulls WVU per-player season stats from the College Football Data API and writes
them (long format) into the player_stats table. Two phases:

  1. WVU stats (2024-2026). Prior seasons populate now; the current season is
     empty until games are played. Returners are remapped onto the roster id so
     their profile joins straight to them.

  2. Incoming transfers' PREVIOUS-school stats. The portal feed gives each new
     arrival's origin school, so we pull their last seasons there and attach
     them to the player's WVU roster id, tagged with team = the old school.
     A fan opening a new transfer sees what they did before Morgantown.

The `team` column records where each stat line was earned, so the app can label
previous-school stats and -- importantly -- keep them OUT of WVU leaderboards.

Prereqs: schema.sql (player_stats table) has been run once; .env has
CFBD_API_KEY, SUPABASE_URL, SUPABASE_SECRET_KEY.
Run:  python sync_player_stats.py
"""

import os
import sys
import unicodedata

import requests
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

CFBD_KEY = os.getenv("CFBD_API_KEY")
SB_URL = os.getenv("SUPABASE_URL")
SB_KEY = os.getenv("SUPABASE_SECRET_KEY")

BASE = "https://api.collegefootballdata.com"
TEAM = "West Virginia"
SEASONS = [2024, 2025, 2026]     # WVU: prior seasons + current (empty until kickoff)
PREV_SEASONS = [2024, 2025]      # incoming transfers: seasons to pull at old school
PORTAL_YEAR = 2026               # portal cycle whose arrivals we enrich
SPORT = "football"
SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}


def die(msg: str) -> None:
    print(f"\n[X] {msg}")
    sys.exit(1)


def norm_name(name: str) -> str:
    """Normalize a name for matching: strip accents, punctuation, suffixes, case."""
    if not name:
        return ""
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    s = s.lower().replace(".", " ").replace("'", "").replace("-", " ")
    tokens = [t for t in s.split() if t and t not in SUFFIXES]
    return " ".join(tokens)


def cfbd(path: str, params: dict) -> list:
    headers = {"Authorization": f"Bearer {CFBD_KEY}"}
    r = requests.get(f"{BASE}{path}", headers=headers, params=params, timeout=30)
    if r.status_code != 200:
        die(f"CFBD {path} failed: HTTP {r.status_code} - {r.text[:200]}")
    return r.json()


def stat_row(pid, season, team, d) -> dict:
    return {
        "id": f"{pid}|{season}|{team}|{d['category']}|{d['statType']}",
        "player_id": pid,
        "season": season,
        "sport_id": SPORT,
        "player_name": d.get("player"),
        "position": d.get("position"),
        "category": d["category"],
        "stat_type": d["statType"],
        "stat": str(d.get("stat")),
        "team": team,
    }


def main() -> None:
    for name, val in [("CFBD_API_KEY", CFBD_KEY), ("SUPABASE_URL", SB_URL),
                      ("SUPABASE_SECRET_KEY", SB_KEY)]:
        if not val:
            die(f"Missing {name} in .env")

    sb = create_client(SB_URL, SB_KEY)

    # Build name -> roster id map from the current app roster.
    roster = sb.table("players").select("id,first_name,last_name").eq(
        "sport_id", SPORT).execute().data or []
    name_to_id = {}
    for p in roster:
        key = norm_name(f"{p.get('first_name') or ''} {p.get('last_name') or ''}")
        if key:
            name_to_id[key] = p["id"]
    print(f"roster players to match against: {len(name_to_id)}")

    rows = []

    # --- Phase 1: WVU stats -------------------------------------------------
    wvu_seasons = {}
    for season in SEASONS:
        data = cfbd("/stats/player/season", {"year": season, "team": TEAM})
        wvu_seasons[season] = len(data)
        for d in data:
            if not d.get("category") or not d.get("statType") or not d.get("player"):
                continue
            roster_id = name_to_id.get(norm_name(d["player"]))
            pid_final = roster_id or f"cfbd_{d.get('playerId')}"
            rows.append(stat_row(pid_final, season, TEAM, d))

    # --- Phase 2: incoming transfers' previous-school stats -----------------
    incoming = []  # (roster_id, norm_name, origin)
    for d in cfbd("/player/portal", {"year": PORTAL_YEAR}):
        if d.get("destination") != TEAM or not d.get("origin"):
            continue
        nm = norm_name(f"{d.get('firstName', '')} {d.get('lastName', '')}")
        rid = name_to_id.get(nm)
        if rid:  # only if they're on our roster (so a profile exists to attach to)
            incoming.append((rid, nm, d["origin"]))

    by_origin = {}
    for rid, nm, origin in incoming:
        by_origin.setdefault(origin, []).append((rid, nm))

    prev_linked = set()
    for origin, players in by_origin.items():
        wanted = {nm for _, nm in players}
        id_of = {nm: rid for rid, nm in players}
        for season in PREV_SEASONS:
            for d in cfbd("/stats/player/season", {"year": season, "team": origin}):
                nm = norm_name(d.get("player", ""))
                if nm in wanted and d.get("category") and d.get("statType"):
                    rid = id_of[nm]
                    rows.append(stat_row(rid, season, origin, d))
                    prev_linked.add(rid)

    # Clean slate for football, then insert fresh.
    sb.table("player_stats").delete().eq("sport_id", SPORT).execute()
    if rows:
        for i in range(0, len(rows), 500):
            sb.table("player_stats").upsert(rows[i:i + 500]).execute()

    wvu_linked = len({r["player_id"] for r in rows
                      if r["team"] == TEAM and not r["player_id"].startswith("cfbd_")})
    summary = "  ".join(f"{yr}:{n}" for yr, n in wvu_seasons.items())
    print(f"player_stats -> {len(rows)} stat lines")
    print(f"              WVU: {wvu_linked} returners linked   (CFBD rows/season  {summary})")
    print(f"              Transfers in: {len(incoming)} matched to roster, "
          f"{len(prev_linked)} had previous-school stats")
    print("\n[OK] Football player stats synced to Supabase.")


if __name__ == "__main__":
    main()
