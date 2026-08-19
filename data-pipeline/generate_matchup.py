"""
Mountaineer Pulse - Game-Day Scouting Report
============================================
A full preview of the next game: who the opponent is, how they've been playing, the
head-to-head history, keys to victory, what the opponent does well, where WVU can
attack, injuries and the weather.

Two rules shape the design.

FACTS WE OWN COME FROM OUR DATABASE. WVU's projected starters, stat leaders, recent roster
moves and Pulse are read straight from Supabase and handed to the model as fixed context —
it may not restate them differently. Only the OPPONENT and external facts (weather,
injuries) come from web search. That keeps the half of the report we can verify verifiable.

IT ONLY RUNS NEAR GAME DAY. A report generated three weeks out has stale injuries and a
forecast that does not exist yet, and burns web search for nothing. Nothing happens unless a game falls inside
LOOKAHEAD_DAYS, so this is safe to run daily year-round — most days it exits immediately.
Inside the window it refreshes as kickoff nears, so injuries and the forecast stay current.

Writes to matchups (one row per game_id). Needs ANTHROPIC_API_KEY.
Run:  python generate_matchup.py [--dry-run] [--force] [--game-id N]
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from supabase import create_client

import usage as api_usage
# Reuse the briefing's hardened helpers rather than re-implementing them: the retry/
# pause_turn handling in particular took a real outage to get right.
from generate_briefing import _create_resilient, extract_json, strip_tags

load_dotenv()

SB_URL = os.getenv("SUPABASE_URL")
SB_KEY = os.getenv("SUPABASE_SECRET_KEY")
ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY")

MODEL = "claude-sonnet-5"
# 6, not 10: the retry helper resumes a paused search loop, and each resume gets a FRESH
# budget — a 10-cap run actually spent 24 searches and $0.56. Capping lower bounds the
# worst case, and the budget note in the prompt keeps a normal run well under it.
WEB_SEARCH_TOOL = {"type": "web_search_20260209", "name": "web_search", "max_uses": 6}
SPORT_NAME = {"football": "Football", "mbb": "Men's Basketball", "baseball": "Baseball"}

# Only preview a game this close. "A week or two out" — before that, injuries and the
# forecast don't exist yet and anything written would be stale by kickoff.
LOOKAHEAD_DAYS = 10

SEARCH_BUDGET = (
    "\n\nSEARCH BUDGET: web search is the cost here. Spend it on what actually changes the "
    "report — the opponent's record and current form, the quarterback/lineup situation, the "
    "injury report, the line, the forecast. Do NOT re-search to confirm something you already "
    "found, and do not research WVU at all: those facts are given above. Aim for about 5 "
    "searches. Once you can fill the JSON, stop searching and write it."
)


def refresh_hours(days_out: float) -> int:
    """How stale a report may get before regenerating, scaled to how close kickoff is.

    Regenerating daily for ten straight days costs roughly $5.60 per game — most of it
    re-researching a record and a series history that haven't changed. What actually moves
    late is the injury report and the weather, so the cadence tightens as the game
    approaches: one report when it enters the window, another at midweek, then daily in the
    last two days. About four runs per game instead of ten.
    """
    if days_out > 5:
        return 96
    if days_out > 2:
        return 48
    return 20


def die(msg: str) -> None:
    print(f"\n[X] {msg}")
    sys.exit(1)


def next_game(sb, game_id: int | None):
    """The soonest scheduled game inside the lookahead window, or a specific one by id."""
    if game_id:
        rows = sb.table("games").select("*").eq("id", game_id).execute().data
        return rows[0] if rows else None
    now = datetime.now(timezone.utc)
    horizon = (now + timedelta(days=LOOKAHEAD_DAYS)).isoformat()
    rows = (sb.table("games").select("*")
            .neq("status", "final")
            .gte("start_date", now.isoformat())
            .lte("start_date", horizon)
            .order("start_date").limit(1).execute().data or [])
    return rows[0] if rows else None


def wvu_context(sb, game: dict) -> str:
    """WVU's side of the matchup, straight from our own tables. The model is told to treat
    this as fixed — it's the half of the report we can actually verify."""
    sport = game["sport_id"]
    lines: list[str] = []

    depth = (sb.table("depth_chart").select("unit,position,pos_order,rank,player_name,note,status")
             .eq("sport_id", sport).order("pos_order").order("rank").execute().data or [])
    starters = [d for d in depth if d.get("rank") == 1]
    if starters:
        lines.append("=== WVU PROJECTED STARTERS (from our depth chart — use these names) ===")
        for d in starters:
            note = f" — {d['note']}" if d.get("note") else ""
            flag = "  [!]" if (d.get("status") or "active") != "active" else ""
            lines.append(f"- {d['position']}: {d['player_name']}{note}{flag}")

    stats = (sb.table("player_stats").select("player_name,category,stat_type,stat,season")
             .eq("sport_id", sport).order("season", desc=True).limit(120).execute().data or [])
    if stats:
        newest = max(s["season"] for s in stats)
        top = [s for s in stats if s["season"] == newest][:40]
        if top:
            lines.append(f"\n=== WVU STAT LEADERS ({newest}) ===")
            for s in top:
                lines.append(f"- {s['player_name']}: {s['stat']} {s['stat_type']} ({s['category']})")

    moves = (sb.table("roster_moves").select("player_name,position,direction,category,other_school,move_date")
             .eq("sport_id", sport).order("move_date", desc=True).limit(10).execute().data or [])
    if moves:
        lines.append("\n=== RECENT WVU ROSTER MOVES ===")
        for m in moves:
            d = "IN" if m["direction"] == "in" else "OUT"
            sch = f" ({'from' if d == 'IN' else 'to'} {m['other_school']})" if m.get("other_school") else ""
            lines.append(f"- {d}: {m['player_name']} {m.get('position') or ''}{sch} [{m.get('move_date')}]")

    snap = (sb.table("pulse_snapshots").select("score,trend,date")
            .eq("sport_id", sport).order("date", desc=True).limit(1).execute().data or [])
    if snap:
        lines.append(f"\n=== MOUNTAINEER PULSE === \n- {snap[0]['score']}/100 ({snap[0]['trend']})")

    return "\n".join(lines)


