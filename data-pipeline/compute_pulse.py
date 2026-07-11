"""
Mountaineer Pulse - The Pulse Formula (v2: national-standing-first)
==================================================================
Per-sport Pulse (0-100) is anchored on NATIONAL STANDING (ranking), because
that is the true "against other schools" measure:

  * Ranked team   -> anchor from national rank  (#1 ~= 81, #25 ~= 61)
  * Unranked team -> anchor from win%           (0% = 32, 100% = 78)
  + net postseason (wins - losses), form, roster moves, and news hype

The anchor is kept below the cap so an elite team lands in the 90s with room to
rise AND fall — losses and outbound transfers stay visible instead of pinning at 99.

Trend arrow uses REGULAR-SEASON form only, so a deep postseason run that ends
in a loss (e.g. the CWS) is never mistaken for a decline.

NUMBERS come from the formula; the EXPLANATION is AI-written when
ANTHROPIC_API_KEY is set, else a clean template.

Run:  python compute_pulse.py
"""

import os
import sys
from datetime import date, datetime

from dotenv import load_dotenv
from supabase import create_client

from pulse_model import is_postseason as post_by_date
from pulse_model import clamp, national_rank, news_hype, pulse_score, surge, trend_of, wvu_won

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


def is_postseason(sport: str, g: dict) -> bool:
    if not g.get("start_date"):
        return False
    try:
        d = datetime.fromisoformat(g["start_date"].replace("Z", "+00:00"))
    except ValueError:
        return False
    return post_by_date(sport, d)


def made_cws(games: list[dict]) -> bool:
    return any("charles schwab" in (g.get("venue") or "").lower() or "omaha" in (g.get("venue") or "").lower()
               for g in games)


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

        # Roster movement, by category. Incoming class = transfer/recruit/juco/hs;
        # departures = portal-out plus graduation/eligibility/draft. Only DATED moves
        # count, matching the chart — an undated move can't cause an unexplained bump.
        all_moves = sb.table("roster_moves").select("direction,category,move_date").eq("sport_id", sport).execute().data
        moves = [m for m in all_moves if m.get("move_date")]
        transfers_in = sum(1 for m in moves if m["direction"] == "in" and m.get("category") == "transfer")
        transfers_out = sum(1 for m in moves if m["direction"] == "out" and m.get("category") == "transfer")
        recruits = sum(1 for m in moves if m["direction"] == "in" and m.get("category") in ("recruit", "juco", "hs"))
        departures = sum(1 for m in moves if m["direction"] == "out" and m.get("category") in ("graduation", "eligibility", "draft"))
        transfers_delta = (transfers_in - transfers_out) * 1.5
        recruits_delta = recruits * 0.8
        departures_delta = departures * -0.4

        note_dates = [date.fromisoformat(r["date"][:10]) for r in
                      sb.table("daily_sport_notes").select("date").eq("sport_id", sport).execute().data]
        hype = news_hype(note_dates, date.today())

        reg = [1 if wvu_won(g) else 0 for g in season_games if not is_postseason(sport, g)]
        post_games = [g for g in season_games if is_postseason(sport, g)]
        post_wins = sum(1 for g in post_games if wvu_won(g))
        post_losses = len(post_games) - post_wins
        score = pulse_score(sport, w, l, rank, reg, moves, post_wins, post_losses, hype)

        # Anti-spike guard: the line may only make a big move on a day with a REAL
        # event — a game, a dated roster move, or a news note TODAY. On a "quiet" day
        # nothing can move the score much, so cap the day-over-day change. This stops a
        # transient/partial data read during the daily run from writing a phantom spike
        # (e.g. a -34 drop with no news) that then lingers permanently on the chart.
        has_event_today = (
            any((g.get("start_date") or "")[:10] == today for g in season_games)
            or any((m.get("move_date") or "")[:10] == today for m in moves)
            or date.today() in note_dates
        )
        if not has_event_today:
            prev = (sb.table("pulse_snapshots").select("score").eq("sport_id", sport)
                    .lt("date", today).order("date", desc=True).limit(1).execute().data)
            if prev:
                score = int(round(clamp(score, prev[0]["score"] - 2, prev[0]["score"] + 2)))

        trend = trend_of(reg)
        scored[sport] = score

        # Transparent breakdown of what's moving the score.
        drivers = []
        if rank:
            drivers.append({"label": f"#{rank} nationally", "kind": "rank"})
        if hype >= 1:
            drivers.append({"label": "News buzz", "delta": round(hype), "kind": "news"})
        if cws:
            drivers.append({"label": "CWS run", "delta": round(surge(post_wins, post_losses)), "kind": "post"})
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
