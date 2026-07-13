"""
Mountaineer Pulse - Historical Backfill (the stock chart's data)
================================================================
Recomputes each program's Pulse at every past game date and roster-move date,
using the SHARED model in pulse_model.py — so the chart line and today's number
(compute_pulse.py) always agree, and every rise/fall ties to a real event.

Rebuilds each sport's history from scratch each run (deletes stale points first),
so removed/redated moves don't leave orphan points on the chart.

Run:  python backfill_pulse.py
"""

import os
import sys
from datetime import date, datetime

from dotenv import load_dotenv
from supabase import create_client

from pulse_model import (OFFSEASON_BONUS, SEASON_RANK, is_postseason, national_rank,
                         news_delta, pulse_score, trend_of, wvu_won)

load_dotenv()

SB_URL = os.getenv("SUPABASE_URL")
SB_KEY = os.getenv("SUPABASE_SECRET_KEY")


def die(msg: str) -> None:
    print(f"\n[X] {msg}")
    sys.exit(1)


def to_date(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return date.fromisoformat(s[:10])
        except ValueError:
            return None


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

        moves = sb.table("roster_moves").select("direction,category,move_date,impact").eq("sport_id", sport).execute().data
        for m in moves:
            m["_d"] = to_date(m["move_date"])

        note_rows = sb.table("daily_sport_notes").select("date,pulse_delta").eq("sport_id", sport).execute().data
        # Every note day gets a chart point (so the line's note is hoverable); the
        # SIGNED pulse_delta of each note moves the score (up or down) and holds.
        note_dates = [d for d in (to_date(r["date"]) for r in note_rows) if d]
        note_deltas = [(to_date(r["date"]), r.get("pulse_delta") or 0) for r in note_rows if to_date(r["date"])]

        # A sport with a SEASON_RANK was ranked all year: hold that caliber FLAT across
        # its whole latest season (regular season floors at one level; the CWS surge and
        # roster departures move it from there). Otherwise use the live poll.
        season_rank = SEASON_RANK.get(sport)
        base_rank = season_rank if season_rank else national_rank(sport)
        flat = bool(season_rank)
        last_game = max((g["_d"] for g in games), default=None)
        off_bonus = OFFSEASON_BONUS.get(sport, 0.0)

        # A point at every game date + dated move date + news day.
        event_dates = sorted({g["_d"] for g in games} | {m["_d"] for m in moves if m["_d"]} | set(note_dates))
        rows = []
        for d in event_dates:
            if d >= today:
                continue
            games_to = [g for g in games if g["_d"] <= d]
            if not games_to:
                continue
            moves_to = [m for m in moves if m["_d"] and m["_d"] <= d]
            w = sum(1 for g in games_to if wvu_won(g))
            l = len(games_to) - w
            reg = [1 if wvu_won(g) else 0 for g in games_to if not is_postseason(sport, g["_d"])]
            post_games = [g for g in games_to if is_postseason(sport, g["_d"])]
            post_wins = sum(1 for g in post_games if wvu_won(g))
            post_losses = len(post_games) - post_wins
            news = news_delta(note_deltas, d)
            # Offseason bonus (projected next-season caliber) applies only after the
            # season's final game — it lifts the offseason line, not the played season.
            extra = off_bonus if (last_game and d > last_game) else 0.0
            score = pulse_score(sport, w, l, base_rank, reg, moves_to, post_wins, post_losses,
                                news, ranked_flat=flat, extra=extra)
            rows.append({"sport_id": sport, "date": d.isoformat(), "score": score, "trend": trend_of(reg)})

        # Rebuild from scratch so stale points (old/redated moves) don't linger.
        sb.table("pulse_snapshots").delete().eq("sport_id", sport).execute()
        if rows:
            sb.table("pulse_snapshots").upsert(rows, on_conflict="sport_id,date").execute()
        print(f"  {sport:<9} rebuilt {len(rows)} points "
              f"({rows[0]['date'] if rows else '-'} -> {rows[-1]['date'] if rows else '-'})  "
              f"rank {base_rank or 'NR'}{' flat' if flat else ''}")

    print("\n[OK] Historical Pulse rebuilt with the shared model.")


if __name__ == "__main__":
    main()
