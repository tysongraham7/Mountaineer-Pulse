"""
Mountaineer Pulse - Game-day push
=================================
The two notifications a sports app is actually for: your team is about to play, and your
team just finished. Until now the app pushed news and never scores, which for a sports app
is backwards.

Deliberately has NO model call. Everything here is a fact already in the games table, so a
game-day alert costs nothing and cannot hallucinate. That also means it can run every few
minutes without thinking about budget.

Two alerts per game, each fired at most once:

  KICKOFF  about KICKOFF_LEAD_MIN before the start, so there's time to find a TV. Only for
           the sports people plan their day around, and never for a game whose start time
           hasn't been announced (the feed stores those as midnight Eastern).
  FINAL    once the score lands. Every sport — a final is the single most wanted alert
           there is, and by definition it's news the moment it exists.

`notified_kickoff_at` / `notified_final_at` on the row are what make it once-only, so
running this every ten minutes is safe.

Run:  python notify_games.py [--dry-run] [--force]
        --dry-run  decide and print, send nothing, write nothing
        --force    ignore the daily cap
"""

import os
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from supabase import create_client

from send_push import send_push

load_dotenv()

SB_URL = os.getenv("SUPABASE_URL")
SB_KEY = os.getenv("SUPABASE_SECRET_KEY")

ET = ZoneInfo("America/New_York")

# Long enough to turn a TV on or leave for the stadium, short enough to still feel like
# "now". An alert three hours out is just a calendar entry.
KICKOFF_LEAD_MIN = 90
# Reminders only for the sports people plan a day around. Baseball plays midweek and in
# doubleheaders; a heads-up before each one would train people to turn alerts off. Baseball
# finals still go out — see below.
KICKOFF_SPORTS = {"football", "mbb"}
# A "final" older than this isn't news, it's a backfill. Without this, one re-sync of an old
# season would push every result WVU has ever had.
FINAL_MAX_AGE_H = 8
# A doubleheader plus a football game is a real day; twelve is not. Guards against a bad
# feed update marking many games final at once.
MAX_PER_DAY = 4

VERB = {"football": "Kickoff", "mbb": "Tip-off", "baseball": "First pitch"}
SPORT_LABEL = {"football": "Football", "mbb": "Men's Basketball", "baseball": "Baseball"}

WVU = "West Virginia"


def die(msg: str) -> None:
    print(f"\n[X] {msg}")
    sys.exit(1)


