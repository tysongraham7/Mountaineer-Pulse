"""
Mountaineer Pulse - Data Spike #1
=================================
Goal: prove we can pull real WVU football data from the CollegeFootballData API.
This is the single most important de-risking step of the whole project. If this
prints real schedules, scores, rosters, and records, the data backbone is real.

Run:  python cfbd_spike.py
"""

import os
import sys
import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("CFBD_API_KEY")
BASE = "https://api.collegefootballdata.com"
TEAM = "West Virginia"

COMPLETED_SEASON = 2025   # finished season -> guaranteed populated data
UPCOMING_SEASON = 2026    # current/upcoming season -> schedule may be partial


def die(msg: str) -> None:
    print(f"\n[X] {msg}")
    sys.exit(1)


def get(path: str, params: dict) -> list:
    """Call a CFBD endpoint and return parsed JSON, with friendly errors."""
    headers = {"Authorization": f"Bearer {API_KEY}"}
    resp = requests.get(f"{BASE}{path}", headers=headers, params=params, timeout=30)
    if resp.status_code == 401:
        die("API key rejected (401). Check CFBD_API_KEY in your .env file.")
    if resp.status_code != 200:
        die(f"Request to {path} failed: HTTP {resp.status_code} - {resp.text[:200]}")
    return resp.json()


def section(title: str) -> None:
    print("\n" + "=" * 60)
    print(f"  {title}")
    print("=" * 60)


def main() -> None:
    if not API_KEY or API_KEY == "your_key_here":
        die("No API key found. Copy .env.example to .env and paste your key.")

    print(f"Pulling West Virginia football data from CFBD...\n(key ...{API_KEY[-4:]})")

    # 1) Completed 2025 schedule + scores -------------------------------------
    section(f"{COMPLETED_SEASON} SCHEDULE & SCORES")
    games = get("/games", {"year": COMPLETED_SEASON, "team": TEAM, "seasonType": "regular"})
    wins = losses = 0
    for g in games:
        home, away = g.get("homeTeam"), g.get("awayTeam")
        hp, ap = g.get("homePoints"), g.get("awayPoints")
        if hp is None or ap is None:
            print(f"  {away} @ {home}  -  (not played)")
            continue
        wvu_home = home == TEAM
        wvu_pts = hp if wvu_home else ap
        opp_pts = ap if wvu_home else hp
        result = "W" if wvu_pts > opp_pts else "L"
        wins += result == "W"
        losses += result == "L"
        print(f"  [{result}]  {away} {ap} @ {home} {hp}")
    print(f"\n  >> {COMPLETED_SEASON} record from scores: {wins}-{losses}")

    # 2) Official records ------------------------------------------------------
    section(f"{COMPLETED_SEASON} OFFICIAL RECORD")
    records = get("/records", {"year": COMPLETED_SEASON, "team": TEAM})
    if records:
        r = records[0]
        total = r.get("total", {})
        print(f"  Overall: {total.get('wins')}-{total.get('losses')}")
        conf = r.get("conferenceGames", {})
        print(f"  Conference ({r.get('conference')}): {conf.get('wins')}-{conf.get('losses')}")

    # 3) Roster ----------------------------------------------------------------
    section(f"{COMPLETED_SEASON} ROSTER (first 15 of full list)")
    roster = get("/roster", {"team": TEAM, "year": COMPLETED_SEASON})
    print(f"  Total players on roster: {len(roster)}")
    for p in roster[:15]:
        name = f"{p.get('firstName','')} {p.get('lastName','')}".strip()
        print(f"   #{str(p.get('jersey','')).rjust(2)}  {name:<24} {p.get('position','') or '':<4} {p.get('homeCity','') or ''}, {p.get('homeState','') or ''}")

    # 4) Rankings (did WVU appear in any poll?) --------------------------------
    section(f"{COMPLETED_SEASON} AP POLL APPEARANCES")
    rankings = get("/rankings", {"year": COMPLETED_SEASON, "seasonType": "regular"})
    appeared = False
    for week in rankings:
        for poll in week.get("polls", []):
            if poll.get("poll") != "AP Top 25":
                continue
            for rank in poll.get("ranks", []):
                if rank.get("school") == TEAM:
                    appeared = True
                    print(f"  Week {week.get('week')}: #{rank.get('rank')} (AP)")
    if not appeared:
        print("  WVU did not appear in the AP Top 25 this season.")

    # 5) Upcoming 2026 schedule ------------------------------------------------
    section(f"{UPCOMING_SEASON} UPCOMING SCHEDULE")
    upcoming = get("/games", {"year": UPCOMING_SEASON, "team": TEAM, "seasonType": "regular"})
    if not upcoming:
        print(f"  No {UPCOMING_SEASON} schedule published yet.")
    for g in upcoming:
        date = (g.get("startDate") or "")[:10]
        print(f"  {date}  {g.get('awayTeam')} @ {g.get('homeTeam')}")

    print("\n" + "=" * 60)
    print("  [OK] SPIKE SUCCESSFUL - the data backbone works.")
    print("=" * 60)


if __name__ == "__main__":
    main()
