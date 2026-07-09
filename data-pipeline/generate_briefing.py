"""
Mountaineer Pulse - Daily AI Briefing
=====================================
Claude reads the last ~36h of WVU headlines + today's Mountaineer Pulse and
writes a short "3 biggest developments" briefing for the app's home screen.

Needs ANTHROPIC_API_KEY in .env (get one at https://console.anthropic.com).

Model: claude-sonnet-5 (strong synthesis, cheaper than Opus). Swap MODEL below to
"claude-haiku-4-5" for the cheapest option, or "claude-opus-4-8" for top quality.

Run:  python generate_briefing.py
"""

import os
import sys
from datetime import date, datetime, timedelta, timezone

from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

SB_URL = os.getenv("SUPABASE_URL")
SB_KEY = os.getenv("SUPABASE_SECRET_KEY")
ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY")

MODEL = "claude-sonnet-5"          # cheaper than Opus; "claude-haiku-4-5" is ~cheapest
SPORT_NAME = {"football": "Football", "mbb": "Men's Basketball", "baseball": "Baseball"}


def die(msg: str) -> None:
    print(f"\n[X] {msg}")
    sys.exit(1)


def build_context(sb) -> str:
    """Assemble the real facts Claude is allowed to use — nothing else exists."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=36)).isoformat()
    news = (
        sb.table("news_items").select("headline,source_name,published_at,sport_id")
        .gte("published_at", cutoff).order("published_at", desc=True).limit(40).execute().data
    )

    lines = ["=== RECENT WVU HEADLINES (last ~36 hours) ==="]
    if news:
        for n in news:
            tag = f"[{SPORT_NAME.get(n['sport_id'], 'General')}] " if n.get("sport_id") else ""
            lines.append(f"- {tag}{n['headline']} ({n.get('source_name') or 'source'})")
    else:
        lines.append("- (no headlines in the last 36 hours)")

    # The ONLY source of truth for who is actually on/off the roster.
    moves = (
        sb.table("roster_moves").select("player_name,position,direction,category,sport_id")
        .order("move_date", desc=True).execute().data
    )
    if moves:
        lines.append("\n=== CONFIRMED ROSTER MOVES (only source of truth for who is in/out) ===")
        for m in moves:
            d = "IN" if m["direction"] == "in" else "OUT"
            pos = f" {m['position']}" if m.get("position") else ""
            lines.append(f"- {d}: {m['player_name']}{pos} "
                         f"({SPORT_NAME.get(m['sport_id'], m['sport_id'])}, {m.get('category') or 'move'})")

    snaps = sb.table("pulse_snapshots").select("*").order("date", desc=True).execute().data
    seen, pulse_lines = set(), []
    for s in snaps:
        if s["sport_id"] in seen:
            continue
        seen.add(s["sport_id"])
        pulse_lines.append(f"- {SPORT_NAME.get(s['sport_id'], s['sport_id'])}: {s['score']}/100 ({s['trend']})")
    if pulse_lines:
        lines.append("\n=== TODAY'S MOUNTAINEER PULSE ===")
        lines += pulse_lines

    return "\n".join(lines)


def main() -> None:
    if not SB_URL or not SB_KEY:
        die("Missing SUPABASE_URL or SUPABASE_SECRET_KEY in .env")
    if not ANTHROPIC_KEY:
        die("No ANTHROPIC_API_KEY in .env — get one at https://console.anthropic.com")

    import anthropic

    sb = create_client(SB_URL, SB_KEY)
    context = build_context(sb)

    system = (
        "You write the daily briefing for Mountaineer Pulse, a West Virginia University sports "
        "app. Voice: sharp, factual, a plugged-in WVU fan. Never hype, never filler.\n\n"
        "ABSOLUTE RULES — accuracy is everything; one wrong fact loses a fan's trust:\n"
        "1. Use ONLY the facts in the DATA provided. Never add a name, coach, player, position, "
        "record, ranking, or any context from your own knowledge — even if you believe you know "
        "it. If it is not written in the DATA, it does not exist for this briefing. (You do NOT "
        "know who WVU's coaches are unless the DATA says so.)\n"
        "2. Rumors are not facts. Headlines with words like 'trending', 'source', 'reportedly', "
        "'linked', 'targets', 'could', or 'rumored' are SPECULATION — never state them as done "
        "deals. Skip them, or clearly mark them ('reportedly').\n"
        "3. A roster move is real ONLY if it appears in CONFIRMED ROSTER MOVES. Never call a "
        "player a commit/signing/transfer unless he is on that list.\n"
        "4. Significance filter: include only genuinely notable items. Do NOT pad to hit a "
        "number, and NEVER inflate a single minor item (one former player's pro news, a routine "
        "ranking blurb) into a category.\n"
        "5. Slow news day? Say so plainly. A short honest briefing beats a padded one."
    )
    prompt = (
        f"DATA:\n{context}\n\n"
        "Write today's briefing: a short, warm one-line greeting, then the genuinely notable WVU "
        "developments as a numbered list (one crisp sentence each). Give 2-3 ONLY if you truly "
        "have that many worth a fan's attention — otherwise give one, or just say it's a quiet "
        "day. Under 110 words. Plain text, no markdown headers, no invented facts."
    )

    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    resp = client.messages.create(
        model=MODEL,
        max_tokens=700,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    briefing = "".join(b.text for b in resp.content if b.type == "text").strip()

    if not briefing:
        die("Claude returned an empty briefing.")

    today = date.today().isoformat()
    sb.table("daily_briefings").upsert({"date": today, "content": briefing}, on_conflict="date").execute()

    print(f"Daily Briefing ({today}) — {MODEL}\n" + "-" * 60)
    print(briefing)
    print("-" * 60)
    print(f"\n[OK] Briefing stored. (tokens: {resp.usage.input_tokens} in / {resp.usage.output_tokens} out)")

    generate_sport_notes(client, sb, today)


if __name__ == "__main__":
    main()
