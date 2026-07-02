"""
Mountaineer Pulse - Historical Backfill (the stock chart's data)
================================================================
Recomputes each program's Pulse at every past game date and roster-move date,
so the app can plot a score-over-time curve. Uses a self-consistent model
(win% + form + postseason surge + roster) that converges to today's authoritative
score. compute_pulse.py still owns TODAY's snapshot (ranking-based).

Run:  python backfill_pulse.py
"""

import os
import sys
from datetime import date, datetime

from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

SB_URL = os.getenv("SUPABASE_URL")
SB_KEY = os.getenv("SUPABASE_SECRET_KEY")
POSTSEASON_CUTOFF = {"football": (12, 1), "mbb": (3, 12), "baseball": (5, 20)}
CAT_WEIGHT = {("transfer", "in"): 1.5, ("transfer", "out"): -1.5, ("recruit", "in"): 1.0,
              ("graduation", "out"): -0.4, ("draft", "out"): -0.4}


def die(msg: str) -> None:
    print(f"\n[X] {msg}")
    sys.exit(1)


def to_date(s: str | None):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return date.fromisoformat(s[:10])
        except ValueError:
            return None


def wvu_won(g: dict) -> bool:
    wvu = g["home_points"] if g["is_wvu_home"] else g["away_points"]
    opp = g["away_points"] if g["is_wvu_home"] else g["home_points"]
    return (wvu or 0) > (opp or 0)


def is_postseason(sport: str, d: date) -> bool:
    m, day = POSTSEASON_CUTOFF[sport]
    return d.month > m or (d.month == m and d.day >= day)


def score_at(sport, games_to, moves_to) -> tuple[int, str]:
    w = sum(1 for g in games_to if wvu_won(g))
    l = len(games_to) - w
    total = w + l
    anchor = 30.0 + (w / total) * 40.0 if total else 50.0

    reg = [1 if wvu_won(g) else 0 for g in games_to if not is_postseason(sport, g["_d"])]
    trend = "neutral"
    form_adj = 0.0
    if len(reg) >= 3:
        season = sum(reg) / len(reg)
        recent = sum(reg[-5:]) / len(reg[-5:])
        diff = recent - season
        form_adj = max(-8.0, min(8.0, diff * 30.0))
        trend = "up" if diff > 0.12 else ("down" if diff < -0.12 else "neutral")

    post_wins = sum(1 for g in games_to if is_postseason(sport, g["_d"]) and wvu_won(g))
    reached_omaha = any("charles schwab" in (g.get("venue") or "").lower()
                        or "omaha" in (g.get("venue") or "").lower() for g in games_to)
    surge = min(post_wins * 3.0, 30.0) + (6.0 if reached_omaha else 0.0)

    roster = sum(CAT_WEIGHT.get((m.get("category") or "transfer", m["direction"]), 0.0) for m in moves_to)
    roster = max(-8.0, min(8.0, roster))

    return int(round(max(5, min(99, anchor + form_adj + surge + roster)))), trend


def main() -> None:
    if not SB_URL or not SB_KEY:
        die("Missing SUPABASE_URL or SUPABASE_SECRET_KEY in .env")
    sb = create_client(SB_URL, SB_KEY)
    today = date.today()

    for sport in ("football", "mbb", "baseball"):
        games = (sb.table("games").select("*").eq("sport_id", sport).eq("status", "final")
                 .order("start_date").execute().data)
        if not games:
            continue
        latest_season = max(g["season"] for g in games)
        games = [g for g in games if g["season"] == latest_season]
        for g in games:
            g["_d"] = to_date(g["start_date"])
        games = [g for g in games if g["_d"]]

        moves = sb.table("roster_moves").select("direction,category,move_date").eq("sport_id", sport).execute().data
        for m in moves:
            m["_d"] = to_date(m["move_date"])

        # Snapshot at every game date + move date (before today).
        event_dates = sorted({g["_d"] for g in games} | {m["_d"] for m in moves if m["_d"]})
        rows = []
        for d in event_dates:
            if d >= today:
                continue
            games_to = [g for g in games if g["_d"] <= d]
            if not games_to:
                continue
            moves_to = [m for m in moves if m["_d"] and m["_d"] <= d]
            score, trend = score_at(sport, games_to, moves_to)
            rows.append({"sport_id": sport, "date": d.isoformat(), "score": score, "trend": trend})

        if rows:
            sb.table("pulse_snapshots").upsert(rows, on_conflict="sport_id,date").execute()
        print(f"  {sport:<9} backfilled {len(rows)} historical points "
              f"({rows[0]['date'] if rows else '-'} -> {rows[-1]['date'] if rows else '-'})")

    print("\n[OK] Historical Pulse backfilled. The stock chart has its data.")


if __name__ == "__main__":
    main()
