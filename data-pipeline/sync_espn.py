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
# ESPN 403s browser-impersonating user agents. "Mozilla/5.0" on its own is a known bot
# signature and is now refused outright; an honest, identifiable agent is let through. Do
# not "fix" a future block by pasting a real Chrome string here — that is the thing being
# blocked. Verified 2026-09-01: bare Mozilla/5.0 -> 403, this -> 200.
UA = {"User-Agent": "MountaineerPulse/1.0 (+https://github.com/tysongraham/mountaineer-pulse)"}
SEASON = 2026
# Men's basketball spans two calendar years and ESPN labels a season by the year it ends,
# so 2026-27 is season 2027. Both are pulled every run:
#
#   2026 - the season just completed. It has to be asked for by NUMBER, because once a
#          season ends ESPN's default team-schedule response flips to the next one. In the
#          offseason that response is empty, and an empty response used to be written
#          straight through as a 0-0 record: WVU's 21-win, Crown-winning 2025-26 sat in the
#          app as 0-0 from June 30 until this was found.
#   2027 - the season being announced. A future season answers only with an explicit
#          seasontype=2, and fills in a few games at a time as they're released, so the
#          schedule builds itself on the Scores tab without anyone typing it in.
MBB_SEASONS = [2026, 2027]
CONF = {"mbb": "Big 12", "baseball": "Big 12"}


def die(msg: str) -> None:
    print(f"\n[X] {msg}")
    sys.exit(1)


def is_wvu(competitor: dict) -> bool:
    t = competitor.get("team", {}) or {}
    return str(t.get("id")) == TEAM_ID or "West Virginia" in (t.get("displayName", "") or "")


def parse_event(ev: dict, sport_id: str, season: int) -> dict | None:
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
        "season": season,
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


def basketball_events(season: int) -> list[dict]:
    """Regular season (type 2) and postseason (type 3), merged.

    Asking for the type explicitly is what makes a not-yet-started season answer at all.
    Type 3 matters for more than completeness: the bare URL and type 2 both return 32 games
    for 2025-26 and none of the three College Basketball Crown wins, so a record computed
    from either reads 18-14 for a team that finished 21-14 and won the thing."""
    found: dict[str, dict] = {}
    for stype in (2, 3):
        url = (f"{SITE}/basketball/mens-college-basketball/teams/{TEAM_ID}/schedule"
               f"?season={season}&seasontype={stype}")
        try:
            data = requests.get(url, headers=UA, timeout=30).json()
        except (requests.RequestException, ValueError):
            continue  # one missing half shouldn't lose the other
        for ev in data.get("events", []):
            found[str(ev.get("id"))] = ev
    return list(found.values())


def baseball_events(season: int) -> list[dict]:
    """Scan the college-baseball scoreboard day by day and keep WVU games.

    `season` is taken for signature parity with basketball; the window below is what
    actually bounds the scan, and it needs widening by hand for a new baseball year."""
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

    jobs = [("mbb", f"Men's Basketball {yr - 1}-{str(yr)[2:]}", yr, basketball_events)
            for yr in MBB_SEASONS]
    jobs.append(("baseball", "Baseball", SEASON, baseball_events))

    for sport_id, label, season, fetch in jobs:
        print(f"\n{label}: fetching from ESPN...")
        events = fetch(season)
        rows = [r for r in (parse_event(e, sport_id, season) for e in events) if r]
        if not rows:
            # An empty answer is almost always ESPN, not reality — a 403, a schedule not
            # published yet, an endpoint that moved. Writing it through anyway is how the
            # basketball record became 0-0. Leave whatever is on file alone and say so.
            print(f"  no games returned for {season} — leaving existing rows and record alone")
            continue

        sb.table("games").upsert(rows).execute()

        wins, losses = compute_record(rows)
        sb.table("team_records").upsert(
            {
                "sport_id": sport_id,
                "season": season,
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
