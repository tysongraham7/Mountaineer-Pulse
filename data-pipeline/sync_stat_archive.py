"""
Mountaineer Pulse - Stat Archive and Leaderboards (wvusports.com official stats)
===============================================================================
Keeps every season of WVU football, men's basketball and baseball stats that
wvusports.com publishes, and ranks them into the leaderboards the Team tab shows:
this season, any past season, career, and best single seasons.

Why wvusports.com and not the APIs the other syncs use: CFBD's per-player football
stats thin out before ~2016 (2012 has no defensive stats at all, 2005 has one
player) and its free tier is 1,000 calls a month. The school's own cumulative stats
are the official numbers, complete from the first season the site publishes, and
cost no quota. Each stats page carries them as the page's Nuxt state, so this reads
structured data rather than scraping table cells.

  football  2014 -   /sports/football/stats/2025
  mbb       2014-15  /sports/mens-basketball/stats/2025-26   (stored as 2026, like CBD)
  baseball  2015 -   /sports/baseball/stats/2026

Nothing earlier exists there; the archive says "since" its first season rather
than pretending to be all-time.

Each run:
  1. Fetches any season not stored yet, plus the newest stored season and the ones
     after it (the live season changes nightly; finished ones never do). A normal
     night is two or three pages per sport.
  2. Rewrites stat_archive / team_season_stats for each season it fetched.
  3. Fills team_records for past seasons: football's from CFBD (one call, back to
     1891, only while those seasons are missing), the others from the stats pages.
     Seasons already there are left alone; sync_football / sync_espn own the
     current ones.
  4. Re-ranks stat_leaders for every sport from the whole archive.
  5. Rebuilds record_book: WVU's all-time top-10 lists (record_book.json, made by
     build_record_book.py) brought current with every archived season.

A player's career is linked by normalized name (names.norm_name). wvusports.com's
roster bio ids change every season, so they can't link seasons.

Prereqs: migrate.py has been run; .env has SUPABASE_URL, SUPABASE_SECRET_KEY
(and CFBD_API_KEY, only needed for the one-time football records backfill).
Run:  python sync_stat_archive.py            (incremental, what the nightly job runs)
      python sync_stat_archive.py --full     (refetch every season)
"""

import json
import os
import re
import sys
import time
from collections import defaultdict
from datetime import date

import requests
from dotenv import load_dotenv
from supabase import create_client

from names import norm_name, same_person, split_name

load_dotenv()

SB_URL = os.getenv("SUPABASE_URL")
SB_KEY = os.getenv("SUPABASE_SECRET_KEY")
CFBD_KEY = os.getenv("CFBD_API_KEY")

SITE = "https://wvusports.com"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120 Safari/537.36"}
REQUEST_PAUSE = 2.0      # seconds between page fetches; a backfill is ~40 pages
TOP_N = 25               # rows kept per leaderboard

# First season each sport's stats page has data for (checked 2026-10-08: football 2013,
# basketball 2013-14 and baseball 2014 all come back empty).
SPORTS = {
    "football": {"path": "football", "first": 2014},
    "mbb": {"path": "mens-basketball", "first": 2015},
    "baseball": {"path": "baseball", "first": 2015},
}

FOOTER_NAMES = {"total", "totals", "team", "tm", "opponents", "opponent", "opp"}


def die(msg: str) -> None:
    print(f"\n[X] {msg}")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Fetching and decoding
# ---------------------------------------------------------------------------

def season_url(sport: str, season: int) -> str:
    """Basketball pages are named for both years ("2025-26"); we store the year it ends."""
    label = f"{season - 1}-{str(season)[-2:]}" if sport == "mbb" else str(season)
    return f"{SITE}/sports/{SPORTS[sport]['path']}/stats/{label}"


def season_label(sport: str, season: int) -> str:
    return f"{season - 1}-{str(season)[-2:]}" if sport == "mbb" else str(season)


def fetch(url: str, attempts: int = 3) -> str:
    """GET with retries. Same contract as sync_rosters.fetch: wvusports.com is sometimes
    very slow, and a truncated page must fail loudly rather than parse as an empty season."""
    delay = 5.0
    last: Exception | None = None
    for i in range(1, attempts + 1):
        try:
            html = requests.get(url, headers=UA, timeout=60).text
            if "</html>" not in html[-2000:]:
                raise requests.RequestException(
                    f"incomplete response ({len(html)} bytes, no closing </html>)")
            return html
        except requests.RequestException as e:
            last = e
            if i < attempts:
                print(f"    (fetch failed {type(e).__name__} - retry {i}/{attempts - 1} in {delay:.0f}s)")
                time.sleep(delay)
                delay *= 2
    raise last  # type: ignore[misc]


_WRAPPERS = {"Reactive", "ShallowReactive", "Ref", "ShallowRef", "EmptyRef", "EmptyShallowRef"}


def nuxt_state(html: str):
    """Decode the page's __NUXT_DATA__ payload.

    Nuxt serializes its state as one flat JSON array in which every object value and list
    item is an INDEX into that array (devalue format); -1 means undefined. Reactive
    wrappers arrive as ["Reactive", idx]. Shared values are referenced more than once,
    hence the memo."""
    m = re.search(r'<script[^>]*id="__NUXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        return None
    arr = json.loads(m.group(1))
    memo: dict[int, object] = {}

    def res(i):
        if not isinstance(i, int) or i < 0 or i >= len(arr):
            return None
        if i in memo:
            return memo[i]
        v = arr[i]
        if isinstance(v, list):
            if v and isinstance(v[0], str) and v[0] in _WRAPPERS:
                out = res(v[1]) if len(v) > 1 else None
            elif v and isinstance(v[0], str) and v[0] in ("Date", "BigInt"):
                out = v[1] if len(v) > 1 else None
            elif v and isinstance(v[0], str) and v[0] == "Set":
                out = [res(x) for x in v[1:]]
            else:
                lst: list = []
                memo[i] = lst
                lst.extend(res(x) for x in v)
                return lst
        elif isinstance(v, dict):
            obj: dict = {}
            memo[i] = obj
            for k, x in v.items():
                obj[k] = res(x)
            return obj
        else:
            out = v
        memo[i] = out
        return out

    return res(0)


def roster_url(sport: str, season: int) -> str:
    return f"{SITE}/sports/{SPORTS[sport]['path']}/roster/{season_label(sport, season)}"


def roster_players(state) -> list[dict]:
    """That season's roster page: [{name, jersey, position, photo}]. Empty when unreadable;
    the roster only polishes names and photos, so the stats never wait on it."""
    try:
        rosters = state["pinia"]["roster"]["roster"]
    except (KeyError, TypeError):
        return []
    out = []
    for r in (rosters or {}).values():
        for p in (r or {}).get("players") or []:
            if not isinstance(p, dict):
                continue
            name = f"{(p.get('firstName') or '').strip()} {(p.get('lastName') or '').strip()}".strip()
            if not name:
                continue
            img = p.get("image") or {}
            photo = img.get("absoluteUrl") or (SITE + img["url"] if img.get("url") else None)
            out.append({"name": name, "jersey": (p.get("jerseyNumber") or "").strip() or None,
                        "position": (p.get("positionShort") or "").strip() or None, "photo": photo})
    return out


def cumulative(state) -> dict | None:
    """The season's cumulative stats block, or None when the page has no season yet."""
    try:
        blocks = state["pinia"]["statsSeason"]["cumulativeStats"]
    except (KeyError, TypeError):
        return None
    for b in (blocks or {}).values():
        if isinstance(b, dict) and b.get("overallIndividualStats"):
            return b
    return None


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def num(x) -> float | None:
    """'1,276' -> 1276.0, '59.412%' -> 59.412, '.361' -> 0.361. Blank/NaN/'-' -> None."""
    if x is None or isinstance(x, bool):
        return None
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x).strip().replace(",", "").rstrip("%")
    if not s or s in ("-", "--") or s.lower() == "nan":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def pair(x) -> tuple[float | None, float | None]:
    """'10-12' -> (10, 12)."""
    parts = str(x or "").replace(",", "").split("-")
    if len(parts) != 2:
        return None, None
    return num(parts[0]), num(parts[1])


def innings_to_outs(ip) -> float | None:
    """Baseball innings are written in thirds: 534.1 is 534 1/3, not 534.1."""
    v = num(ip)
    if v is None:
        return None
    whole = int(v)
    thirds = round((v - whole) * 10)
    return float(whole * 3 + min(thirds, 2))


def display_name(raw: str) -> str:
    """'Fox Jr., Scotty' -> 'Scotty Fox Jr.'; 'SHELL,RUSHEL' -> 'Rushel Shell';
    'II,TONY FIELDS' (suffix filed as the surname) -> 'Tony Fields II'."""
    s = (raw or "").strip()
    if "," in s:
        last, first = (x.strip() for x in s.split(",", 1))
        if s.isupper():
            last, first = last.title(), first.title()
        if last and not norm_name(last):   # the "surname" is only a suffix
            suffix = last.upper() if last.lower() in ("ii", "iii", "iv", "v") else last
            s = f"{first.title()} {suffix}"
        else:
            s = f"{first} {last}"
    elif s.isupper():
        s = s.title()
    return re.sub(r"\s+", " ", s).strip()


