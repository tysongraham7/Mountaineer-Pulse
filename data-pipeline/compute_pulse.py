"""
Mountaineer Pulse - The Pulse Formula (v2: national-standing-first)
==================================================================
Per-sport Pulse (0-100) is anchored on NATIONAL STANDING (ranking), because
that is the true "against other schools" measure:

  * Ranked team   -> anchor from national rank  (#1 ~= 98, #25 ~= 76)
  * Unranked team -> anchor from win%           (0% = 30, 100% = 70)
  + postseason bonus (e.g. College World Series appearance)

Trend arrow uses REGULAR-SEASON form only, so a deep postseason run that ends
in a loss (e.g. the CWS) is never mistaken for a decline.

NUMBERS come from the formula; the EXPLANATION is AI-written when
ANTHROPIC_API_KEY is set, else a clean template.

Run:  python compute_pulse.py
"""

import os
import sys
from datetime import date, datetime

import requests
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

SB_URL = os.getenv("SUPABASE_URL")
SB_KEY = os.getenv("SUPABASE_SECRET_KEY")

WEIGHTS = {"football": 0.5, "mbb": 0.3, "baseball": 0.2}
SPORT_NAME = {"football": "Football", "mbb": "Men's Basketball", "baseball": "Baseball"}
ESPN_PATH = {
    "football": "football/college-football",
    "mbb": "basketball/mens-college-basketball",
    "baseball": "baseball/college-baseball",
}
# Games on/after (month, day) are treated as postseason for the TREND calc.
POSTSEASON_CUTOFF = {"football": (12, 1), "mbb": (3, 12), "baseball": (5, 20)}
UA = {"User-Agent": "Mozilla/5.0"}


def die(msg: str) -> None:
    print(f"\n[X] {msg}")
    sys.exit(1)


def wvu_won(g: dict) -> bool:
    wvu = g["home_points"] if g["is_wvu_home"] else g["away_points"]
    opp = g["away_points"] if g["is_wvu_home"] else g["home_points"]
    return (wvu or 0) > (opp or 0)


def national_rank(sport: str) -> int | None:
    """WVU's current national rank from ESPN's rankings (media poll), or None."""
    try:
        j = requests.get(
            f"https://site.api.espn.com/apis/site/v2/sports/{ESPN_PATH[sport]}/rankings",
            headers=UA,
            timeout=20,
        ).json()
        for poll in j.get("rankings", []):
            if "seed" in (poll.get("name", "").lower()):
                continue  # prefer a media poll over tournament seedings
            for r in poll.get("ranks", []):
                team = r.get("team", {}) or {}
                blob = f"{team.get('name','')} {team.get('location','')} {team.get('displayName','')}".lower()
                if "west virginia" in blob:
                    return r.get("current")
    except Exception as e:
        print(f"    (ranking lookup failed for {sport}: {e})")
    return None


def is_postseason(sport: str, g: dict) -> bool:
    if not g.get("start_date"):
        return False
    try:
        d = datetime.fromisoformat(g["start_date"].replace("Z", "+00:00"))
    except ValueError:
        return False
    m, day = POSTSEASON_CUTOFF[sport]
    return d.month > m or (d.month == m and d.day >= day)


def made_cws(games: list[dict]) -> bool:
    return any("charles schwab" in (g.get("venue") or "").lower() or "omaha" in (g.get("venue") or "").lower()
               for g in games)


def anchor_score(w: int, l: int, rank: int | None) -> float:
    if rank is not None:
        return 98.0 - (rank - 1) * (22.0 / 24.0)  # #1 -> 98, #25 -> 76
    total = w + l
    winpct = (w / total) if total else 0.5
    return 30.0 + winpct * 40.0  # 0% -> 30, 50% -> 50, 100% -> 70


def trend_from_regular(sport: str, games: list[dict]) -> str:
    reg = [1 if wvu_won(g) else 0 for g in games if not is_postseason(sport, g)]
    if len(reg) < 3:
        return "neutral"
    season = sum(reg) / len(reg)
    recent = sum(reg[-5:]) / len(reg[-5:])
    diff = recent - season
    return "up" if diff > 0.12 else ("down" if diff < -0.12 else "neutral")


def ai_explanation(ctx: str) -> str | None:
    key = os.getenv("ANTHROPIC_API_KEY")
    if not key:
        return None
    try:
        import anthropic

        client = anthropic.Anthropic(api_key=key)
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=80,
            messages=[{
                "role": "user",
                "content": (
                    "Write ONE punchy, factual sentence (max 24 words, no emojis, no hype) for a "
                    f"WVU sports app summarizing this program. Facts: {ctx}"
                ),
            }],
        )
        return msg.content[0].text.strip()
    except Exception as e:
        print(f"    (AI explanation skipped: {e})")
        return None


