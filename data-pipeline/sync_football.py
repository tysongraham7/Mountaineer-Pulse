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

# ESPN, for the event ids and broadcasts, for finals CFBD hasn't posted yet, and for
# scores, kickoffs and the record when CFBD is down (see main()). CFBD owns the schedule.
ESPN_SCHEDULE = "https://site.api.espn.com/apis/site/v2/sports/football/college-football/teams/277/schedule"
# ESPN refuses browser-impersonating user agents — see the note in sync_espn.py before
# changing this.
ESPN_UA = {"User-Agent": "MountaineerPulse/1.0 (+https://github.com/tysongraham/mountaineer-pulse)"}
EASTERN = ZoneInfo("America/New_York")


def die(msg: str) -> None:
    print(f"\n[X] {msg}")
    sys.exit(1)


class CfbdDown(RuntimeError):
    """CFBD refused a request. Caught in main(), which falls back to ESPN."""


def cfbd(path: str, params: dict) -> list:
    headers = {"Authorization": f"Bearer {CFBD_KEY}"}
    try:
        r = requests.get(f"{BASE}{path}", headers=headers, params=params, timeout=30)
    except requests.RequestException as e:
        raise CfbdDown(f"CFBD {path} unreachable ({type(e).__name__})") from e
    if r.status_code != 200:
        raise CfbdDown(f"CFBD {path} failed: HTTP {r.status_code} - {r.text[:200]}")
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


def espn_schedule() -> dict[int, list[dict]]:
    """ESPN's WVU football schedule, season -> events, for every season it answered.

    Best-effort by design: an unreachable season is simply absent, and every caller treats
    a missing season as "leave what we have alone".
    """
    out: dict[int, list[dict]] = {}
    for season in SEASONS:
        try:
            r = requests.get(ESPN_SCHEDULE, params={"season": season}, headers=ESPN_UA, timeout=30)
            r.raise_for_status()
            out[season] = [ev for ev in r.json().get("events", []) if str(ev.get("id", "")).isdigit()]
        except (requests.RequestException, ValueError) as e:
            print(f"  [!] ESPN schedule {season} unavailable ({type(e).__name__}) - "
                  f"live scores will be off for that season until the next run")
    return out


def espn_events(schedule: dict[int, list[dict]]) -> dict[str, tuple[int, str | None]]:
    """Map Eastern game date -> (ESPN event id, broadcast) for every WVU football game
    ESPN lists.

    These are niceties — the id powers the live-score card, the broadcast is the "where to
    watch" line. If ESPN is unreachable the map is empty, and the caller then leaves both
    columns untouched instead of blanking values it wrote earlier.

    WVU plays at most one football game a day, so the date is a unique key.
    """
    out: dict[str, tuple[int, str | None]] = {}
    for events in schedule.values():
        for ev in events:
            day = eastern_day(ev.get("date"))
            if day:
                comp = (ev.get("competitions") or [{}])[0]
                out[day] = (int(ev["id"]), broadcast_of(comp))
    return out


def points(side: dict) -> int | None:
    """A competitor's score. The schedule endpoint nests it ({"value": 24.0}), the
    scoreboard gives a bare string; either way a missing score is None, never 0."""
    s = side.get("score")
    if isinstance(s, dict):
        s = s.get("value")
    try:
        return int(float(s))
    except (TypeError, ValueError):
        return None


def espn_final(ev: dict) -> dict | None:
    """The finished game as games-table columns, or None until ESPN calls it final.

    Only completed games: a live score belongs to the live card, and writing one here
    would put a half-played game under Results.
    """
    comp = (ev.get("competitions") or [{}])[0]
    if not ((comp.get("status") or {}).get("type") or {}).get("completed"):
        return None
    sides = {c.get("homeAway"): c for c in comp.get("competitors", [])}
    hp, ap = points(sides.get("home", {})), points(sides.get("away", {}))
    if hp is None or ap is None:
        return None
    return {"home_points": hp, "away_points": ap, "status": "final"}


def espn_kickoff(ev: dict) -> str | None:
    """The kickoff as ISO UTC, once ESPN has a real time. Before the network sets it ESPN
    reports a placeholder (timeValid false), which must not replace one we already have."""
    comp = (ev.get("competitions") or [{}])[0]
    if not comp.get("timeValid") or not ev.get("date"):
        return None
    return datetime.fromisoformat(ev["date"].replace("Z", "+00:00")).isoformat()


def espn_record(events: list[dict]) -> dict | None:
    """WVU's overall and conference record after its latest completed game, as
    team_records columns. ESPN stamps each competitor with its record to date."""
    for ev in reversed(events):
        if not espn_final(ev):
            continue
        comp = ev["competitions"][0]
        wvu = next((c for c in comp.get("competitors", []) if c.get("team", {}).get("location") == TEAM), None)
        recs = {r.get("type"): r.get("displayValue", "") for r in (wvu or {}).get("record", [])}
        try:
            tw, tl = (int(x) for x in recs["total"].split("-")[:2])
            cw, cl = (int(x) for x in recs["vsconf"].split("-")[:2])
        except (KeyError, ValueError):
            return None
        return {"total_wins": tw, "total_losses": tl, "conf_wins": cw, "conf_losses": cl}
    return None


