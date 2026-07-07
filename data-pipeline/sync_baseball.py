"""
Mountaineer Pulse - Baseball Player Season Stats (NCAA API)
==========================================================
There is no CFBD-style API for college baseball, so we use the NCAA API
(henrygd/ncaa-api, which wraps NCAA.com) and aggregate WVU's per-game box scores
into season totals -- the same player_stats shape football uses via CFBD.

Flow: scan the season's daily scoreboards for WVU games, pull each game's box
score, sum every Mountaineer's batting/pitching line, recompute AVG/ERA, name-
match to the wvusports roster, and upsert into player_stats (sport_id=baseball).

Note: NCAA box-score batting lines are basic (AB/R/H/RBI/BB/K/AVG) -- no HR/SB.
Pitching is complete (ERA/IP/K/W/L/SV/H/BB). Free, no API key, ~5 req/sec/IP.

Run:  python sync_baseball.py
"""

import os
import sys
import time
import unicodedata
from collections import defaultdict
from datetime import date, timedelta

import requests
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

SB_URL = os.getenv("SUPABASE_URL")
SB_KEY = os.getenv("SUPABASE_SECRET_KEY")

NCAA = "https://ncaa-api.henrygd.me"
HEADERS = {"User-Agent": "Mozilla/5.0"}
TEAM = "West Virginia"
SPORT = "baseball"
SEASON = 2026
# WVU 2026 season window (open week of Feb 14 → CWS late June). Scan inclusive.
START = date(2026, 2, 13)
END = date(2026, 6, 25)
PACE = 0.22  # seconds between calls (~4.5/sec, under the 5/sec/IP limit)
SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}


def die(msg: str) -> None:
    print(f"\n[X] {msg}")
    sys.exit(1)


def norm_name(name: str) -> str:
    s = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode()
    s = s.lower().replace(".", " ").replace("'", "").replace("-", " ")
    return " ".join(t for t in s.split() if t and t not in SUFFIXES)


def agg_key(first: str, last: str) -> str:
    """Key by first-initial + last name so 'Gavin Kelly' and 'G. Kelly' merge
    (NCAA box scores abbreviate first names inconsistently)."""
    f = norm_name(first)
    ln = norm_name(last)
    return f"{f[:1]} {ln}".strip()


def get(path: str):
    r = requests.get(f"{NCAA}{path}", headers=HEADERS, timeout=25)
    if r.status_code != 200:
        return None
    try:
        return r.json()
    except ValueError:
        return None


def num(x) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def ip_to_outs(ip) -> int:
    """'5.2' innings = 5 innings + 2 outs = 17 outs."""
    try:
        whole, _, frac = str(ip).partition(".")
        return int(whole or 0) * 3 + int(frac or 0)
    except ValueError:
        return 0