def surnames(raw: str) -> set[str]:
    """Surname tokens of a 'Last, First' name, suffixes dropped."""
    return set(norm_name((raw or "").split(",")[0]).split())


# Per-table field maps: source field -> our stat key. Anything not listed is ignored.
FB_TABLES = {
    "individualRushingStats": ("rushing", {"attempts": "att", "net": "yds", "touchdowns": "td", "longest": "long"}),
    "individualPassingStats": ("passing", {"completions": "cmp", "attempts": "att", "yards": "yds",
                                           "touchdowns": "td", "interceptions": "int", "longest": "long"}),
    "individualReceivingStats": ("receiving", {"number": "rec", "yards": "yds", "touchdowns": "td", "longest": "long"}),
    "individualDefensiveStats": ("defense", {"totalTackles": "tkl", "tacklesUnassisted": "solo",
                                             "tacklesAssisted": "ast", "totalTacklesForLoss": "tfl",
                                             "totalSacks": "sacks", "passesIntercepted": "int",
                                             "interceptionYards": "int_yds", "passBreakups": "pbu",
                                             "quarterbackHurries": "qbh", "fumblesForces": "ff",
                                             "fumblesRecovered": "fr", "blockedKicks": "blk"}),
    "individualPuntingStats": ("punting", {"number": "no", "yards": "yds", "inside20": "in20", "longest": "long"}),
    "individualFieldGoalStats": ("kicking", {"made": "fgm", "attempts": "fga", "longestFieldGoal": "long"}),
    "individualPuntReturnStats": ("punt_ret", {"number": "no", "yards": "yds", "touchdowns": "td"}),
    "individualKickReturnStats": ("kick_ret", {"number": "no", "yards": "yds", "touchdowns": "td"}),
    "individualScoringStats": ("scoring", {"touchdowns": "td", "points": "pts"}),
}
MBB_FIELDS = {
    "gamesPlayed": "gp", "gamesStarted": "gs", "minutesPlayed": "min", "points": "pts",
    "rebounds": "reb", "reboundsOffensive": "oreb", "reboundsDefensive": "dreb",
    "assists": "ast", "steals": "stl", "blocks": "blk", "turnovers": "to",
    "fieldGoals": "fgm", "fieldGoalsAttempted": "fga",
    "threePointFieldGoals": "tpm", "threePointFieldGoalsAttempted": "tpa",
    "freeThrows": "ftm", "freeThrowsAttempted": "fta", "personalFouls": "pf",
    "highestPoints": "high",
}
BSB_TABLES = {
    "individualHittingStats": ("hitting", {
        "gamesPlayed": "gp", "gamesStarted": "gs", "atBats": "ab", "runs": "r", "hits": "h",
        "doubles": "2b", "triples": "3b", "homeRuns": "hr", "runsBattedIn": "rbi",
        "totalBases": "tb", "walks": "bb", "hitByPitch": "hbp", "strikeouts": "so",
        "sacrificeFlies": "sf", "sacrificeHits": "sh", "stolenBases": "sb",
        "stolenBasesAttemps": "sba", "caughtStealing": "cs"}, "meetsMinHittingStats"),
    "individualPitchingStats": ("pitching", {
        "appearances": "app", "gamesStarted": "gs", "wins": "w", "losses": "l", "saves": "sv",
        "hitsAllowed": "h", "runsAllowed": "r", "earnedRunsAllowed": "er", "walksAllowed": "bb",
        "strikeouts": "so", "homeRunsAllowed": "hr", "gamesCompleted": "cg", "shutouts": "sho",
        "hitBatters": "hbp", "opponentsAtBats": "oab"}, "meetsMinPitchingStats"),
}

# Stats that combine across seasons by max, not sum (a career long is the longest one).
MAX_STATS = {"long", "high"}


class Season:
    """Every stat line on one season's page, keyed by player then category.stat.

    Each row carries two names, and they can disagree. `nameFromStats` is the name in the
    official stat file: abbreviated ("SMALLWOOD,W") but it is who made the play.
    `playerName` is wvusports.com's link from that line to a roster page, made by jersey
    number, so two players sharing #4 sends Wendell Smallwood's 1,519 rushing yards to the
    roster page of defensive back Antonio Crawford. When the surnames disagree, the stat
    file wins and the (wrong) headshot is dropped.

    The same check catches a worse fault: a whole opponent box score filed under WVU (2014
    football has Kansas's lineup from one game, 2014-15 basketball Maryland's). Those
    lines link to whichever WVU player wore the number and played exactly one game, so a
    mismatched line with one game or fewer is dropped rather than credited to anyone."""

    def __init__(self, stat_gp: dict[str, float] | None = None, trusted: set[str] | None = None):
        self.players: dict[str, dict] = {}   # key -> {name, jersey, photo, stats{cat.stat: v}}
        self.team_games = 0
        self.stat_gp = stat_gp or {}          # stat-file name -> most games in any table
        self.trusted = trusted or set()       # stat-file names some row links correctly
        self.relinked: set[str] = set()
        self.dropped: set[str] = set()

    def identity(self, row: dict) -> tuple[str, bool] | None:
        """(display name, roster photo trustworthy), or None for a line to drop."""
        linked = (row.get("playerName") or "").strip()
        filed = (row.get("nameFromStats") or "").strip()
        if linked and filed and surnames(linked) and surnames(filed) \
                and not (surnames(linked) & surnames(filed)):
            # A kicker's tables have no games column, so a name that's linked correctly on
            # any other row this season is a Mountaineer whatever his games count says.
            if filed not in self.trusted and self.stat_gp.get(filed, 0) <= 1:
                self.dropped.add(f"{filed} (linked to {linked})")
                return None
            self.relinked.add(f"{filed} (was linked to {linked})")
            return display_name(filed), False
        if linked and not surnames(linked) and filed:
            return display_name(filed), True
        return display_name(linked or filed), True

    def add(self, row: dict, category: str, fields: dict, qual_field: str | None = None):
        if row.get("isAFooterStat"):
            return
        raw = row.get("playerName") or row.get("nameFromStats") or ""
        if raw.strip().lower() in FOOTER_NAMES:
            return
        who = self.identity(row)
        if who is None:
            return
        name, photo_ok = who
        key = norm_name(name)
        if not key or key in FOOTER_NAMES:
            return
        p = self.players.setdefault(key, {"name": name, "jersey": None, "photo": None,
                                          "position": None, "stats": {}})
        jersey = (row.get("playerUniform") or "").strip()
        if jersey and not p["jersey"]:
            p["jersey"] = jersey.lstrip("0") or "0"
        img = (row.get("playerImageUrl") or "").strip()
        if img and photo_ok and not p["photo"]:
            p["photo"] = img if img.startswith("http") else SITE + img
        s: dict[str, float] = {}
        for src, stat in fields.items():
            v = num(row.get(src))
            if v is not None:
                s[f"{category}.{stat}"] = v
        gp = num(row.get("gamesPlayed"))
        if gp is None and row.get("gamesPlayedAndStarted"):
            gp, gs = pair(row["gamesPlayedAndStarted"])
            if gs is not None and category == "basketball":
                s["basketball.gs"] = gs
        if gp is not None:
            s["general.gp"] = gp
        if category == "pitching":
            outs = innings_to_outs(row.get("inningsPitched"))
            if outs is not None:
                s["pitching.outs"] = outs
        # Stored as 0 or 1 when the page says, absent when it doesn't, so the leaderboard
        # can tell "didn't qualify" from "this page has no flag" and fall back to a floor.
        if qual_field and isinstance(row.get(qual_field), bool):
            s[f"{category}.qual"] = 1.0 if row[qual_field] else 0.0
        # The same player can own two rows of one table -- a relinked line beside his
        # correctly linked one -- and those are different games, so they add.
        merge_stats(p["stats"], s)


def merge_stats(dst: dict, src: dict) -> None:
    """Fold one player-season's stats into another's: two spellings of the same player.

    Games played comes from every table, so both spellings carry the season's count -- the
    same number seen twice, not two to add. Every other stat sits in one table, where two
    rows are different games, so those add."""
    for sk, v in src.items():
        if sk not in dst:
            dst[sk] = v
        elif sk.startswith("general.") or sk.split(".")[1] in MAX_STATS or sk.endswith(".qual"):
            dst[sk] = max(dst[sk], v)
        else:
            dst[sk] += v


def apply_roster(season: Season, roster: list[dict]) -> int:
    """Use that season's roster for each stat line's full name, headshot and position.

    The stat file abbreviates ("SMALLWOOD,W", "HAYNES,JONATHA"), and a line we relinked
    away from the wrong roster page has no photo at all. The roster is matched by name, not
    jersey -- jersey sharing is what broke the site's own links. Returns how many names it
    completed."""
    if not roster:
        return 0
    completed = 0
    for key in list(season.players):
        p = season.players[key]
        hits = [r for r in roster if _same_player_name(p["name"], r["name"])]
        if len(hits) > 1 and p["jersey"]:
            hits = [r for r in hits if r["jersey"] == p["jersey"]]
        if len(hits) != 1:
            continue
        r = hits[0]
        p["on_roster"] = True
        p["position"] = r["position"]
        p["photo"] = r["photo"] or p["photo"]
        mine, theirs = norm_name(p["name"]).split(), norm_name(r["name"]).split()
        if mine and theirs and len(theirs[0]) > len(mine[0]) and theirs[0].startswith(mine[0]):
            p["name"] = r["name"]
            completed += 1
            new_key = norm_name(r["name"])
            if new_key != key:
                del season.players[key]
                if new_key in season.players:
                    other = season.players[new_key]
                    merge_stats(other["stats"], p["stats"])
                    for f in ("photo", "position", "jersey"):
                        other[f] = other[f] or p[f]
                else:
                    season.players[new_key] = p
    return completed