SYSTEM = (
    "You write the game-day scouting report for Mountaineer Pulse, a West Virginia University "
    "sports app. Voice: sharp, factual, a plugged-in fan who has done the homework. Never hype.\n\n"
    "You have web search. Use it to research the OPPONENT and the external facts — their record, "
    "form, key players, injuries, the line, the forecast, and the series history.\n\n"
    "ABSOLUTE RULES — one wrong fact loses a fan's trust:\n"
    "1. WVU FACTS ARE GIVEN TO YOU. The projected starters, stat leaders, roster moves and Pulse "
    "in the DATA block are authoritative. Use those names and numbers exactly; never substitute a "
    "player you remember or found online, and never promote someone to starter who isn't listed.\n"
    "2. Everything about the OPPONENT must come from your searches, not memory. If you cannot "
    "confirm something, leave that field empty rather than guessing. An empty field is fine.\n"
    "3. Injury news moves. Attribute it and note it is as-of today; never state an injury as "
    "settled fact if the source hedges.\n"
    "4. If the two teams have never played, say so plainly rather than inventing a series history.\n"
    "5. No predictions of the final score. Analysis of what decides the game, not a guess at it.\n"
    "6. THE LINE IS CONTEXT, NOT A TIP. Give the spread and total plainly, as the number a "
    "fan should expect the game to look like, and attribute it with an as-of date. Never "
    "frame it as advice, never name a sportsbook as a place to wager, never say what to "
    "back or which side has value, and never use 'lock', 'value', 'edge' or 'pick'.\n\n"
    "OUTPUT — reply with ONLY a JSON object, no prose around it:\n"
    "{\n"
    '  "headline": "<one sharp sentence framing the game>",\n'
    '  "opponent": {"record": "<e.g. 8-5 (5-3 Sun Belt), 2025>", "snapshot": "<2-3 sentences: who '
    'they are, how they played last season, who runs the offense>"},\n'
    '  "history": "<series history, or \'First meeting.\'>",\n'
    '  "keys": [{"topic": "<3-6 words>", "body": "<2-3 sentences: something WVU must actually '
    'DO to win, not a storyline>"}],\n'
    '  "strengths": "<2-3 sentences on what the opponent genuinely does well and WVU has to '
    'respect. Never empty flattery; if they are outmatched, say where they are least so>",\n'
    '  "exploit": "<2-3 sentences on the opponent\'s clearest weakness and how WVU attacks '
    'it, naming the WVU players from the DATA above>",\n'
    '  "injuries": "<notable availability for either side, attributed — or empty>",\n'
    '  "line": "<the spread and total as of today, attributed — or empty>",\n'
    '  "weather": "<forecast at kickoff for outdoor games — or empty>"\n'
    "}\n"
    "Give 2-3 'keys'. Keep every field tight. 'strengths' and 'exploit' are two halves of one "
    "judgement — what they can hurt you with, and what you can hurt them with — so neither may "
    "be a restatement of the other."
)


def to_plaintext(obj: dict, game: dict) -> str:
    parts = [obj.get("headline", "").strip()]
    op = obj.get("opponent") or {}
    if op.get("record"):
        parts.append(f"\nOPPONENT: {op['record']}")
    if op.get("snapshot"):
        parts.append(op["snapshot"])
    if obj.get("history"):
        parts.append(f"\nHISTORY: {obj['history']}")
    for w in obj.get("keys", []):
        parts.append(f"\n• {w.get('topic', '')}: {w.get('body', '')}")
    if obj.get("strengths"):
        parts.append(f"\nWHAT THEY DO WELL: {obj['strengths']}")
    if obj.get("exploit"):
        parts.append(f"\nWHERE TO ATTACK: {obj['exploit']}")
    for k in ("injuries", "line", "weather"):
        if obj.get(k):
            parts.append(f"\n{k.upper()}: {obj[k]}")
    return "\n".join(p for p in parts if p and p.strip()).strip()


