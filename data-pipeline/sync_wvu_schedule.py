"""
Mountaineer Pulse - Official Schedule Fill-In: wvusports.com -> games
=====================================================================
ESPN is the source of record for basketball games — it is where scores come from — but it
publishes a new season a few games at a time, weeks after WVU announces the whole thing.
On 2026-09-12 WVU posted all 14 nonconference games plus three exhibitions; ESPN had four.
A Scores tab that shows four games under "2026-27 Season" the day the schedule drops looks
broken to the fan who came to see it.

So this reads the schedule WVU itself publishes and writes a placeholder row for every game
ESPN hasn't listed yet. The moment ESPN lists a game on the same day, the placeholder is
deleted and ESPN's row takes over — ids, scores, live status, all of it. Nothing here ever
touches a row ESPN wrote.

Placeholder ids are 9_000_000_000 + wvusports' own event id, which can't collide with
ESPN's 401xxxxxx ids and is still a safe JavaScript integer. Any row at or above that base
belongs to this script and may be deleted by it; nothing else writes up there.

Exhibitions are carried too, tagged season_type='exhibition', because a fan wants to know
about the trip to Maryland. They are dropped once played rather than given a score: four
places (the home-screen record, the Pulse, the Pulse detail, the final-score alert) count
every 'final' row, and an exhibition win is not a win.

Brittleness: the same Nuxt hydration payload sync_rosters.py, sync_coaches.py and
sync_game_themes.py read. If WVU redesigns, this writes nothing rather than nonsense, and
whatever ESPN has stays up.

Runs AFTER sync_espn.py in the daily pipeline, so "what ESPN has" is today's answer.

Run:  python sync_wvu_schedule.py [--dry-run]
"""

import os
import re
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from supabase import create_client

from sync_game_themes import eastern_day, payload
from sync_rosters import fetch

load_dotenv()

SB_URL = os.getenv("SUPABASE_URL")
SB_KEY = os.getenv("SUPABASE_SECRET_KEY")

SCHEDULES = [
    ("mbb", "https://wvusports.com/sports/mens-basketball/schedule"),
]
PLACEHOLDER_BASE = 9_000_000_000
WVU = "West Virginia Mountaineers"  # ESPN's spelling, so the app's short-name rules apply
EASTERN = ZoneInfo("America/New_York")
SEASON_RE = re.compile(r"(20\d\d)-(\d\d)")
# One announced start: "7 p.m.", "7:30 p.m.", "12 PM". Nothing else is a time.
TIME_RE = re.compile(r"^\d{1,2}(:\d{2})?\s*[ap]\.?m\.?$", re.I)


def die(msg: str) -> None:
    print(f"\n[X] {msg}")
    sys.exit(1)


def season_of(events: list[dict]) -> int | None:
    """The season number the games table uses: the year the season ENDS in, which is how
    ESPN and the app both label it (2026-27 is 2027). Read off the schedule's own title
    rather than guessed from a date, so an October exhibition and a March game agree."""
    for e in events:
        sched = e.get("schedule")
        title = sched.get("title") if isinstance(sched, dict) else str(sched or "")
        m = SEASON_RE.search(title or "")
        if m:
            return int(m.group(1)[:2] + m.group(2))
    return None


def start_utc(e: dict) -> str | None:
    """ISO start in UTC, with an unannounced time stored as midnight Eastern — the sentinel
    the rest of the pipeline and the app already read as "Time TBA".

    The site's `date` is Eastern local, but its clock is only meaningful when the `time`
    string is one plain time ("7 p.m."). A tournament slot that hasn't been drawn is
    written as "7:30 or 10:00 p.m." with a midnight clock — or, worse, as a literal
    "11:59 p.m.", which parses fine and would put an 11:59 PM tip on the Scores tab. No
    college game tips at 11:59 either, so that clock is a placeholder too."""
    local = e.get("date")
    if not local:
        return None
    try:
        dt = datetime.fromisoformat(local)
    except ValueError:
        return None
    if not TIME_RE.match((e.get("time") or "").strip()) or (dt.hour, dt.minute) == (23, 59):
        dt = dt.replace(hour=0, minute=0, second=0)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=EASTERN)
    return dt.astimezone(timezone.utc).isoformat()


def opponent_of(e: dict) -> tuple[str, bool]:
    """(name, is_exhibition). WVU writes "Maryland (exhibition)" as the opponent's name."""
    op = e.get("opponent")
    name = (op.get("title") or op.get("name") or "") if isinstance(op, dict) else str(op or "")
    exhibition = "exhibition" in name.lower()
    name = re.sub(r"\(\s*exhibition\s*\)", "", name, flags=re.I).strip()
    return name, exhibition