def drop_visitors(season: Season, year: int, roster: list[dict],
                  known: dict[str, set[int]]) -> list[str]:
    """Remove an opponent's players filed under WVU without a roster link to give them away.

    2014-15 basketball carries Maryland's lineup from one game (Melo Trimble, Dez Wells)
    under plain stat-file names, so the mislink check in Season.identity never fires. A
    visitor has three marks together: absent from that season's WVU roster page, one game
    played, and no other WVU season under his name. Any one alone proves nothing -- old
    roster pages miss players who left mid-season (Oscar Tshiebwe, 2020-21) -- so it takes
    all three. The cost is a one-game walk-on missing from the same incomplete roster, whose
    line is a rounding error. With no roster page to compare against, nothing is dropped."""
    if not roster:
        return []
    out = []
    for key in list(season.players):
        p = season.players[key]
        if p.get("on_roster") or p["stats"].get("general.gp", 0) > 1:
            continue
        elsewhere = any(yr != year and _same_player_name(p["name"], name)
                        for name, years in known.items() for yr in years)
        if not elsewhere:
            out.append(p["name"])
            del season.players[key]
    return sorted(out)


def footer_games(rows: list) -> int:
    for r in rows or []:
        if r.get("isAFooterStat"):
            g = num(r.get("gamesPlayed"))
            if g:
                return int(g)
    return 0


def parse_season(sport: str, block: dict) -> Season:
    ind = (block.get("overallIndividualStats") or {}).get("individualStats")
    # Games played per stat-file name across every table, so a line from a table without
    # a games column (punting, scoring) is judged by the same count as the rest of his.
    stat_gp: dict[str, float] = defaultdict(float)
    trusted: set[str] = set()
    for table in (ind.values() if isinstance(ind, dict) else [ind or []]):
        for r in table or []:
            filed = (r.get("nameFromStats") or "").strip()
            gp = num(r.get("gamesPlayed")) or num(r.get("appearances"))
            if filed and gp:
                stat_gp[filed] = max(stat_gp[filed], gp)
            if filed and surnames(filed) & surnames(r.get("playerName") or ""):
                trusted.add(filed)
    out = Season(stat_gp, trusted)
    if sport == "football":
        # A kicker's field-goal row can arrive with no stat-file name at all, leaving only
        # the (wrong) roster link: 2023 credits Michael Hayes's 17 field goals to Josiah
        # Jackson, who shared #22. His kickoff and scoring rows on the same link do name
        # HAYES,MICHAEL, and a specialist's tables travel together, so a nameless row in one
        # borrows the name filed for the same link in the others.
        specialist = ("individualFieldGoalStats", "individualPuntingStats", "individualKickoffStats",
                      "individualScoringStats")
        filed_for: dict[tuple, set] = defaultdict(set)
        for table in specialist:
            for r in (ind or {}).get(table) or []:
                if (r.get("nameFromStats") or "").strip():
                    filed_for[(r.get("playerName"), r.get("playerUniform"))].add(r["nameFromStats"].strip())
        for table, (cat, fields) in FB_TABLES.items():
            for r in (ind or {}).get(table) or []:
                if table in specialist and not (r.get("nameFromStats") or "").strip():
                    names = filed_for.get((r.get("playerName"), r.get("playerUniform")), set())
                    if len(names) == 1:
                        r = {**r, "nameFromStats": next(iter(names))}
                out.add(r, cat, fields)
        out.team_games = footer_games((ind or {}).get("individualRushingStats"))
    elif sport == "mbb":
        for r in ind or []:
            out.add(r, "basketball", MBB_FIELDS)
        out.team_games = footer_games(ind)
    else:
        for table, (cat, fields, qual) in BSB_TABLES.items():
            for r in (ind or {}).get(table) or []:
                out.add(r, cat, fields, qual)
        w, l = pair((block.get("overallTeamStats") or {}).get("teamStats", {}).get("ourWinsLosses"))
        out.team_games = int((w or 0) + (l or 0))
    if not out.team_games:
        rec = block.get("record") or ""
        w, l = pair(rec.split(",")[0].strip())
        out.team_games = int((w or 0) + (l or 0))
    return out


# ---------------------------------------------------------------------------
# Team stats: WVU vs opponents, formatted once here so the app just prints them
# ---------------------------------------------------------------------------

def f_int(v):
    n = num(v)
    return None if n is None else f"{n:,.0f}"


def f_1(v):
    n = num(v)
    return None if n is None else f"{n:,.1f}"


def f_pct(v):
    """'45.238%' -> '45.2%'."""
    n = num(v)
    return None if n is None else f"{n:.1f}%"


def f_avg3(v):
    """'.449' -> '.449'; also accepts 0.449."""
    n = num(v)
    if n is None:
        return None
    return f"{n:.3f}".lstrip("0") if n < 1 else f"{n:.3f}"


def f_raw(v):
    s = str(v).strip() if v is not None else ""
    return s or None