def short_team(name: str) -> str:
    """Trim the mascot so a 60-character notification title fits the matchup."""
    for suffix in (" Mountaineers", " Tar Heels", " Golden Bears", " Horned Frogs",
                   " Thundering Herd", " Nittany Lions", " Chanticleers", " Cyclones",
                   " Bearcats", " Wildcats", " Cowboys", " Trojans", " Bears", " Skyhawks"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def start_is_tba(iso: str | None) -> bool:
    """The feed stores an unannounced start as midnight Eastern. Treated as a real time it
    would fire a 10:30pm reminder for a game that has no time yet — so it isn't."""
    if not iso:
        return True
    et = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(ET)
    return et.hour == 0 and et.minute == 0


def opponent_of(g: dict) -> str:
    return short_team(g["away_team"] if g.get("is_wvu_home") else g["home_team"])


def pushed_today(sb, now_et: datetime) -> int:
    """Game alerts already sent today, counted in EASTERN days — a 10pm ET final is stored
    as tomorrow in UTC, and counting UTC days would reset the cap mid-evening."""
    start = (now_et.replace(hour=0, minute=0, second=0, microsecond=0)
             .astimezone(timezone.utc).isoformat())
    n = 0
    for col in ("notified_kickoff_at", "notified_final_at"):
        n += len(sb.table("games").select("id").gte(col, start).execute().data or [])
    return n


def due_kickoffs(sb, now: datetime) -> list[dict]:
    window = (now + timedelta(minutes=KICKOFF_LEAD_MIN)).isoformat()
    rows = (sb.table("games")
            .select("id,sport_id,start_date,home_team,away_team,venue,is_wvu_home,status")
            .neq("status", "final")
            .gte("start_date", now.isoformat()).lte("start_date", window)
            .is_("notified_kickoff_at", "null")
            .order("start_date").execute().data or [])
    return [g for g in rows
            if g.get("sport_id") in KICKOFF_SPORTS and not start_is_tba(g.get("start_date"))]


def refresh_scores(sb, now: datetime) -> None:
    """Pull fresh scores, but only while a game could actually be finishing.

    The schedule syncs run once a day at 11:00 UTC. Left alone, a Saturday final wouldn't
    reach the database until Sunday morning — by which point FINAL_MAX_AGE_H would correctly
    refuse to alert on it, and the single most wanted notification in the app would simply
    never fire.

    So the sync runs from here instead, gated on a game having started and not yet being
    final. In practice that's a handful of hours a week in season and never in the summer,
    which is what makes a ten-minute cron affordable.

    Never fatal: these scripts call sys.exit() on a bad response, and a flaky upstream must
    not take down the alert for a game whose score we already have.
    """
    started = (now - timedelta(hours=FINAL_MAX_AGE_H)).isoformat()
    live = (sb.table("games").select("sport_id")
            .neq("status", "final")
            .gte("start_date", started).lte("start_date", now.isoformat())
            .execute().data or [])
    if not live:
        return
    sports = {g["sport_id"] for g in live}
    print(f"  a game is under way ({', '.join(sorted(sports))}) — refreshing scores")
    for mod, owns in (("sync_football", {"football"}), ("sync_espn", {"mbb", "baseball"})):
        if not (sports & owns):
            continue
        try:
            __import__(mod).main()
        except SystemExit:
            print(f"    ({mod} bailed out — using the scores we already have)")
        except Exception as e:
            print(f"    ({mod} failed: {str(e)[:120]})")


def due_finals(sb, now: datetime) -> list[dict]:
    cutoff = (now - timedelta(hours=FINAL_MAX_AGE_H)).isoformat()
    rows = (sb.table("games")
            .select("id,sport_id,start_date,home_team,away_team,home_points,away_points,"
                    "is_wvu_home,status")
            .eq("status", "final").gte("start_date", cutoff)
            .is_("notified_final_at", "null")
            .order("start_date").execute().data or [])
    return [g for g in rows if g.get("home_points") is not None and g.get("away_points") is not None]


def kickoff_alert(g: dict) -> tuple[str, str]:
    opp = opponent_of(g)
    et = datetime.fromisoformat(g["start_date"].replace("Z", "+00:00")).astimezone(ET)
    when = et.strftime("%-I:%M %p") if os.name != "nt" else et.strftime("%#I:%M %p")
    verb = VERB.get(g["sport_id"], "First pitch")
    where = "vs" if g.get("is_wvu_home") else "at"
    return (
        f"WVU {where} {opp} today",
        f"{verb} at {when} ET. Tap for the matchup and what to watch for.",
    )


def final_alert(g: dict) -> tuple[str, str]:
    home = bool(g.get("is_wvu_home"))
    wvu, opp_pts = (g["home_points"], g["away_points"]) if home else (g["away_points"], g["home_points"])
    opp = opponent_of(g)
    sport = SPORT_LABEL.get(g["sport_id"], "")
    # The opponent belongs in the TITLE, not just the body — a lock screen often shows only
    # the first line, and "Mountaineers win, 12-0" against nobody is half a result.
    if wvu > opp_pts:
        title = f"WVU beats {opp}, {wvu}–{opp_pts}"
    elif wvu < opp_pts:
        title = f"WVU falls to {opp}, {opp_pts}–{wvu}"
    else:
        title = f"WVU ties {opp}, {wvu}–{opp_pts}"
    where = "in Morgantown" if home else f"at {opp}"
    return title, f"{sport} final {where}."


def main() -> None:
    dry = "--dry-run" in sys.argv
    force = "--force" in sys.argv
    if not SB_URL or not SB_KEY:
        die("Missing SUPABASE_URL or SUPABASE_SECRET_KEY")

    sb = create_client(SB_URL, SB_KEY)
    now = datetime.now(timezone.utc)
    now_et = now.astimezone(ET)

    refresh_scores(sb, now)

    # Finals first: a result is more wanted than a reminder, so if the cap only allows one
    # alert through, it should be the score.
    jobs: list[tuple[dict, str]] = [(g, "final") for g in due_finals(sb, now)]
    jobs += [(g, "kickoff") for g in due_kickoffs(sb, now)]
    if not jobs:
        print(f"Nothing to alert on ({now_et:%H:%M} ET): no game starting within "
              f"{KICKOFF_LEAD_MIN}m and no new final.")
        return

    already = pushed_today(sb, now_et)
    print(f"{len(jobs)} game alert(s) due; {already}/{MAX_PER_DAY} already sent today.")

    for g, kind in jobs:
        if not force and already >= MAX_PER_DAY:
            print(f"  cap reached — skipping the rest ({len(jobs)} were due)")
            break
        title, body = kickoff_alert(g) if kind == "kickoff" else final_alert(g)
        print(f"  {kind.upper():<8} {title}\n           {body}")
        if dry:
            continue
        # gameId opens this game's sheet directly, rather than dropping the reader on the
        # Scores tab to find the row themselves.
        send_push(title, body, data={"screen": "scores", "gameId": str(g["id"])})
        col = "notified_kickoff_at" if kind == "kickoff" else "notified_final_at"
        sb.table("games").update({col: now.isoformat()}).eq("id", g["id"]).execute()
        already += 1

    if dry:
        print("\n[dry run] Nothing sent, nothing marked.")
    else:
        print(f"\n[OK] {already} game alert(s) sent today.")


if __name__ == "__main__":
    main()
