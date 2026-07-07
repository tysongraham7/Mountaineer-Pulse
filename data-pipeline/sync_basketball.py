"""
Mountaineer Pulse - Basketball Player Season Stats (CollegeBasketballData)
=========================================================================
Pulls WVU men's basketball per-player season stats from CollegeBasketballData
(the CFBD-family API, its own key) and writes them into player_stats -- the same
shape football/baseball use, so Leaders and player profiles light up for hoops.

CBD returns season TOTALS + rates; we derive per-game (PPG/RPG/APG/...) and keep
the shooting splits. Name-matched to the wvusports roster so returners' profiles
join straight to their line.

Season note: CBD labels a season by the year it ends (2025-26 = 2026).

Prereqs: .env has CBD_API_KEY, SUPABASE_URL, SUPABASE_SECRET_KEY.
Run:  python sync_basketball.py
"""

import os
import sys
import unicodedata

import requests
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

CBD_KEY = os.getenv("CBD_API_KEY")
SB_URL = os.getenv("SUPABASE_URL")
SB_KEY = os.getenv("SUPABASE_SECRET_KEY")

BASE = "https://api.collegebasketballdata.com"
TEAM = "West Virginia"
SPORT = "mbb"
SEASONS = [2025, 2026]     # 2024-25 and 2025-26
SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}


def die(msg: str) -> None:
    print(f"\n[X] {msg}")
    sys.exit(1)


def norm_name(name: str) -> str:
    s = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode()
    s = s.lower().replace(".", " ").replace("'", "").replace("-", " ")
    return " ".join(t for t in s.split() if t and t not in SUFFIXES)


def cbd(path: str):
    r = requests.get(f"{BASE}{path}", headers={"Authorization": f"Bearer {CBD_KEY}",
                                               "Accept": "application/json"}, timeout=30)
    if r.status_code != 200:
        die(f"CBD {path} failed: HTTP {r.status_code} - {r.text[:160]}")
    return r.json()


def pg(total, games: int) -> float:
    return round((total or 0) / games, 1) if games else 0.0


def num(x) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def stat_rows(pid, season, team, p) -> list:
    """Build the long-format per-game/shooting rows for one player-season."""
    games = int(p.get("games") or 0)
    if games <= 0:
        return []
    reb = p.get("rebounds") or {}
    reb_total = reb.get("total") if isinstance(reb, dict) else reb
    fg = p.get("fieldGoals") or {}
    tp = p.get("threePointFieldGoals") or {}
    ft = p.get("freeThrows") or {}
    stat_map = {
        "GP": games, "GS": int(p.get("starts") or 0),
        "MPG": pg(p.get("minutes"), games), "PPG": pg(p.get("points"), games),
        "RPG": pg(reb_total, games), "APG": pg(p.get("assists"), games),
        "SPG": pg(p.get("steals"), games), "BPG": pg(p.get("blocks"), games),
        "FG%": round(num(fg.get("pct")), 1), "FGA": int(num(fg.get("attempted"))),
        "3P%": round(num(tp.get("pct")), 1), "3PA": int(num(tp.get("attempted"))),
        "3PM": int(num(tp.get("made"))), "FT%": round(num(ft.get("pct")), 1),
        "PTS": int(num(p.get("points"))), "REB": int(num(reb_total)),
        "AST": int(num(p.get("assists"))),
    }
    return [{
        "id": f"{pid}|{season}|{team}|basketball|{stype}",
        "player_id": pid, "season": season, "sport_id": SPORT,
        "player_name": p.get("name"), "position": p.get("position"),
        "category": "basketball", "stat_type": stype, "stat": str(val), "team": team,
    } for stype, val in stat_map.items()]


def main() -> None:
    for name, val in [("CBD_API_KEY", CBD_KEY), ("SUPABASE_URL", SB_URL),
                      ("SUPABASE_SECRET_KEY", SB_KEY)]:
        if not val:
            die(f"Missing {name} in .env")
    sb = create_client(SB_URL, SB_KEY)

    roster = sb.table("players").select("id,first_name,last_name").eq(
        "sport_id", SPORT).execute().data or []
    name_to_id = {}
    for p in roster:
        k = norm_name(f"{p.get('first_name') or ''} {p.get('last_name') or ''}")
        if k:
            name_to_id[k] = p["id"]

    # --- Phase 1: WVU stats -------------------------------------------------
    rows = []
    linked = set()
    by_season = {}
    for season in SEASONS:
        data = cbd(f"/stats/player/season?season={season}&team={TEAM}")
        by_season[season] = len(data)
        for p in data:
            key = norm_name(p.get("name") or "")
            pid = name_to_id.get(key) or f"cbd_{key.replace(' ', '_')}"
            r = stat_rows(pid, season, TEAM, p)
            if r and not pid.startswith("cbd_"):
                linked.add(pid)
            rows += r

    # --- Phase 2: incoming transfers' previous-school stats -----------------
    # Basketball transfers come from D1 schools CBD covers, so we can attach their
    # old-school line to their WVU profile (tagged with the previous school).
    incoming = sb.table("roster_moves").select("player_name,other_school").eq(
        "sport_id", SPORT).eq("direction", "in").eq("category", "transfer").execute().data or []
    school_cache = {}
    prev_linked = 0
    for mv in incoming:
        school = (mv.get("other_school") or "").strip()
        pid = name_to_id.get(norm_name(mv.get("player_name") or ""))
        if not school or not pid:
            continue  # need both a school and a roster profile to attach to
        want = norm_name(mv["player_name"])
        for season in SEASONS:
            ck = (school, season)
            if ck not in school_cache:
                school_cache[ck] = cbd(
                    f"/stats/player/season?season={season}&team={requests.utils.quote(school)}")
            match = next((p for p in school_cache[ck] if norm_name(p.get("name", "")) == want), None)
            if match:
                r = stat_rows(pid, season, school, match)
                if r:
                    rows += r
                    prev_linked += 1

    sb.table("player_stats").delete().eq("sport_id", SPORT).execute()
    for i in range(0, len(rows), 500):
        sb.table("player_stats").upsert(rows[i:i + 500]).execute()

    summary = "  ".join(f"{yr}:{n}" for yr, n in by_season.items())
    print(f"player_stats -> {len(rows)} basketball stat lines  (WVU players/season  {summary})")
    print(f"              {len(linked)} returners linked; "
          f"{prev_linked} incoming-transfer prev-school seasons")
    print("\n[OK] Basketball player stats synced to Supabase.")


if __name__ == "__main__":
    main()