def team_rows(sport: str, season: int, block: dict, games: int) -> list[dict]:
    ts = (block.get("overallTeamStats") or {}).get("teamStats") or {}

    def side(prefix):
        return lambda k: ts.get(f"{prefix}{k}")

    out = []

    def add(stat, label, grp, wvu, opp):
        if wvu is None and opp is None:
            return
        out.append({"id": f"{sport}|{season}|{stat}", "sport_id": sport, "season": season,
                    "stat": stat, "label": label, "grp": grp, "ord": len(out), "wvu": wvu, "opp": opp})

    rec = (block.get("record") or "").split(",")
    add("record", "Record", "Record", f_raw(rec[0]) if rec and rec[0] else None, None)
    if len(rec) > 1 and rec[1].strip():
        add("conf_record", "Conference", "Record", f_raw(rec[1]), None)
    add("games", "Games", "Record", str(games) if games else None, None)

    us, them = side("our"), side("opponent")

    def both(stat, label, grp, key, fmt):
        add(stat, label, grp, fmt(us(key)), fmt(them(key)))

    if sport == "football":
        both("pts", "Points", "Scoring", "Score", f_int)
        both("ppg", "Points / Game", "Scoring", "PointsPerGame", f_1)
        both("td", "Touchdowns", "Scoring", "TouchdownsScored", f_int)
        both("ypg", "Total Yards / Game", "Offense", "TotalAveragePerGame", f_1)
        both("ypp", "Yards / Play", "Offense", "TotalAveragePerPlay", f_1)
        both("rush_ypg", "Rushing Yards / Game", "Offense", "RushingYardsAveragePerGame", f_1)
        both("ypc", "Yards / Carry", "Offense", "RushingYardsAveragePerRush", f_1)
        both("rush_td", "Rushing TD", "Offense", "RushingTouchdowns", f_int)
        both("pass_ypg", "Passing Yards / Game", "Offense", "PassingAveragePerGame", f_1)
        both("ypa", "Yards / Pass", "Offense", "PassingAveragePerPass", f_1)
        both("pass_td", "Passing TD", "Offense", "PassingTouchdowns", f_int)

        def cmp_att_int(v):
            parts = str(v or "").split("-")   # source order is Att-Comp-Int
            return f"{parts[1]}-{parts[0]}-{parts[2]}" if len(parts) == 3 else None
        both("cai", "Comp-Att-Int", "Offense", "PassingAttCompInt", cmp_att_int)
        both("first_downs", "First Downs", "Situational", "FirstDowns", f_int)

        # Conversions and rate on separate rows: "62-179 (34.6%)" wraps in a phone column.
        both("third", "Third Down", "Situational", "ThirdDownConversions", f_raw)
        both("third_pct", "Third Down %", "Situational", "ThirdDownPercentage", f_pct)
        both("fourth", "Fourth Down", "Situational", "FourthDownConversions", f_raw)
        both("fourth_pct", "Fourth Down %", "Situational", "FourthDownPercentage", f_pct)
        both("rz_td", "Red Zone TD", "Situational", "RedzoneTouchdowns", f_raw)
        both("rz", "Red Zone Scores", "Situational", "RedzoneScores", f_raw)

        def turnovers(prefix):
            _, fl = pair(ts.get(f"{prefix}FumblesNumAndLost"))
            parts = str(ts.get(f"{prefix}PassingAttCompInt") or "").split("-")
            ints = num(parts[2]) if len(parts) == 3 else None
            return f_int(fl + ints) if fl is not None and ints is not None else None
        add("turnovers", "Turnovers Lost", "Situational", turnovers("our"), turnovers("opponent"))
        both("sacks", "Sacks-Yards", "Situational", "SacksByYards", f_raw)
        both("pen", "Penalties-Yards", "Situational", "PenaltiesYards", f_raw)
        both("top", "Possession / Game", "Situational", "TimeOfPosessionPerGame", f_raw)
        both("fg", "Field Goals", "Special Teams", "FieldgoalsAttempts", f_raw)
        both("punt_avg", "Punt Average", "Special Teams", "PuntsAveragePerPunt", f_1)
        both("punt_net", "Net Punting", "Special Teams", "PuntsNetAverage", f_1)
        both("kr_avg", "Kick Return Avg", "Special Teams", "KickReturnsAverage", f_1)
        both("pr_avg", "Punt Return Avg", "Special Teams", "PuntReturnsAverage", f_1)

        def attendance(v):
            parts = str(v or "").split("-", 1)
            return parts[1] if len(parts) == 2 and parts[1].strip() else None
        add("attendance", "Avg Home Attendance", "Attendance",
            attendance(us("HomegamesAndAverageAttendance")), None)

    elif sport == "mbb":
        both("ppg", "Points / Game", "Scoring", "PointsPerGame", f_1)
        add("margin", "Scoring Margin", "Scoring", f_1(us("ScoringMargin")), None)
        both("fg", "Field Goals", "Shooting", "FieldGoalsMadeAndAttempts", f_raw)
        both("fg_pct", "FG %", "Shooting", "FieldGoalPercentage", f_avg3)
        both("tp", "3-Pointers", "Shooting", "ThreePointFieldGoalsPadeAndAttempted", f_raw)
        both("tp_pct", "3PT %", "Shooting", "ThreePointFieldGoalPercentage", f_avg3)
        both("ft", "Free Throws", "Shooting", "FreeThrowsMadeAndAttempted", f_raw)
        both("ft_pct", "FT %", "Shooting", "FreeThrowsPercentage", f_avg3)
        both("rpg", "Rebounds / Game", "Possession", "ReboundsPerGame", f_1)
        add("reb_margin", "Rebound Margin", "Possession", f_1(us("ReboundsMargin")), None)
        both("apg", "Assists / Game", "Possession", "AssistsPerGame", f_1)
        both("topg", "Turnovers / Game", "Possession", "TurnoversPerGame", f_1)
        add("to_margin", "Turnover Margin", "Possession", f_1(us("TurnoverMargin")), None)
        both("spg", "Steals / Game", "Defense", "StealsPerGame", f_1)
        both("bpg", "Blocks / Game", "Defense", "BlocksPerGame", f_1)

        def attendance(v):
            parts = str(v or "").split("-", 1)
            return parts[1] if len(parts) == 2 and parts[1].strip() else None
        add("attendance", "Avg Home Attendance", "Attendance",
            attendance(us("HomeGamesAndAverageAttendance")), None)

    else:
        both("avg", "Batting Average", "Hitting", "BattingAverage", f_avg3)
        both("slg", "Slugging %", "Hitting", "SluggingPercentage", f_avg3)
        both("ops", "OPS", "Hitting", "Ops", f_avg3)
        both("r", "Runs", "Hitting", "Runs", f_int)
        both("h", "Hits", "Hitting", "Hits", f_int)
        both("2b", "Doubles", "Hitting", "Doubles", f_int)
        both("hr", "Home Runs", "Hitting", "HomeRuns", f_int)
        both("bb", "Walks", "Hitting", "Walks", f_int)
        both("sb", "Stolen Bases", "Hitting", "StolenBasesAttempts", f_raw)

        def era(prefix):
            outs = innings_to_outs(ts.get(f"{prefix}InningsPitched"))
            er = num(ts.get(f"{prefix}EarnedRunsAllowed"))
            return f"{er * 27 / outs:.2f}" if outs and er is not None else None
        add("era", "ERA", "Pitching", era("our"), era("opponent"))
        both("whip", "WHIP", "Pitching", "Whip", lambda v: None if num(v) is None else f"{num(v):.2f}")
        both("so", "Strikeouts", "Pitching", "Strikeouts", f_int)
        both("bb_allowed", "Walks Allowed", "Pitching", "WalksAllowed", f_int)
        both("hr_allowed", "Home Runs Allowed", "Pitching", "HomerunsAllowed", f_int)
        both("fld", "Fielding %", "Fielding", "FieldingPercentage", f_avg3)
        both("e", "Errors", "Fielding", "Errors", f_int)
        both("dp", "Double Plays", "Fielding", "DoublePlays", f_int)
    return out


# ---------------------------------------------------------------------------
# Leaderboards
#
# One definition per board. `val` reads a player's totals (season or career) and
# returns the number to rank, or None when it doesn't apply. `q_season` / `q_career`
# are the qualification floors for rate stats -- without them a 2-for-2 backup leads
# the completion-percentage board. Season floors scale with the team's games played
# (`g`), so the live season isn't empty in September.
# ---------------------------------------------------------------------------

def g(t, k):
    return t.get(k, 0.0)


def ratio(a, b, scale=1.0):
    return a * scale / b if b else None


def passer_rating(t):
    att = g(t, "passing.att")
    if not att:
        return None
    return (8.4 * g(t, "passing.yds") + 330 * g(t, "passing.td") + 100 * g(t, "passing.cmp")
            - 200 * g(t, "passing.int")) / att


def obp(t):
    den = g(t, "hitting.ab") + g(t, "hitting.bb") + g(t, "hitting.hbp") + g(t, "hitting.sf")
    return ratio(g(t, "hitting.h") + g(t, "hitting.bb") + g(t, "hitting.hbp"), den)


def slg(t):
    return ratio(g(t, "hitting.tb"), g(t, "hitting.ab"))


def ops(t):
    o, s = obp(t), slg(t)
    return o + s if o is not None and s is not None else None


def qualified(cat, key, per_game):
    """Baseball pages flag who meets the NCAA minimum for the season; use their call, and
    a per-game floor on a page that doesn't say."""
    def check(t, games):
        if f"{cat}.qual" in t:
            return t[f"{cat}.qual"] >= 1
        return g(t, key) >= per_game * games
    return check


HIT_QUAL = qualified("hitting", "hitting.ab", 2.0)
PITCH_QUAL = qualified("pitching", "pitching.outs", 3.0)


def at_least(key, per_game=None, total=None):
    def check(t, games):
        need = per_game * games if per_game is not None else total
        return g(t, key) >= (need or 0)
    return check


def B(key, title, group, val, fmt="int", hero=False, asc=False, q_season=None, q_career=None,
      detail=None, career=True, best_floor=None):
    """`best_floor` (stat, minimum) is an extra bar for the best-single-season board, where a
    short season would otherwise win on a qualifier scaled to its own length: baseball's
    2020 lasted 16 games, so 25 innings qualified and topped the all-time ERA list."""
    return {"key": key, "title": title, "group": group, "val": val, "fmt": fmt, "hero": hero,
            "asc": asc, "q_season": q_season, "q_career": q_career, "detail": detail,
            "career": career, "best_floor": best_floor}


HIT_FLOOR = ("hitting.ab", 120)
PITCH_FLOOR = ("pitching.outs", 150)   # 50 innings


def stat(key):
    return lambda t: t.get(key)


def n(v):
    return f"{v:,.0f}"