def clean(obj: dict) -> dict:
    """Strip web-search cite tags everywhere, and drop malformed keys."""
    out = {
        "headline": strip_tags(str(obj.get("headline", ""))),
        "opponent": {
            "record": strip_tags(str((obj.get("opponent") or {}).get("record", ""))),
            "snapshot": strip_tags(str((obj.get("opponent") or {}).get("snapshot", ""))),
        },
        "history": strip_tags(str(obj.get("history", ""))),
        "injuries": strip_tags(str(obj.get("injuries", ""))),
        "line": strip_tags(str(obj.get("line", ""))),
                "weather": strip_tags(str(obj.get("weather", ""))),
        "strengths": strip_tags(str(obj.get("strengths", ""))),
        "exploit": strip_tags(str(obj.get("exploit", ""))),
        "keys": [],
    }
    for w in (obj.get("keys") or [])[:3]:
        topic = strip_tags(str(w.get("topic", "")))
        body = strip_tags(str(w.get("body", "")))
        if topic and body:
            out["keys"].append({"topic": topic, "body": body})
    return out


def main() -> None:
    dry = "--dry-run" in sys.argv
    force = "--force" in sys.argv
    gid = None
    if "--game-id" in sys.argv:
        gid = int(sys.argv[sys.argv.index("--game-id") + 1])
    if not SB_URL or not SB_KEY:
        die("Missing SUPABASE_URL or SUPABASE_SECRET_KEY")
    if not ANTHROPIC_KEY:
        die("No ANTHROPIC_API_KEY")

    import anthropic

    sb = create_client(SB_URL, SB_KEY)
    game = next_game(sb, gid)
    if not game:
        print(f"No game inside the next {LOOKAHEAD_DAYS} days — nothing to preview.")
        return

    kickoff = game.get("start_date")
    opp = game["away_team"] if game.get("is_wvu_home") else game["home_team"]
    where = "vs" if game.get("is_wvu_home") else "at"
    sport = SPORT_NAME.get(game["sport_id"], game["sport_id"])
    print(f"{sport}: WVU {where} {opp} — {kickoff} @ {game.get('venue') or 'TBD'}")

    days_out = (datetime.fromisoformat(kickoff) - datetime.now(timezone.utc)).total_seconds() / 86400
    stale_after = refresh_hours(days_out)
    existing = sb.table("matchups").select("generated_at").eq("game_id", game["id"]).execute().data
    if existing and not force and not dry:
        age = datetime.now(timezone.utc) - datetime.fromisoformat(existing[0]["generated_at"])
        if age < timedelta(hours=stale_after):
            print(f"  Report is {age.total_seconds() / 3600:.0f}h old and kickoff is "
                  f"{days_out:.1f}d away (refresh every {stale_after}h) — skipping.")
            return

    data = (
        f"=== THE GAME ===\n"
        f"- {sport}, week {game.get('week') or '?'}, {game.get('season_type') or 'regular'} season\n"
        f"- West Virginia {where} {opp}\n"
        f"- Kickoff (UTC): {kickoff}\n"
        f"- Venue: {game.get('venue') or 'TBD'}\n"
        f"- WVU is {'HOME' if game.get('is_wvu_home') else 'AWAY'}\n\n"
        f"{wvu_context(sb, game)}"
    )
    instruction = (
        f"Research {opp} and write the scouting report JSON for this game. Today is "
        f"{datetime.now(timezone.utc).date().isoformat()}. Spend your searches on the OPPONENT, "
        f"the injury report and the forecast — the WVU facts above are already "
        f"correct and must be used as given."
    ) + SEARCH_BUDGET

    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    kwargs = dict(
        model=MODEL,
        max_tokens=6000,
        thinking={"type": "adaptive"},
        system=[{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": [
            {"type": "text", "text": f"DATA:\n{data}", "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": instruction},
        ]}],
        tools=[WEB_SEARCH_TOOL],
    )
    blocks, resp = _create_resilient(client, kwargs)
    text = "".join(b.text for b in blocks if getattr(b, "type", "") == "text").strip()
    searches = sum(1 for b in blocks if getattr(b, "type", "") == "server_tool_use")

    obj = extract_json(text)
    if not obj:
        die(f"No parseable JSON. Tail: ...{text[-300:]!r}")
    report = clean(obj)
    if not report["headline"] and not report["keys"]:
        die("Report came back empty.")

    content = to_plaintext(report, game)
    print("-" * 60)
    print(content)
    print("-" * 60)
    api_usage.log_raw(sb, "generate_matchup", MODEL, resp.usage, searches)

    if dry:
        print(f"\n[dry run] {searches} searches. Nothing written.")
        return

    sb.table("matchups").upsert({
        "game_id": game["id"],
        "sport_id": game["sport_id"],
        "kickoff": kickoff,
        "opponent": opp,
        "sections": report,
        "content": content,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }, on_conflict="game_id").execute()
    print(f"\n[OK] Scouting report stored for game {game['id']} ({searches} searches).")


if __name__ == "__main__":
    main()
