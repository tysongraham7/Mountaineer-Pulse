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
    """Assemble the real facts Claude is allowed to use."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=36)).isoformat()
    news = (
        sb.table("news_items").select("headline,source_name,published_at,sport_id")
        .gte("published_at", cutoff).order("published_at", desc=True).limit(40).execute().data
    )

    lines = ["RECENT WVU HEADLINES (last ~36 hours):"]
    if news:
        for n in news:
            tag = f"[{SPORT_NAME.get(n['sport_id'], 'General')}] " if n.get("sport_id") else ""
            lines.append(f"- {tag}{n['headline']} ({n.get('source_name') or 'source'})")
    else:
        lines.append("- (no headlines in the last 36 hours)")

    snaps = sb.table("pulse_snapshots").select("*").order("date", desc=True).execute().data
    seen, pulse_lines = set(), []
    for s in snaps:
        if s["sport_id"] in seen:
            continue
        seen.add(s["sport_id"])
        pulse_lines.append(f"- {SPORT_NAME.get(s['sport_id'], s['sport_id'])}: {s['score']}/100 ({s['trend']})")
    if pulse_lines:
        lines.append("\nTODAY'S MOUNTAINEER PULSE:")
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
        "You write the daily briefing for Mountaineer Pulse, a West Virginia University "
        "sports app. Voice: sharp, factual, a WVU fan's insider — never hype, never fluff. "
        "STRICT RULE: use ONLY the facts provided. Do not invent scores, names, or events. "
        "If there is little news, say plainly that it's a quiet day."
    )
    prompt = (
        f"{context}\n\n"
        "Write today's briefing. Start with a short, warm one-line greeting, then give the "
        "3 biggest WVU athletics developments from the last 24-36 hours as a numbered list "
        "(one crisp sentence each). If there isn't enough real news for three, give fewer. "
        "Keep the whole thing under 120 words. Plain text, no markdown headers."
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


if __name__ == "__main__":
    main()