BOARDS = {
    "football": [
        B("pass_yds", "Passing Yards", "Passing", stat("passing.yds"), hero=True,
          detail=lambda t: f"{n(g(t, 'passing.cmp'))}/{n(g(t, 'passing.att'))}"),
        B("pass_td", "Passing TD", "Passing", stat("passing.td")),
        B("pass_rating", "Passer Rating", "Passing", passer_rating, fmt="1",
          q_season=at_least("passing.att", per_game=10), q_career=at_least("passing.att", total=300),
          detail=lambda t: f"{n(g(t, 'passing.att'))} att"),
        B("cmp_pct", "Completion %", "Passing",
          lambda t: ratio(g(t, "passing.cmp"), g(t, "passing.att"), 100), fmt="pct",
          q_season=at_least("passing.att", per_game=10), q_career=at_least("passing.att", total=300),
          detail=lambda t: f"{n(g(t, 'passing.cmp'))}/{n(g(t, 'passing.att'))}"),
        B("rush_yds", "Rushing Yards", "Rushing", stat("rushing.yds"), hero=True,
          detail=lambda t: f"{n(g(t, 'rushing.att'))} car"),
        B("rush_td", "Rushing TD", "Rushing", stat("rushing.td")),
        B("ypc", "Yards / Carry", "Rushing", lambda t: ratio(g(t, "rushing.yds"), g(t, "rushing.att")),
          fmt="1", q_season=at_least("rushing.att", per_game=4), q_career=at_least("rushing.att", total=150),
          detail=lambda t: f"{n(g(t, 'rushing.att'))} car"),
        B("rec", "Receptions", "Receiving", stat("receiving.rec")),
        B("rec_yds", "Receiving Yards", "Receiving", stat("receiving.yds"),
          detail=lambda t: f"{n(g(t, 'receiving.rec'))} rec"),
        B("rec_td", "Receiving TD", "Receiving", stat("receiving.td")),
        B("ypr", "Yards / Catch", "Receiving", lambda t: ratio(g(t, "receiving.yds"), g(t, "receiving.rec")),
          fmt="1", q_season=at_least("receiving.rec", per_game=1.5), q_career=at_least("receiving.rec", total=50),
          detail=lambda t: f"{n(g(t, 'receiving.rec'))} rec"),
        B("tkl", "Tackles", "Defense", stat("defense.tkl"), hero=True,
          detail=lambda t: f"{n(g(t, 'defense.solo'))} solo"),
        B("tfl", "Tackles for Loss", "Defense", stat("defense.tfl"), fmt="1"),
        B("sacks", "Sacks", "Defense", stat("defense.sacks"), fmt="1"),
        B("def_int", "Interceptions", "Defense", stat("defense.int")),
        B("pbu", "Pass Breakups", "Defense", stat("defense.pbu")),
        B("ff", "Forced Fumbles", "Defense", stat("defense.ff")),
        B("pts", "Points", "Special Teams", stat("scoring.pts")),
        B("fgm", "Field Goals", "Special Teams", stat("kicking.fgm"),
          detail=lambda t: f"{n(g(t, 'kicking.fgm'))}/{n(g(t, 'kicking.fga'))}"),
        B("fg_pct", "Field Goal %", "Special Teams",
          lambda t: ratio(g(t, "kicking.fgm"), g(t, "kicking.fga"), 100), fmt="pct",
          q_season=at_least("kicking.fga", per_game=0.75), q_career=at_least("kicking.fga", total=25),
          detail=lambda t: f"{n(g(t, 'kicking.fgm'))}/{n(g(t, 'kicking.fga'))}"),
        B("punt_avg", "Punt Average", "Special Teams", lambda t: ratio(g(t, "punting.yds"), g(t, "punting.no")),
          fmt="1", q_season=at_least("punting.no", per_game=2.5), q_career=at_least("punting.no", total=75),
          detail=lambda t: f"{n(g(t, 'punting.no'))} punts"),
        B("kr_avg", "Kick Return Avg", "Special Teams",
          lambda t: ratio(g(t, "kick_ret.yds"), g(t, "kick_ret.no")), fmt="1",
          q_season=at_least("kick_ret.no", per_game=1), q_career=at_least("kick_ret.no", total=25),
          detail=lambda t: f"{n(g(t, 'kick_ret.no'))} ret"),
    ],
    "mbb": [
        B("ppg", "Points / Game", "Scoring", lambda t: ratio(g(t, "basketball.pts"), g(t, "general.gp")),
          fmt="1", hero=True, q_season=at_least("general.gp", per_game=0.5),
          q_career=at_least("general.gp", total=50), detail=lambda t: f"{n(g(t, 'general.gp'))} gp"),
        B("pts", "Points", "Scoring", stat("basketball.pts")),
        B("high", "Season High", "Scoring", stat("basketball.high"), career=False),
        B("rpg", "Rebounds / Game", "Rebounding", lambda t: ratio(g(t, "basketball.reb"), g(t, "general.gp")),
          fmt="1", hero=True, q_season=at_least("general.gp", per_game=0.5),
          q_career=at_least("general.gp", total=50), detail=lambda t: f"{n(g(t, 'general.gp'))} gp"),
        B("reb", "Rebounds", "Rebounding", stat("basketball.reb")),
        B("oreb", "Offensive Rebounds", "Rebounding", stat("basketball.oreb")),
        B("apg", "Assists / Game", "Playmaking", lambda t: ratio(g(t, "basketball.ast"), g(t, "general.gp")),
          fmt="1", hero=True, q_season=at_least("general.gp", per_game=0.5),
          q_career=at_least("general.gp", total=50), detail=lambda t: f"{n(g(t, 'general.gp'))} gp"),
        B("ast", "Assists", "Playmaking", stat("basketball.ast")),
        B("ato", "Assist / Turnover", "Playmaking", lambda t: ratio(g(t, "basketball.ast"), g(t, "basketball.to")),
          fmt="2", q_season=at_least("basketball.ast", per_game=1.5),
          q_career=at_least("basketball.ast", total=150),
          detail=lambda t: f"{n(g(t, 'basketball.ast'))} ast"),
        B("stl", "Steals", "Defense", stat("basketball.stl")),
        B("blk", "Blocks", "Defense", stat("basketball.blk")),
        B("fg_pct", "FG %", "Shooting", lambda t: ratio(g(t, "basketball.fgm"), g(t, "basketball.fga"), 100),
          fmt="pct", q_season=at_least("basketball.fgm", per_game=2.5),
          q_career=at_least("basketball.fgm", total=200),
          detail=lambda t: f"{n(g(t, 'basketball.fgm'))}/{n(g(t, 'basketball.fga'))}"),
        B("tpm", "3-Pointers Made", "Shooting", stat("basketball.tpm"),
          detail=lambda t: f"{n(g(t, 'basketball.tpm'))}/{n(g(t, 'basketball.tpa'))}"),
        B("tp_pct", "3PT %", "Shooting", lambda t: ratio(g(t, "basketball.tpm"), g(t, "basketball.tpa"), 100),
          fmt="pct", q_season=at_least("basketball.tpm", per_game=1),
          q_career=at_least("basketball.tpm", total=75),
          detail=lambda t: f"{n(g(t, 'basketball.tpm'))}/{n(g(t, 'basketball.tpa'))}"),
        B("ft_pct", "FT %", "Shooting", lambda t: ratio(g(t, "basketball.ftm"), g(t, "basketball.fta"), 100),
          fmt="pct", q_season=at_least("basketball.ftm", per_game=1.5),
          q_career=at_least("basketball.ftm", total=100),
          detail=lambda t: f"{n(g(t, 'basketball.ftm'))}/{n(g(t, 'basketball.fta'))}"),
    ],
    "baseball": [
        B("avg", "Batting Average", "Hitting", lambda t: ratio(g(t, "hitting.h"), g(t, "hitting.ab")),
          fmt="avg", hero=True, q_season=HIT_QUAL, best_floor=HIT_FLOOR, q_career=at_least("hitting.ab", total=300),
          detail=lambda t: f"{n(g(t, 'hitting.h'))}-{n(g(t, 'hitting.ab'))}"),
        B("obp", "On-Base %", "Hitting", obp, fmt="avg",
          q_season=HIT_QUAL, best_floor=HIT_FLOOR, q_career=at_least("hitting.ab", total=300)),
        B("ops", "OPS", "Hitting", ops, fmt="avg",
          q_season=HIT_QUAL, best_floor=HIT_FLOOR, q_career=at_least("hitting.ab", total=300)),
        B("h", "Hits", "Hitting", stat("hitting.h")),
        B("r", "Runs", "Hitting", stat("hitting.r")),
        B("rbi", "RBI", "Hitting", stat("hitting.rbi")),
        B("bb", "Walks", "Hitting", stat("hitting.bb")),
        B("hr", "Home Runs", "Power", stat("hitting.hr"), hero=True),
        B("2b", "Doubles", "Power", stat("hitting.2b")),
        B("slg", "Slugging %", "Power", slg, fmt="avg",
          q_season=HIT_QUAL, best_floor=HIT_FLOOR, q_career=at_least("hitting.ab", total=300)),
        B("tb", "Total Bases", "Power", stat("hitting.tb")),
        B("sb", "Stolen Bases", "Speed", stat("hitting.sb"),
          detail=lambda t: f"{n(g(t, 'hitting.sb'))}/{n(g(t, 'hitting.sba'))}"),
        B("era", "ERA", "Pitching", lambda t: ratio(g(t, "pitching.er"), g(t, "pitching.outs"), 27),
          fmt="2", hero=True, asc=True, q_season=PITCH_QUAL, best_floor=PITCH_FLOOR,
          q_career=at_least("pitching.outs", total=300), detail=lambda t: ip_text(g(t, "pitching.outs"))),
        B("whip", "WHIP", "Pitching",
          lambda t: ratio(g(t, "pitching.bb") + g(t, "pitching.h"), g(t, "pitching.outs"), 3),
          fmt="2", asc=True, q_season=PITCH_QUAL, best_floor=PITCH_FLOOR,
          q_career=at_least("pitching.outs", total=300), detail=lambda t: ip_text(g(t, "pitching.outs"))),
        B("w", "Wins", "Pitching", stat("pitching.w"),
          detail=lambda t: f"{n(g(t, 'pitching.w'))}-{n(g(t, 'pitching.l'))}"),
        B("p_so", "Strikeouts", "Pitching", stat("pitching.so")),
        B("sv", "Saves", "Pitching", stat("pitching.sv")),
        B("ip", "Innings", "Pitching", lambda t: g(t, "pitching.outs") / 3 if g(t, "pitching.outs") else None,
          fmt="ip"),
        B("k9", "Strikeouts / 9", "Pitching", lambda t: ratio(g(t, "pitching.so"), g(t, "pitching.outs"), 27),
          fmt="1", q_season=PITCH_QUAL, best_floor=PITCH_FLOOR, q_career=at_least("pitching.outs", total=300),
          detail=lambda t: ip_text(g(t, "pitching.outs"))),
    ],
}


def ip_text(outs: float) -> str:
    return f"{int(outs // 3)}.{int(outs % 3)} IP"


def fmt_value(v: float, fmt: str) -> str:
    if fmt == "int":
        return f"{v:,.0f}"
    if fmt == "1":
        return f"{v:,.1f}"
    if fmt == "2":
        return f"{v:.2f}"
    if fmt == "pct":
        return f"{v:.1f}%"
    if fmt == "avg":
        return f"{v:.3f}".lstrip("0") if v < 1 else f"{v:.3f}"
    if fmt == "ip":
        outs = round(v * 3)
        return f"{outs // 3}.{outs % 3}"
    return str(v)