def patch_from_espn(sb, schedule: dict[int, list[dict]]) -> int:
    """With CFBD down, bring the rows we already have up to date from ESPN: final scores
    and announced kickoff times. Returns how many rows changed.

    Updates only, never inserts: every game is already in the table from a day CFBD
    answered (ids, team names and venues are CFBD's), and ESPN spells teams its own way.
    Matched on espn_event_id, which the good days wrote.
    """
    ids = [int(ev["id"]) for events in schedule.values() for ev in events]
    if not ids:
        return 0
    have = {r["espn_event_id"]: r for r in (sb.table("games")
            .select("id,espn_event_id,start_date,status,home_points,away_points")
            .eq("sport_id", SPORT).in_("espn_event_id", ids).execute().data or [])}
    changed = 0
    for events in schedule.values():
        for ev in events:
            row = have.get(int(ev["id"]))
            if not row:
                continue
            patch = {}
            if row["status"] != "final" and (final := espn_final(ev)):
                patch.update(final)
            kickoff = espn_kickoff(ev)
            if kickoff and (not row["start_date"] or
                            datetime.fromisoformat(row["start_date"]) != datetime.fromisoformat(kickoff)):
                patch["start_date"] = kickoff
            if patch:
                sb.table("games").update(patch).eq("id", row["id"]).execute()
                changed += 1
    return changed


def warn_cfbd_down(reason: str) -> None:
    """Make an outage visible. The step is continue-on-error, so a failure alone is a
    yellow icon in the Actions tab, and one went unnoticed for two game weeks in
    September 2026 while the Scores tab silently lost both results."""
    print(f"::warning title=CFBD down - football from ESPN::{reason}")
    from emailer import email_configured, send_email
    if not email_configured():
        return
    try:
        send_email(
            "CFBD is down - football scores are coming from ESPN",
            f"sync_football.py couldn't reach CFBD this morning:\n\n  {reason}\n\n"
            "Scores, kickoff times and the season record were filled in from ESPN instead, "
            "so the app is current. What ESPN can't supply stays stale until CFBD is back: "
            "new games on the schedule, and player stats (sync_player_stats.py).\n\n"
            "If this says 'Monthly call quota exceeded', it resets with the month.",
        )
    except Exception as e:
        print(f"  [!] couldn't email the CFBD warning: {str(e)[:120]}")


def main() -> str | None:
    """Returns why CFBD was skipped if it was (the ESPN fallback ran instead), else None.
    notify_games.py calls this mid-game and ignores the result; only a direct run warns."""
    for name, val in [("CFBD_API_KEY", CFBD_KEY), ("SUPABASE_URL", SB_URL),
                      ("SUPABASE_SECRET_KEY", SB_KEY)]:
        if not val:
            die(f"Missing {name} in .env")

    sb = create_client(SB_URL, SB_KEY)
    print(f"Connected to Supabase: {SB_URL}\n")

    schedule = espn_schedule()
    try:
        sync_from_cfbd(sb, schedule)
        return None
    except CfbdDown as e:
        # A monthly quota running out is the usual cause, and it lasts until the 1st. The
        # Scores tab, the record and the final-score alert all read the games table, so
        # keep it current from ESPN rather than leaving every result since then missing.
        print(f"  [!] {e}\n  [!] falling back to ESPN for scores, kickoff times and the record")
        if not schedule:
            die("ESPN is unreachable too - nothing to fall back on")
        print(f"  games        -> updated {patch_from_espn(sb, schedule)} rows from ESPN")
        record_rows = [{"sport_id": SPORT, "season": season, "team": TEAM, **rec}
                       for season, events in schedule.items() if (rec := espn_record(events))]
        if record_rows:
            sb.table("team_records").upsert(record_rows, on_conflict="sport_id,season,team").execute()
        print(f"  team_records -> upserted {len(record_rows)} rows from ESPN")
        return str(e)


def sync_from_cfbd(sb, schedule: dict[int, list[dict]]) -> None:
    # --- GAMES (schedule + scores) ------------------------------------------
    espn = espn_events(schedule)
    finals = {int(ev["id"]): f for events in schedule.values() for ev in events if (f := espn_final(ev))}
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
                # CFBD posts a final hours after ESPN does. Mid-game, notify_games.py runs
                # this sync to catch the final while it's still news, so take ESPN's.
                if not played and event_id in finals:
                    game_rows[-1].update(finals[event_id])
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
    if reason := main():
        warn_cfbd_down(reason)
