"""
Mountaineer Pulse - ESPN Pipeline: Basketball + Baseball -> Supabase
====================================================================
Men's Basketball: ESPN team-schedule endpoint (clean, one request).
Baseball: ESPN per-team schedule is broken (500s), so we scan the
college-baseball scoreboard across the season and keep WVU's games.

Writes into the same `games` and `team_records` tables as football, keyed by
ESPN event id (globally unique across sports, so no PK collisions).

Run:  python sync_espn.py
"""

import os
import sys
from datetime import date, timedelta

import requests
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

SB_URL = os.getenv("SUPABASE_URL")
SB_KEY = os.getenv("SUPABASE_SECRET_KEY")

TEAM_ID = "277"  # West Virginia
SITE = "https://site.api.espn.com/apis/site/v2/sports"
UA = {"User-Agent": "Mozilla/5.0"}
SEASON = 2026
CONF = {"mbb": "Big 12", "baseball": "Big 12"}


def die(msg: str) -> None:
    print(f"\n[X] {msg}")
    sys.exit(1)


def is_wvu(competitor: dict) -> bool:
    t = competitor.get("team", {}) or {}
    return str(t.get("id")) == TEAM_ID or "West Virginia" in (t.get("displayName", "") or "")


def parse_event(ev: dict, sport_id: str) -> dict | None:
    comp = (ev.get("competitions") or [{}])[0]
    competitors = comp.get("competitors", [])
    if not any(is_wvu(c) for c in competitors):
        return None

    status = (comp.get("status") or {}).get("type", {})
    completed = bool(status.get("completed"))

    home = away = None
    for c in competitors:
        name = (c.get("team") or {}).get("displayName", "?")
        score = c.get("score")
        pts = score.get("value") if isinstance(score, dict) else score
        try:
            pts = int(float(pts)) if pts is not None and pts != "" else None
        except (TypeError, ValueError):
            pts = None
        rec = {"name": name, "pts": pts, "wvu": is_wvu(c)}
        if c.get("homeAway") == "home":
            home = rec
        else:
            away = rec

    if not home or not away:
        return None

    return {
        "id": int(ev["id"]),
        "sport_id": sport_id,
        "season": SEASON,
        "week": None,
        "season_type": None,
        "start_date": ev.get("date"),
        "home_team": home["name"],
        "away_team": away["name"],
        "home_points": home["pts"] if completed else None,
        "away_points": away["pts"] if completed else None,
        "venue": (comp.get("venue") or {}).get("fullName"),
        "status": "final" if completed else "scheduled",
        "is_wvu_home": home["wvu"],
    }


def basketball_events() -> list[dict]:
    url = f"{SITE}/basketball/mens-college-basketball/teams/{TEAM_ID}/schedule"
    data = requests.get(url, headers=UA, timeout=30).json()
    return data.get("events", [])


def baseball_events() -> list[dict]:
    """Scan the college-baseball scoreboard day by day and keep WVU games."""
    found: dict[str, dict] = {}
    d, end = date(2026, 2, 10), date(2026, 6, 30)
    days = (end - d).days + 1
    scanned = 0
    while d <= end:
        ds = d.strftime("%Y%m%d")
        try:
            j = requests.get(
                f"{SITE}/baseball/college-baseball/scoreboard?dates={ds}&limit=300",
                headers=UA,
                timeout=20,
            ).json()
            for ev in j.get("events", []):
                comp = (ev.get("competitions") or [{}])[0]
                if any(is_wvu(c) for c in comp.get("competitors", [])):
                    found[ev["id"]] = ev
        except requests.RequestException:
            pass  # one bad day shouldn't kill the scan
        scanned += 1
        if scanned % 30 == 0:
            print(f"    ...scanned {scanned}/{days} days, {len(found)} WVU games so far")
        d += timedelta(days=1)
    return list(found.values())


def compute_record(rows: list[dict]) -> tuple[int, int]:
    wins = losses = 0
    for g in rows:
        if g["status"] != "final" or g["home_points"] is None:
            continue
        wvu_pts = g["home_points"] if g["is_wvu_home"] else g["away_points"]
        opp_pts = g["away_points"] if g["is_wvu_home"] else g["home_points"]
        if wvu_pts > opp_pts:
            wins += 1
        else:
            losses += 1
    return wins, losses


def main() -> None:
    if not SB_URL or not SB_KEY:
        die("Missing SUPABASE_URL or SUPABASE_SECRET_KEY in .env")
    sb = create_client(SB_URL, SB_KEY)

    for sport_id, label, fetch in [
        ("mbb", "Men's Basketball", basketball_events),
        ("baseball", "Baseball", baseball_events),
    ]:
        print(f"\n{label}: fetching from ESPN...")
        events = fetch()
        rows = [r for r in (parse_event(e, sport_id) for e in events) if r]
        if rows:
            sb.table("games").upsert(rows).execute()

        wins, losses = compute_record(rows)
        sb.table("team_records").upsert(
            {
                "sport_id": sport_id,
                "season": SEASON,
                "team": "West Virginia",
                "total_wins": wins,
                "total_losses": losses,
                "conference": CONF[sport_id],
                "conf_wins": None,
                "conf_losses": None,
            },
            on_conflict="sport_id,season,team",
        ).execute()
        print(f"  games -> {len(rows)} upserted | record {wins}-{losses}")

    print("\n[OK] Basketball + Baseball synced to Supabase.")


if __name__ == "__main__":
    main()