def span(sport: str, seasons: list[int]) -> str:
    lo, hi = min(seasons), max(seasons)
    if sport == "mbb":
        lo -= 1   # 2015-16 .. 2018-19 reads as 2015-19
    return str(hi) if lo == hi else f"{lo}-{str(hi)[-2:]}"


def rank_board(board, entries):
    """entries: [(value, meta)] -> ranked rows with standard competition ranking (1,2,2,4)."""
    entries.sort(key=lambda e: e[0] if board["asc"] else -e[0])
    out, prev, prev_rank = [], None, 0
    for i, (v, meta) in enumerate(entries[:TOP_N]):
        shown = fmt_value(v, board["fmt"])
        rank = prev_rank if shown == prev else i + 1
        prev, prev_rank = shown, rank
        out.append((rank, v, shown, meta))
    return out


def _same_player_name(a: str, b: str) -> bool:
    """names.same_person, plus the shapes hyphens produce: a hyphenated surname printed
    whole one season and as its last half another ("Dravon Henry" / "D Askew-Henry"), and
    a hyphenated first name ("Al-Rasheed Benton" / "A Benton"). Same final surname and a
    compatible first name; the career guards in reconcile_keys do the rest."""
    if same_person(a, b):
        return True
    ta, tb = norm_name(a).split(), norm_name(b).split()
    if len(ta) < 2 or len(tb) < 2 or ta[-1] != tb[-1]:
        return False
    return ta[0].startswith(tb[0]) or tb[0].startswith(ta[0])


def reconcile_keys(archive: list[dict]) -> dict[str, str]:
    """Map every player_key to one key per real player.

    The stats pages don't always print a name the same way. Early football defensive
    tables use initials ("Benton, A"), and spellings drift between seasons ("Shaq" /
    "Shaquille", a dropped letter). Left alone, each variant is its own career and a
    four-year starter shows up twice on the career board with half his tackles each time.

    Conservative like names.py: two keys merge only when the names plausibly match AND
    the seasons fit one career (within two years of each other, six in all). An initial
    sharing a stat table with a full name in the same season could be two people on one
    roster ("J Robinson" and "Justin Robinson"), so that never merges; two full spellings
    in one table ("Shaq" and "Shaquille") are one player the box scores typed two ways.
    An initial matching several players is settled by jersey number, or left alone."""
    info: dict[str, dict] = {}
    for r in archive:
        p = info.setdefault(r["player_key"], {"name": r["player_name"], "seasons": set(),
                                              "cats": set(), "jerseys": set()})
        p["seasons"].add(r["season"])
        if r["category"] != "general":   # every line has games played; it says nothing
            p["cats"].add((r["season"], r["category"]))
        if r.get("jersey"):
            p["jerseys"].add((r["season"], r["jersey"]))
        if len(r["player_name"]) > len(p["name"]):
            p["name"] = r["player_name"]

    def initial(p) -> bool:
        first = split_name(p["name"])[0]
        return len(first) <= 1

    def compatible(a, b) -> bool:
        if a["cats"] & b["cats"] and (initial(a) or initial(b)):
            return False
        seasons = a["seasons"] | b["seasons"]
        gap = min(abs(x - y) for x in a["seasons"] for y in b["seasons"])
        return gap <= 2 and max(seasons) - min(seasons) <= 6

    def jersey_match(a, b) -> bool:
        jb = {j for _, j in b["jerseys"]}
        return any(j in jb for _, j in a["jerseys"])

    parent = {k: k for k in info}

    def find(k):
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k

    keys = sorted(info)
    by_last: dict[str, list[str]] = defaultdict(list)
    for k in keys:
        by_last[k.split()[-1]].append(k)

    def link(k, pool):
        cands = [c for c in pool
                 if c != k and _same_player_name(info[k]["name"], info[c]["name"])
                 and compatible(info[k], info[c])]
        # Candidates already joined into one player are one candidate, not an ambiguity.
        roots = {find(c) for c in cands}
        if len(roots) > 1:
            roots = {find(c) for c in cands if jersey_match(info[k], info[c])}
        if len(roots) == 1:
            a, b = find(k), roots.pop()
            if a != b:
                parent[a] = b

    # Full spellings first ("Jeff" / "Jeffery"), so by the time an initial is placed the
    # spellings it could mean have already become one player.
    for k in keys:
        if not initial(info[k]):
            link(k, [c for c in by_last[k.split()[-1]] if not initial(info[c])])
    for k in keys:
        if initial(info[k]):
            link(k, by_last[k.split()[-1]])
    return {k: find(k) for k in keys}


def player_lines(archive: list[dict], quiet: bool = False) -> tuple[dict, dict]:
    """The archive as (season, player) lines and per-player careers, name variants joined.

    Shared by the leaderboards and the record book so both rank the same numbers."""
    canon = reconcile_keys(archive)
    merged = sum(1 for k, v in canon.items() if k != v)
    if merged and not quiet:
        print(f"  reconciled {merged} name variant(s) onto the same player")
    variants: dict[tuple[int, str], dict] = {}   # (season, stored key) -> player-season
    for r in archive:
        p = variants.setdefault((r["season"], r["player_key"]), {
            "name": r["player_name"], "jersey": r.get("jersey"), "photo": r.get("photo_url"),
            "position": r.get("position"), "stats": {}})
        p["stats"][f"{r['category']}.{r['stat']}"] = float(r["value"])

    lines: dict[tuple[int, str], dict] = {}      # (season, player) -> player-season
    for (season, key), v in sorted(variants.items()):
        k = (season, canon[key])
        if k not in lines:
            lines[k] = {**v, "stats": dict(v["stats"])}
            continue
        p = lines[k]
        # A merged variant can be the fuller spelling or the one with a headshot.
        if len(v["name"]) > len(p["name"]):
            p["name"] = v["name"]
        for f in ("photo", "jersey", "position"):
            p[f] = p[f] or v[f]
        merge_stats(p["stats"], v["stats"])

    careers: dict[str, dict] = {}
    for (season, key), p in sorted(lines.items()):
        c = careers.setdefault(key, {"seasons": [], "stats": defaultdict(float)})
        c["seasons"].append(season)
        # Later seasons win for photo/jersey/position: that's how fans last saw him. The
        # name is the fullest spelling any season printed, since some print an initial.
        if len(p["name"]) > len(c.get("name", "")):
            c["name"] = p["name"]
        c["jersey"] = p["jersey"] or c.get("jersey")
        c["photo"] = p["photo"] or c.get("photo")
        c["position"] = p["position"] or c.get("position")
        for sk, v in p["stats"].items():
            if sk.endswith(".qual"):
                continue
            if sk.split(".")[1] in MAX_STATS:
                c["stats"][sk] = max(c["stats"][sk], v)
            else:
                c["stats"][sk] += v
    return lines, careers


def build_leaders(sport: str, archive: list[dict], games_by_season: dict[int, int]) -> list[dict]:
    """Every leaderboard for one sport: per season, career and best single season."""
    lines, careers = player_lines(archive)
    rows: list[dict] = []

    def emit(scope, season, board, order, ranked, detail_of):
        for slot, (rank, v, shown, meta) in enumerate(ranked):
            rows.append({
                "id": f"{sport}|{scope}|{season}|{board['key']}|{slot}",
                "sport_id": sport, "scope": scope, "season": season,
                "board": board["key"], "board_title": board["title"], "board_group": board["group"],
                "board_order": order, "hero": board["hero"], "rank": rank,
                "player_key": meta["key"], "player_name": meta["name"], "jersey": meta.get("jersey"),
                "photo_url": meta.get("photo"), "position": meta.get("position"),
                "value": round(v, 4), "display": shown,
                "detail": detail_of(meta),
            })

    def value_of(board, stats, qual, games):
        v = board["val"](stats)
        if v is None:
            return None
        if qual and not qual(stats, games):
            return None
        if not qual and not board["asc"] and v <= 0:
            return None   # counting boards skip zeros
        return v

    seasons = sorted({s for s, _ in lines})
    for order, board in enumerate(BOARDS[sport]):
        best = []
        for season in seasons:
            games = games_by_season.get(season, 0)
            entries = []
            for (s, key), p in lines.items():
                if s != season:
                    continue
                v = value_of(board, p["stats"], board["q_season"], games)
                if v is not None:
                    meta = {"key": key, "name": p["name"], "jersey": p["jersey"], "photo": p["photo"],
                            "position": p["position"], "stats": p["stats"], "season": season}
                    entries.append((v, meta))
                    floor = board["best_floor"]
                    if not floor or p["stats"].get(floor[0], 0) >= floor[1]:
                        best.append((v, meta))
            ranked = rank_board(board, entries)
            emit("season", season, board, order, ranked,
                 lambda m: board["detail"](m["stats"]) if board["detail"] else None)

        emit("best", 0, board, order, rank_board(board, best),
             lambda m: " · ".join(x for x in [season_label(sport, m["season"]),
                                               board["detail"](m["stats"]) if board["detail"] else None] if x))

        if board["career"]:
            entries = []
            for key, c in careers.items():
                v = value_of(board, c["stats"], board["q_career"], 0)
                if v is not None:
                    entries.append((v, {"key": key, "name": c["name"], "jersey": c["jersey"],
                                        "photo": c["photo"], "position": c["position"],
                                        "stats": c["stats"], "seasons": c["seasons"]}))
            emit("career", 0, board, order, rank_board(board, entries),
                 lambda m: span(sport, m["seasons"]))
    return rows


