"""
Mountaineer Pulse - M1 Pipeline: CFBD -> Supabase (Football)
============================================================
Pulls WVU football schedule/scores, roster, and season record from CFBD and
writes them into the Supabase database (games, players, team_records tables).

Prereqs:
  1. schema.sql has been run once in the Supabase SQL Editor.
  2. .env has CFBD_API_KEY, SUPABASE_URL, SUPABASE_SECRET_KEY.

Run:  python sync_football.py
"""

import os
import sys
import requests
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

CFBD_KEY = os.getenv("CFBD_API_KEY")
SB_URL = os.getenv("SUPABASE_URL")
SB_KEY = os.getenv("SUPABASE_SECRET_KEY")

BASE = "https://api.collegefootballdata.com"
TEAM = "West Virginia"
SEASONS = [2025, 2026]      # completed + upcoming
ROSTER_SEASON = 2025        # most recent full roster
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
    print(f"Connected to Supabase: {SB_URL}\n")

    # --- GAMES (schedule + scores) ------------------------------------------
    game_rows = []
    for season in SEASONS:
        games = cfbd("/games", {"year": season, "team": TEAM, "seasonType": "regular"})
        for g in games:
            hp, ap = g.get("homePoints"), g.get("awayPoints")
            played = hp is not None and ap is not None
            game_rows.append({
                "id": g["id"],
                "sport_id": SPORT,
                "season": season,
                "week": g.get("week"),
                "season_type": g.get("seasonType"),
                "start_date": g.get("startDate"),
                "home_team": g.get("homeTeam"),
                "away_team": g.get("awayTeam"),
                "home_points": hp,
                "away_points": ap,
                "venue": g.get("venue"),
                "status": "final" if played else "scheduled",
                "is_wvu_home": g.get("homeTeam") == TEAM,
            })
    sb.table("games").upsert(game_rows).execute()
    print(f"  games        -> upserted {len(game_rows)} rows ({SEASONS[0]}-{SEASONS[-1]})")

    # --- PLAYERS (roster) ----------------------------------------------------
    roster = cfbd("/roster", {"team": TEAM, "year": ROSTER_SEASON})
    player_rows = []
    for p in roster:
        pid = p.get("id")
        if pid is None:
            continue
        player_rows.append({
            "id": str(pid),
            "sport_id": SPORT,
            "season": ROSTER_SEASON,
            "first_name": p.get("firstName"),
            "last_name": p.get("lastName"),
            "jersey": p.get("jersey"),
            "position": p.get("position"),
            "height": p.get("height"),
            "weight": p.get("weight"),
            "class_year": p.get("year"),
            "home_city": p.get("homeCity"),
            "home_state": p.get("homeState"),
        })
    sb.table("players").upsert(player_rows).execute()
    print(f"  players      -> upserted {len(player_rows)} rows ({ROSTER_SEASON} roster)")

    # --- TEAM RECORDS --------------------------------------------------------
    record_rows = []
    for season in SEASONS:
        recs = cfbd("/records", {"year": season, "team": TEAM})
        for r in recs:
            total = r.get("total", {})
            conf = r.get("conferenceGames", {})
            record_rows.append({
                "sport_id": SPORT,
                "season": season,
                "team": r.get("team", TEAM),
                "total_wins": total.get("wins"),
                "total_losses": total.get("losses"),
                "conference": r.get("conference"),
                "conf_wins": conf.get("wins"),
                "conf_losses": conf.get("losses"),
            })
    if record_rows:
        sb.table("team_records").upsert(record_rows, on_conflict="sport_id,season,team").execute()
    print(f"  team_records -> upserted {len(record_rows)} rows")

    print("\n" + "=" * 60)
    print("  [OK] SYNC COMPLETE - WVU football data is now in Supabase.")
    print("=" * 60)


if __name__ == "__main__":
    main()