def template_explanation(name, w, l, season, score, rank, cws) -> str:
    if rank and cws:
        return f"{name} is elite — #{rank} nationally with a College World Series run and a {w}-{l} record ({season})."
    if rank:
        return f"{name} is ranked #{rank} in the nation at {w}-{l} ({season})."
    if score >= 58:
        return f"{name} is holding its own at {w}-{l} ({season})."
    return f"{name} is in a rebuilding stretch at {w}-{l} ({season})."


def main() -> None:
    if not SB_URL or not SB_KEY:
        die("Missing SUPABASE_URL or SUPABASE_SECRET_KEY in .env")
    sb = create_client(SB_URL, SB_KEY)
    today = date.today().isoformat()

    scored: dict[str, int] = {}
    print("Computing Mountaineer Pulse (v2: national-standing-first)...\n")

    for sport in ("football", "mbb", "baseball"):
        games = (
            sb.table("games").select("*").eq("sport_id", sport).eq("status", "final")
            .order("start_date").execute().data
        )
        if not games:
            print(f"  {sport}: no completed games, skipping")
            continue

        latest_season = max(g["season"] for g in games)
        season_games = [g for g in games if g["season"] == latest_season]
        w = sum(1 for g in season_games if wvu_won(g))
        l = len(season_games) - w

        rank = national_rank(sport)
        cws = sport == "baseball" and made_cws(season_games)

        # Offseason driver: roster movement, weighted by category. A graduating
        # senior is expected attrition (~0); a portal departure is a real signal.
        moves = sb.table("roster_moves").select("direction,category").eq("sport_id", sport).execute().data
        transfers_in = sum(1 for m in moves if m["direction"] == "in" and m.get("category") == "transfer")
        transfers_out = sum(1 for m in moves if m["direction"] == "out" and m.get("category") == "transfer")
        recruits = sum(1 for m in moves if m["direction"] == "in" and m.get("category") == "recruit")
        departures = sum(1 for m in moves if m["direction"] == "out" and m.get("category") in ("graduation", "draft"))

        transfers_delta = (transfers_in - transfers_out) * 1.5
        recruits_delta = recruits * 1.0
        departures_delta = departures * -0.4  # graduations/draft: expected, light
        roster_delta = max(-8.0, min(8.0, transfers_delta + recruits_delta + departures_delta))

        anchor = anchor_score(w, l, rank)
        bonus = 4.0 if cws else 0.0
        score = int(round(max(5, min(99, anchor + bonus + roster_delta))))
        trend = trend_from_regular(sport, season_games)
        scored[sport] = score

        # Transparent breakdown of what's moving the score.
        drivers = []
        if rank:
            drivers.append({"label": f"#{rank} nationally", "kind": "rank"})
        if cws:
            drivers.append({"label": "CWS run", "delta": 4, "kind": "post"})
        if transfers_in or transfers_out:
            drivers.append({"label": f"Transfers +{transfers_in}/-{transfers_out}",
                            "delta": round(transfers_delta), "kind": "portal"})
        if recruits:
            drivers.append({"label": f"Recruits +{recruits}", "delta": round(recruits_delta), "kind": "recruit"})
        if departures:
            drivers.append({"label": f"Departures -{departures}", "delta": round(departures_delta), "kind": "depart"})

        name = SPORT_NAME[sport]
        ctx = (f"{name}, {w}-{l} in {latest_season}, national rank {rank or 'unranked'}, "
               f"{'made College World Series, ' if cws else ''}"
               f"transfers in {transfers_in}/out {transfers_out}, {recruits} recruits signed, "
               f"{departures} graduated/drafted, Pulse {score}/100, momentum {trend}")
        explanation = ai_explanation(ctx) or template_explanation(name, w, l, latest_season, score, rank, cws)

        sb.table("pulse_snapshots").upsert(
            {"sport_id": sport, "date": today, "score": score, "trend": trend,
             "ranking": rank, "explanation": explanation, "drivers": drivers},
            on_conflict="sport_id,date",
        ).execute()
        arrow = {"up": "^", "down": "v", "neutral": "-"}[trend]
        rk = f"#{rank}" if rank else "NR"
        print(f"  {name:<18} {score:>3}/100  [{arrow}]  {w}-{l} ({latest_season})  rank {rk}  "
              f"T+{transfers_in}/-{transfers_out} R+{recruits} D-{departures}{'  CWS' if cws else ''}")
        print(f"      {explanation}")

    if scored:
        wsum = sum(WEIGHTS[s] for s in scored)
        overall = int(round(sum(scored[s] * WEIGHTS[s] for s in scored) / wsum))
        best = max(scored, key=scored.get)
        summary = f"WVU athletics sits at {overall}/100, led by {SPORT_NAME[best]}."
        sb.table("pulse_overall").upsert({"date": today, "score": overall, "summary": summary}).execute()
        print(f"\n  OVERALL: {overall}/100 — {summary}")

    print("\n[OK] Mountaineer Pulse computed and stored.")


if __name__ == "__main__":
    main()