# ---------------------------------------------------------------------------
# Record Book
#
# record_book.json (build_record_book.py) holds WVU's all-time top-10 lists as of each
# source's last counted season (`through`). Every night the archive brings them current:
#
#   career   a listed player's total becomes the largest of the book's number, the
#            archive's whole-career total (complete for anyone who started in 2014 or
#            later, and right even if the source missed a season), and the book's number
#            plus the archive's seasons after `through` (for careers that straddle it --
#            the baseball book stops in 2014 and the archive starts in 2015). A player the
#            book doesn't list joins on his archive total.
#   season   every archived season is a candidate; one already listed keeps the book's
#            (official) number for seasons the book has counted.
#   rates    FG%, batting average and ERA can't be recombined without their totals, so a
#            listed entry is never changed; only careers and seasons wholly after `through`
#            can join, on the book's own minimums.
#
# A list never grows past its source's length: Wikipedia's football tackles list is five
# deep, and padding it to ten from the archive would rank 2019 linebackers above 1990s
# ones the source never listed.
# ---------------------------------------------------------------------------

RECORD_BOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "record_book.json")


def total_of(*keys):
    return lambda t: sum(g(t, k) for k in keys) if any(k in t for k in keys) else None


RB_STATS = {
    "football": {
        "pass_yds": stat("passing.yds"), "pass_td": stat("passing.td"),
        "rush_yds": stat("rushing.yds"), "rush_td": stat("rushing.td"),
        "rec": stat("receiving.rec"), "rec_yds": stat("receiving.yds"), "rec_td": stat("receiving.td"),
        "total_off": total_of("passing.yds", "rushing.yds"),
        "td_resp": total_of("passing.td", "rushing.td"),
        "apy": total_of("rushing.yds", "receiving.yds", "kick_ret.yds", "punt_ret.yds"),
        "tkl": stat("defense.tkl"), "sacks": stat("defense.sacks"), "def_int": stat("defense.int"),
        "fgm": stat("kicking.fgm"),
        "fg_pct": lambda t: ratio(g(t, "kicking.fgm"), g(t, "kicking.fga"), 100),
    },
    "mbb": {
        "pts": stat("basketball.pts"), "reb": stat("basketball.reb"), "ast": stat("basketball.ast"),
        "stl": stat("basketball.stl"), "blk": stat("basketball.blk"),
    },
    "baseball": {
        "avg": lambda t: ratio(g(t, "hitting.h"), g(t, "hitting.ab")),
        "h": stat("hitting.h"), "r": stat("hitting.r"), "rbi": stat("hitting.rbi"),
        "2b": stat("hitting.2b"), "hr": stat("hitting.hr"), "tb": stat("hitting.tb"),
        "sb": stat("hitting.sb"), "bb": stat("hitting.bb"),
        "era": lambda t: ratio(g(t, "pitching.er"), g(t, "pitching.outs"), 27),
        "w": stat("pitching.w"), "sv": stat("pitching.sv"), "p_so": stat("pitching.so"),
        "ip": stat("pitching.outs"),   # innings are kept as outs until display
    },
}
RB_RATES = {"fg_pct", "avg", "era"}
# The record books' own minimums for rate lists (baseball's are printed beside each list).
RB_QUAL = {
    ("fg_pct", "season"): lambda t, n: g(t, "kicking.fga") >= 15,
    ("fg_pct", "career"): lambda t, n: g(t, "kicking.fga") >= 40,
    ("avg", "season"): lambda t, n: g(t, "hitting.ab") >= 75,
    ("avg", "career"): lambda t, n: g(t, "hitting.ab") >= 150 and n >= 2,
    ("era", "season"): lambda t, n: g(t, "pitching.outs") >= 150,
    ("era", "career"): lambda t, n: g(t, "pitching.outs") >= 300 and n >= 2,
}


def _book_value(v: float, fmt: str) -> float:
    return innings_to_outs(v) if fmt == "ip" else v


def _show(v: float, fmt: str) -> str:
    if fmt == "ip":
        o = int(round(v))
        return f"{o // 3:,}.{o % 3}"
    return fmt_value(v, fmt)


def merge_record_book(sport: str, book: dict, archive: list[dict]) -> list[dict]:
    lines, careers = player_lines(archive, quiet=True)
    through = book["through"]
    stats = RB_STATS.get(sport, {})
    rows: list[dict] = []

    # Keep each group's lists together. The baseball book runs Hits, Doubles, Home Runs,
    # then RBI, so in the book's own order "Hitting" would appear on screen twice.
    group_at: dict[str, int] = {}
    for lst in book["lists"]:
        group_at.setdefault(lst["group"], len(group_at))
    ordered = sorted(enumerate(book["lists"]), key=lambda x: (group_at[x[1]["group"]], x[0]))

    for order, (_, lst) in enumerate(ordered):
        key, scope, fmt = lst["key"], lst["scope"], lst["fmt"]
        fn, rate, asc = stats.get(key), key in RB_RATES, key == "era"
        qual = RB_QUAL.get((key, scope))
        entries = [{**e, "value": _book_value(e["value"], fmt), "photo": None} for e in lst["entries"]]
        size = len(entries)

        def overlaps(e, first, last):
            a, b = e["seasons"]
            return a - 1 <= last and first <= b + 1

        if fn and scope == "career":
            for pkey, c in careers.items():
                v = fn(c["stats"])
                if v is None or (not rate and v <= 0):
                    continue
                if qual and not qual(c["stats"], len(c["seasons"])):
                    continue
                first, last = min(c["seasons"]), max(c["seasons"])
                match = next((e for e in entries if "seasons" in e and _same_player_name(e["name"], c["name"])
                              and overlaps(e, first, last)), None)
                if match:
                    match["photo"] = match["photo"] or c.get("photo")
                    if rate:
                        continue
                    after = sum(fn(lines[(s, pkey)]["stats"]) or 0 for s in c["seasons"] if s > through)
                    best = max(match["value"], v, match["value"] + after)
                    if best > match["value"]:
                        match["value"] = best
                        match["seasons"] = [min(match["seasons"][0], first), max(match["seasons"][1], last)]
                elif not rate or first > through:
                    entries.append({"name": c["name"], "value": v, "seasons": [first, last],
                                    "photo": c.get("photo")})

        elif fn and scope == "season":
            for (season, pkey), p in lines.items():
                v = fn(p["stats"])
                if v is None or (not rate and v <= 0):
                    continue
                if qual and not qual(p["stats"], 1):
                    continue
                dup = next((e for e in entries if e.get("season") == season
                            and _same_player_name(e["name"], p["name"])), None)
                if dup:
                    dup["photo"] = dup["photo"] or p.get("photo")
                    if season > through and not rate:
                        dup["value"] = max(dup["value"], v)
                    continue
                if rate and season <= through:
                    continue
                entries.append({"name": p["name"], "value": v, "season": season, "photo": p.get("photo")})

        elif scope == "game" and sport == "mbb" and key == "pts":
            # The archive knows each player's best game of a season, which is enough to
            # put a new 40-point night on the list. Seasons the source counted are its own.
            for (season, pkey), p in lines.items():
                v = p["stats"].get("basketball.high")
                if not v or season <= through:
                    continue
                if any(e.get("season") == season and _same_player_name(e["name"], p["name"])
                       and e["value"] == v for e in entries):
                    continue
                entries.append({"name": p["name"], "value": v, "season": season, "photo": p.get("photo")})

        entries.sort(key=lambda e: e["value"] if asc else -e["value"])
        prev, prev_rank = None, 0
        for slot, e in enumerate(entries):
            shown = _show(e["value"], fmt)
            rank = prev_rank if shown == prev else slot + 1
            if rank > size:
                break
            prev, prev_rank = shown, rank
            if scope == "career":
                detail = span(sport, e["seasons"])
            else:
                detail = season_label(sport, e["season"])
                if e.get("opponent"):
                    detail += f" · vs. {e['opponent']}"
            rows.append({
                "id": f"{sport}|{scope}|{key}|{slot}", "sport_id": sport, "scope": scope,
                "list_key": key, "title": lst["title"], "grp": lst["group"], "ord": order,
                "rank": rank, "player_name": e["name"], "value": round(e["value"], 4),
                "display": shown, "detail": detail, "photo_url": e.get("photo"),
                "source": book["source"], "through": through,
            })
    return rows


# ---------------------------------------------------------------------------
# Supabase I/O
# ---------------------------------------------------------------------------

def read_all(sb, table: str, cols: str, **eq) -> list[dict]:
    out, start = [], 0
    while True:
        q = sb.table(table).select(cols)
        for k, v in eq.items():
            q = q.eq(k, v)
        page = q.order("id").range(start, start + 999).execute().data or []
        out += page
        if len(page) < 1000:
            return out
        start += 1000


def replace(sb, table: str, rows: list[dict], scope: dict) -> None:
    """Upsert `rows`, then delete whatever else is stored under `scope`.

    Upsert first, so readers never see the season empty mid-run; then drop rows that no
    longer exist (a player whose line was corrected away, a board that lost a slot)."""
    for i in range(0, len(rows), 500):
        sb.table(table).upsert(rows[i:i + 500]).execute()
    keep = {r["id"] for r in rows}
    stale = [r["id"] for r in read_all(sb, table, "id", **scope) if r["id"] not in keep]
    for i in range(0, len(stale), 200):
        sb.table(table).delete().in_("id", stale[i:i + 200]).execute()