def venue_of(e: dict, neutral: bool) -> str | None:
    """Arena, plus the city for a neutral site (the arena alone says nothing about where
    "Michelob ULTRA Arena" is) and the event when there is one."""
    fac = e.get("facility")
    arena = (fac.get("title") if isinstance(fac, dict) else fac) or None
    city = e.get("location") if isinstance(e.get("location"), str) else None
    parts = [arena or city]
    if neutral and arena and city:
        parts = [f"{arena}, {city}"]
    tour = e.get("tournament")
    tour = tour.get("title") if isinstance(tour, dict) else None
    if tour:
        parts.append(f"({tour})")
    return " ".join(p for p in parts if p) or None


def placeholder(e: dict, sport: str, season: int) -> dict | None:
    opponent, exhibition = opponent_of(e)
    start = start_utc(e)
    if not opponent or not start or e.get("id") is None:
        return None
    where = str(e.get("locationIndicator") or e.get("location_indicator") or "").upper()
    home = where == "H"
    media = e.get("media") if isinstance(e.get("media"), dict) else {}
    return {
        "id": PLACEHOLDER_BASE + int(e["id"]),
        "sport_id": sport,
        "season": season,
        "week": None,
        "season_type": "exhibition" if exhibition else "regular",
        "start_date": start,
        "home_team": WVU if home else opponent,
        "away_team": opponent if home else WVU,
        "home_points": None,
        "away_points": None,
        "venue": venue_of(e, neutral=where == "N"),
        "status": "scheduled",
        "is_wvu_home": home,
        "broadcast": (media.get("tv") or "").strip() or None,
    }


def main() -> None:
    dry = "--dry-run" in sys.argv
    if not SB_URL or not SB_KEY:
        die("Missing SUPABASE_URL or SUPABASE_SECRET_KEY in .env")
    sb = create_client(SB_URL, SB_KEY)
    today = datetime.now(EASTERN).date().isoformat()

    for sport, url in SCHEDULES:
        print(f"\n{sport}: reading {url}")
        try:
            events = payload(fetch(url))
        except Exception as e:  # noqa: BLE001 — a thin schedule is fine, a crashed sync isn't
            print(f"  [!] {str(e)[:70]} — leaving placeholders alone")
            continue
        season = season_of(events or [])
        if not events or not season:
            print("  [!] no events parsed — leaving placeholders alone")
            continue

        existing = (sb.table("games").select("id,start_date")
                    .eq("sport_id", sport).eq("season", season).execute().data or [])
        espn_days = {eastern_day(g["start_date"]) for g in existing
                     if g["id"] < PLACEHOLDER_BASE}
        on_file = {g["id"] for g in existing if g["id"] >= PLACEHOLDER_BASE}

        wanted: dict[int, dict] = {}
        for e in events:
            row = placeholder(e, sport, season)
            if not row:
                continue
            day = eastern_day(row["start_date"])
            if day in espn_days:
                continue  # ESPN has it; theirs is the one with scores
            if row["season_type"] == "exhibition" and day < today:
                continue  # played, and not a game that counts
            wanted[row["id"]] = row

        stale = sorted(on_file - set(wanted))
        for r in sorted(wanted.values(), key=lambda r: r["start_date"]):
            tag = " (exhibition)" if r["season_type"] == "exhibition" else ""
            who = r["away_team"] if r["is_wvu_home"] else r["home_team"]
            mark = "  " if r["id"] in on_file else "+ "
            print(f"  {mark}{eastern_day(r['start_date'])}  {'vs' if r['is_wvu_home'] else 'at'} "
                  f"{who}{tag}  - {r['venue']}")
        for gid in stale:
            print(f"  - {gid}  (ESPN caught up, played, or removed from the official schedule)")

        if not dry:
            if wanted:
                sb.table("games").upsert(list(wanted.values())).execute()
            for gid in stale:
                sb.table("games").delete().eq("id", gid).execute()
        print(f"  {sport} {season}: {len(espn_days)} from ESPN, {len(wanted)} placeholders "
              f"({len(set(wanted) - on_file)} new), {len(stale)} removed")

    print(f"\n[OK] Official schedule fill-in synced{' [dry run]' if dry else ''}.")


if __name__ == "__main__":
    main()