def main() -> None:
    if not SB_URL or not SB_KEY:
        die("Missing SUPABASE_URL or SUPABASE_SECRET_KEY in .env")
    sb = create_client(SB_URL, SB_KEY)

    # ---- Phase 1: find WVU game ids across the season -----------------------
    game_ids = []
    d = START
    scanned = 0
    while d <= END:
        data = get(f"/scoreboard/{SPORT}/d1/{d.year}/{d.month:02d}/{d.day:02d}/all-conf")
        scanned += 1
        if data:
            for g in data.get("games", []):
                gm = g.get("game") or g
                blob = f"{gm.get('home', {})}{gm.get('away', {})}"
                if TEAM in blob and (gm.get("gameState") == "final" or gm.get("finalMessage")):
                    if gm.get("gameID"):
                        game_ids.append(gm["gameID"])
        d += timedelta(days=1)
        time.sleep(PACE)
    print(f"scanned {scanned} dates -> {len(game_ids)} WVU final games")

    # ---- Phase 2: aggregate box scores --------------------------------------
    bat = defaultdict(lambda: defaultdict(float))   # name -> stat -> total
    pit = defaultdict(lambda: defaultdict(float))
    pit_outs = defaultdict(int)
    display = {}                                    # norm name -> display name
    used = 0
    for gid in game_ids:
        bx = get(f"/game/{gid}/boxscore")
        time.sleep(PACE)
        if not bx:
            continue
        wvu_tid = None
        for t in bx.get("teams", []):
            if TEAM in (t.get("nameFull") or t.get("nameShort") or ""):
                wvu_tid = str(t.get("teamId"))
        if wvu_tid is None:
            continue
        for tb in bx.get("teamBoxscore", []):
            if str(tb.get("teamId")) != wvu_tid:
                continue
            used += 1
            for p in tb.get("playerStats", []):
                full = f"{p.get('firstName', '')} {p.get('lastName', '')}".strip()
                key = agg_key(p.get("firstName", ""), p.get("lastName", ""))
                if not key:
                    continue
                # keep the fullest name variant for display (prefer "Gavin" over "G.")
                if len(full) > len(display.get(key, "")):
                    display[key] = full
                bs = p.get("batterStats")
                if bs:
                    bat[key]["AB"] += num(bs.get("atBats"))
                    bat[key]["R"] += num(bs.get("runsScored"))
                    bat[key]["H"] += num(bs.get("hits"))
                    bat[key]["RBI"] += num(bs.get("runsBattedIn"))
                    bat[key]["BB"] += num(bs.get("walks"))
                    bat[key]["SO"] += num(bs.get("strikeouts"))
                ps = p.get("pitcherStats")
                if ps:
                    pit_outs[key] += ip_to_outs(ps.get("inningsPitched"))
                    pit[key]["H"] += num(ps.get("hitsAllowed"))
                    pit[key]["R"] += num(ps.get("runsAllowed"))
                    pit[key]["ER"] += num(ps.get("earnedRunsAllowed"))
                    pit[key]["BB"] += num(ps.get("walksAllowed"))
                    pit[key]["SO"] += num(ps.get("strikeouts"))
                    pit[key]["W"] += num(ps.get("win"))
                    pit[key]["L"] += num(ps.get("loss"))
                    pit[key]["SV"] += num(ps.get("save"))
    print(f"aggregated {used} WVU box-score sides")

    # ---- Phase 3: roster match + build player_stats rows --------------------
    roster = sb.table("players").select("id,first_name,last_name").eq(
        "sport_id", SPORT).execute().data or []
    name_to_id = {}
    for pl in roster:
        k = agg_key(pl.get("first_name") or "", pl.get("last_name") or "")
        if k:
            name_to_id[k] = pl["id"]

    rows = []
    linked = set()

    def add(pid, category, stat_type, value):
        rows.append({
            "id": f"{pid}|{SEASON}|{TEAM}|{category}|{stat_type}",
            "player_id": pid, "season": SEASON, "sport_id": SPORT,
            "player_name": display.get(k, k), "position": None,
            "category": category, "stat_type": stat_type, "stat": str(value),
            "team": TEAM,
        })

    for k, b in bat.items():
        if b["AB"] <= 0:
            continue
        pid = name_to_id.get(k) or f"ncaa_{k.replace(' ', '_')}"
        if not pid.startswith("ncaa_"):
            linked.add(pid)
        avg = b["H"] / b["AB"] if b["AB"] else 0
        add(pid, "hitting", "AVG", f"{avg:.3f}")
        for st in ("AB", "R", "H", "RBI", "BB", "SO"):
            add(pid, "hitting", st, int(b[st]))

    for k, p in pit.items():
        outs = pit_outs[k]
        if outs <= 0:
            continue
        pid = name_to_id.get(k) or f"ncaa_{k.replace(' ', '_')}"
        if not pid.startswith("ncaa_"):
            linked.add(pid)
        ip_disp = f"{outs // 3}.{outs % 3}"
        era = (9 * p["ER"]) / (outs / 3) if outs else 0
        add(pid, "pitching", "ERA", f"{era:.2f}")
        add(pid, "pitching", "IP", ip_disp)
        for st in ("H", "R", "ER", "BB", "SO", "W", "L", "SV"):
            add(pid, "pitching", st, int(p[st]))

    # Clean slate for baseball, then insert.
    sb.table("player_stats").delete().eq("sport_id", SPORT).execute()
    for i in range(0, len(rows), 500):
        sb.table("player_stats").upsert(rows[i:i + 500]).execute()

    print(f"player_stats -> {len(rows)} baseball stat lines "
          f"({len(bat)} batters, {len(pit)} pitchers; {len(linked)} linked to roster)")
    print("\n[OK] Baseball player stats synced to Supabase.")


if __name__ == "__main__":
    main()