def archive_rows(sport: str, season: int, parsed: Season) -> list[dict]:
    rows = []
    for key, p in parsed.players.items():
        for sk, v in p["stats"].items():
            cat, st = sk.split(".", 1)
            rows.append({
                "id": f"{sport}|{season}|{key}|{cat}|{st}", "sport_id": sport, "season": season,
                "player_key": key, "player_name": p["name"], "jersey": p["jersey"],
                "photo_url": p["photo"], "position": p.get("position"),
                "category": cat, "stat": st, "value": v,
            })
    return rows


def backfill_football_records(sb) -> None:
    """Football's season-by-season record since 1891, from CFBD. One call, and only while
    those seasons are missing: once stored, a finished season's record never changes."""
    have = {r["season"] for r in sb.table("team_records").select("season")
            .eq("sport_id", "football").eq("team", "West Virginia").execute().data or []}
    if len(have) >= 100:
        return
    if not CFBD_KEY:
        print("  [!] CFBD_API_KEY missing - football records before 2014 not backfilled")
        return
    r = requests.get("https://api.collegefootballdata.com/records",
                     headers={"Authorization": f"Bearer {CFBD_KEY}"},
                     params={"team": "West Virginia"}, timeout=60)
    if r.status_code != 200:
        print(f"  [!] CFBD /records HTTP {r.status_code} - football history not backfilled")
        return
    rows = []
    for rec in r.json():
        yr = rec.get("year")
        if not yr or yr in have:
            continue
        tot, conf = rec.get("total") or {}, rec.get("conferenceGames") or {}
        independent = "independent" in (rec.get("conference") or "").lower()
        rows.append({"sport_id": "football", "season": yr, "team": "West Virginia",
                     "total_wins": tot.get("wins"), "total_losses": tot.get("losses"),
                     "ties": tot.get("ties") or 0, "conference": rec.get("conference"),
                     "conf_wins": None if independent else conf.get("wins"),
                     "conf_losses": None if independent else conf.get("losses")})
    if rows:
        sb.table("team_records").upsert(rows, on_conflict="sport_id,season,team").execute()
    print(f"  team_records <- {len(rows)} football seasons from CFBD (back to {min((x['season'] for x in rows), default='-')})")


def record_from_page(sb, sport: str, season: int, block: dict, have: set[int]) -> None:
    """Past seasons' W-L from the stats page, for seasons nothing else has written."""
    if season in have:
        return
    parts = [p.strip() for p in (block.get("record") or "").split(",")]
    w, l = pair(parts[0]) if parts and parts[0] else (None, None)
    if w is None:
        return
    cw, cl = pair(parts[1]) if len(parts) > 1 else (None, None)
    sb.table("team_records").upsert({
        "sport_id": sport, "season": season, "team": "West Virginia",
        "total_wins": int(w), "total_losses": int(l),
        "conf_wins": int(cw) if cw is not None else None,
        "conf_losses": int(cl) if cl is not None else None,
    }, on_conflict="sport_id,season,team").execute()
    have.add(season)


# ---------------------------------------------------------------------------

def main() -> None:
    for name, val in [("SUPABASE_URL", SB_URL), ("SUPABASE_SECRET_KEY", SB_KEY)]:
        if not val:
            die(f"Missing {name} in .env")
    full = "--full" in sys.argv
    sb = create_client(SB_URL, SB_KEY)
    this_year = date.today().year
    failures = []

    try:
        with open(RECORD_BOOK, encoding="utf-8") as f:
            record_book = json.load(f)
    except (OSError, ValueError) as e:   # the leaderboards don't need it
        record_book = {}
        print(f"  [!] record_book.json unreadable ({e}) - Record Book not refreshed")

    try:
        backfill_football_records(sb)
    except Exception as e:   # history is a nice-to-have; never block the stats on it
        print(f"  [!] football records backfill failed: {e}")

    for sport, cfg in SPORTS.items():
        stored = sorted({r["season"] for r in read_all(sb, "team_season_stats", "id,season",
                                                        sport_id=sport)})
        newest = max(stored) if stored else None
        page_records: dict[int, dict] = {}
        # Basketball's season is named for the year it ends, so next spring's is this_year + 1.
        last_possible = this_year + 1
        todo = [s for s in range(cfg["first"], last_possible + 1)
                if full or s not in stored or (newest is not None and s >= newest)]
        rec_have = {r["season"] for r in sb.table("team_records").select("season")
                    .eq("sport_id", sport).eq("team", "West Virginia").execute().data or []}

        print(f"\n{sport}: {len(stored)} seasons stored; fetching {', '.join(map(str, todo)) or 'none'}")
        # Fetch and parse everything first: telling a visiting player from a Mountaineer
        # needs every season in view (see drop_visitors).
        fetched: dict[int, tuple[dict, Season, list, int]] = {}
        for season in todo:
            url = season_url(sport, season)
            try:
                block = cumulative(nuxt_state(fetch(url)))
            except Exception as e:
                failures.append(f"{sport} {season}: {type(e).__name__}: {e}")
                print(f"  [!] {season}: {e}")
                continue
            finally:
                time.sleep(REQUEST_PAUSE)
            if not block:
                print(f"  {season_label(sport, season)}: no stats published (yet)")
                continue
            parsed = parse_season(sport, block)
            try:
                roster = roster_players(nuxt_state(fetch(roster_url(sport, season))))
            except Exception as e:   # names stay as the stat file prints them
                roster = []
                print(f"      (roster page unavailable: {type(e).__name__}) - names left as filed")
            finally:
                time.sleep(REQUEST_PAUSE)
            completed = apply_roster(parsed, roster)
            if not parsed.players:
                failures.append(f"{sport} {season}: page parsed to zero players")
                print(f"  [!] {season}: page parsed to zero players - leaving stored rows alone")
                continue
            fetched[season] = (block, parsed, roster, completed)

        known: dict[str, set[int]] = defaultdict(set)
        for r in read_all(sb, "stat_archive", "id,season,player_key,player_name",
                          sport_id=sport, category="general", stat="gp"):
            if r["season"] not in fetched:
                known[r["player_name"]].add(r["season"])
        for season, (_, parsed, _, _) in fetched.items():
            for p in parsed.players.values():
                known[p["name"]].add(season)

        for season, (block, parsed, roster, completed) in sorted(fetched.items()):
            visitors = drop_visitors(parsed, season, roster, known)
            arch = archive_rows(sport, season, parsed)
            team = team_rows(sport, season, block, parsed.team_games)
            replace(sb, "stat_archive", arch, {"sport_id": sport, "season": season})
            replace(sb, "team_season_stats", team, {"sport_id": sport, "season": season})
            page_records[season] = block
            print(f"  {season_label(sport, season)}: {len(parsed.players)} players, "
                  f"{len(arch)} stat lines, {len(team)} team stats, {parsed.team_games} games; "
                  f"roster {len(roster)} ({completed} names completed)")
            for x in sorted(parsed.relinked):
                print(f"      relinked {x}")
            if parsed.dropped:
                print(f"      dropped {len(parsed.dropped)} line(s) filed under WVU from an opponent's "
                      f"box score: {', '.join(sorted(parsed.dropped))}")
            if visitors:
                print(f"      dropped {len(visitors)} visiting player(s) (one game, not on the "
                      f"roster, no other WVU season): {', '.join(visitors)}")

        # Past seasons' W-L for the year-by-year list. The newest season is left to
        # sync_football / sync_espn, which update it after every game.
        newest = max([*stored, *page_records], default=None)
        for season, block in page_records.items():
            if newest is not None and season < newest:
                record_from_page(sb, sport, season, block, rec_have)

        # Re-rank from the whole archive: a new season can change the career boards.
        archive = read_all(sb, "stat_archive",
                           "id,season,player_key,player_name,jersey,photo_url,position,category,stat,value",
                           sport_id=sport)
        games = {r["season"]: int(num(r["wvu"]) or 0)
                 for r in read_all(sb, "team_season_stats", "id,season,wvu", sport_id=sport, stat="games")}
        leaders = build_leaders(sport, archive, games)
        replace(sb, "stat_leaders", leaders, {"sport_id": sport})
        if sport in record_book:
            book_rows = merge_record_book(sport, record_book[sport], archive)
            replace(sb, "record_book", book_rows, {"sport_id": sport})
            print(f"  record_book -> {len(book_rows)} rows in {len(record_book[sport]['lists'])} lists "
                  f"(book through {season_label(sport, record_book[sport]['through'])})")
        seasons = sorted({r["season"] for r in archive})
        print(f"  stat_leaders -> {len(leaders)} rows across {len(seasons)} seasons "
              f"({season_label(sport, seasons[0]) if seasons else '-'} to "
              f"{season_label(sport, seasons[-1]) if seasons else '-'})")

    if failures:
        print("\n[!] Some seasons could not be refreshed (stored rows kept):")
        for f in failures:
            print(f"    {f}")
        sys.exit(1)
    print("\n[OK] Stat archive and leaderboards synced.")


if __name__ == "__main__":
    main()
