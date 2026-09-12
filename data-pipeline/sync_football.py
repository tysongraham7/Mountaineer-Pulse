"""
Mountaineer Pulse - M1 Pipeline: CFBD -> Supabase (Football)
============================================================
Pulls WVU football schedule/scores and season record from CFBD and writes them
into the Supabase database (games, team_records).

NOT the roster: sync_rosters.py owns the players table (see the PLAYERS note in
main() for what went wrong when both wrote to it).

Prereqs:
  1. schema.sql has been run once in the Supabase SQL Editor.
  2. .env has CFBD_API_KEY, SUPABASE_URL, SUPABASE_SECRET_KEY.

Run:  python sync_football.py
"""

import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv
from supabase import create_client

from sync_espn import broadcast_of

load_dotenv()

CFBD_KEY = os.getenv("CFBD_API_KEY")
SB_URL = os.getenv("SUPABASE_URL")
SB_KEY = os.getenv("SUPABASE_SECRET_KEY")

BASE = "https://api.collegefootballdata.com"
TEAM = "West Virginia"
SEASONS = [2025, 2026]      # completed + upcoming
SPORT = "football"

# ESPN, for the event-id lookup only. Everything else on this page comes from CFBD.
ESPN_SCHEDULE = "https://site.api.espn.com/apis/site/v2/sports/football/college-football/teams/277/schedule"
# ESPN refuses browser-impersonating user agents — see the note in sync_espn.py before
# changing this.
ESPN_UA = {"User-Agent": "MountaineerPulse/1.0 (+https://github.com/tysongraham/mountaineer-pulse)"}
EASTERN = ZoneInfo("America/New_York")


def die(msg: str) -> None:
    print(f"\n[X] {msg}")
    sys.exit(1)


def cfbd(path: str, params: dict) -> list:
    headers = {"Authorization": f"Bearer {CFBD_KEY}"}
    r = requests.get(f"{BASE}{path}", headers=headers, params=params, timeout=30)
    if r.status_code != 200:
        die(f"CFBD {path} failed: HTTP {r.status_code} - {r.text[:200]}")
    return r.json()


def eastern_day(iso: str | None) -> str | None:
    """The Eastern calendar date of a kickoff, as YYYY-MM-DD.

    Used as the join key between CFBD's game list and ESPN's, because the two have no id
    in common. Eastern rather than UTC on purpose: an 8pm ET Saturday kickoff is Sunday in
    UTC, and a kickoff whose time hasn't been announced is stored as midnight Eastern by
    one feed and as the real time by the other once it lands. Both of those shift the UTC
    date while leaving the Eastern date alone, which is also the date a fan would name.
    """
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(EASTERN).date().isoformat()
    except ValueError:
        return None


def espn_events() -> dict[str, tuple[int, str | None]]:
    """Map Eastern game date -> (ESPN event id, broadcast) for every WVU football game
    ESPN lists.

    Best-effort by design. These are niceties — the id powers the live-score card, the
    broadcast is the "where to watch" line; CFBD remains the source of truth for the
    schedule itself. If ESPN is unreachable the sync must still write games, so every
    failure here returns an empty map rather than raising — the caller then leaves both
    columns untouched instead of blanking values it wrote earlier.

    WVU plays at most one football game a day, so the date is a unique key.
    """
    out: dict[str, tuple[int, str | None]] = {}
    for season in SEASONS:
        try:
            r = requests.get(ESPN_SCHEDULE, params={"season": season}, headers=ESPN_UA, timeout=30)
            r.raise_for_status()
            events = r.json().get("events", [])
        except (requests.RequestException, ValueError) as e:
            print(f"  [!] ESPN schedule {season} unavailable ({type(e).__name__}) - "
                  f"live scores will be off for that season until the next run")
            continue
        for ev in events:
            day = eastern_day(ev.get("date"))
            if day and str(ev.get("id", "")).isdigit():
                comp = (ev.get("competitions") or [{}])[0]
                out[day] = (int(ev["id"]), broadcast_of(comp))
    return out


def main() -> None:
    for name, val in [("CFBD_API_KEY", CFBD_KEY), ("SUPABASE_URL", SB_URL),
                      ("SUPABASE_SECRET_KEY", SB_KEY)]:
        if not val:
            die(f"Missing {name} in .env")

    sb = create_client(SB_URL, SB_KEY)
    print(f"Connected to Supabase: {SB_URL}\n")

    # --- GAMES (schedule + scores) ------------------------------------------
    espn = espn_events()
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
            # Only when ESPN answered. Writing the keys with a None for every row on a day
            # ESPN was down would upsert those nulls over ids we already had, taking the
            # live card offline until the next successful run. Absent key = column left as
            # it is. Present-but-None is still correct for a game ESPN genuinely has no
            # event for, which is why the check is on the map, not on the lookup.
            if espn:
                event_id, broadcast = espn.get(eastern_day(g.get("startDate"))) or (None, None)
                game_rows[-1]["espn_event_id"] = event_id
                game_rows[-1]["broadcast"] = broadcast
    sb.table("games").upsert(game_rows).execute()
    matched = sum(1 for r in game_rows if r.get("espn_event_id"))
    on_tv = sum(1 for r in game_rows if r.get("broadcast"))
    print(f"  games        -> upserted {len(game_rows)} rows ({SEASONS[0]}-{SEASONS[-1]}), "
          f"{matched} matched to an ESPN event, {on_tv} with a broadcast")

    # --- PLAYERS (roster) ----------------------------------------------------
    # Nothing here any more. sync_rosters.py owns the players table: it scrapes
    # wvusports.com, which has photos, heights, class years, hometowns and bios, and it
    # rebuilds the table wholesale every run.
    #
    # This step used to upsert CFBD's roster for LAST season under CFBD athlete ids, a few
    # steps before that rebuild wiped them again. Two things went wrong with that:
    #
    #   * Between this step and the rebuild, football's roster held 247 people instead of
    #     122 - every returner listed twice, once properly and once as a photo-less,
    #     class-less ghost. Anyone opening the app in that window saw the duplicates, and
    #     if the wvusports scrape failed (it times out often enough to have its own retry
    #     logic) they stayed up all day.
    #   * The ghosts were last season's roster, so for those minutes every name-matching
    #     step downstream - the news classifier, the Pulse notes, the move extractor -
    #     treated 125 departed players as current Mountaineers.
    #
    # Nothing consumed them: every football stat row keys to a wvusports id or an unlinked
    # cfbd_ id, and every other reader matches on name. CFBD's value here is games, records
    # and stats, which the rest of this file still pulls.

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
