"""
Mountaineer Pulse - Daily Per-Sport News Note
=============================================
Writes one grounded, CURRENT-program headline per sport (from that sport's
classified news) into daily_sport_notes. This feeds two things, so it must run
BEFORE backfill_pulse.py / compute_pulse.py:
  1. the Pulse chart's per-point note, and
  2. the "news hype" bump in the Pulse score.

Grounding: only the provided headlines; skip former players, off-field/legal/pro
news, rumors, and opinion. If nothing about the current program is notable, no
note is written (and any stale one for today is removed).

Needs ANTHROPIC_API_KEY. Run:  python sync_sport_notes.py
"""

import os
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

SB_URL = os.getenv("SUPABASE_URL")
SB_KEY = os.getenv("SUPABASE_SECRET_KEY")
ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY")

SPORT_NAME = {"football": "Football", "mbb": "Men's Basketball", "baseball": "Baseball"}
NOTE_SYSTEM = (
    "You summarize ONE WVU sport's news for a fan app, in a single line about the CURRENT "
    "program: roster/portal moves, recruiting/commits, game results, rankings/awards, coaching. "
    "ABSOLUTE RULES:\n"
    "1. Use ONLY the headlines provided — never add a name, record, ranking, or fact from your "
    "own knowledge.\n"
    "2. EXCLUDE (treat as not notable): news about FORMER players; off-field/legal/arrest/personal "
    "stories; NFL/NBA/MLB/pro news; opinion, mailbags, fan polls, previews of unrelated teams; and "
    "anything not about the CURRENT WVU roster/team on the field.\n"
    "3. Rumors ('reportedly', 'trending', 'source', 'targets', 'linked', 'could') are NOT facts — "
    "skip them.\n"
    "4. If nothing about the current program is genuinely notable, reply EXACTLY: NONE.\n"
    "One sentence, max 18 words, plain and factual, no hype, no markdown."
)


def die(msg: str) -> None:
    print(f"\n[X] {msg}")
    sys.exit(1)


def main() -> None:
    if not SB_URL or not SB_KEY:
        die("Missing SUPABASE_URL or SUPABASE_SECRET_KEY in .env")
    if not ANTHROPIC_KEY:
        die("No ANTHROPIC_API_KEY in .env")

    import anthropic

    sb = create_client(SB_URL, SB_KEY)
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    today = date.today().isoformat()

    cutoff = (datetime.now(timezone.utc) - timedelta(hours=36)).isoformat()
    news = (sb.table("news_items").select("headline,sport_id,published_at")
            .gte("published_at", cutoff).order("published_at", desc=True).limit(80).execute().data)
    by_sport = defaultdict(list)
    for n in news:
        if n.get("sport_id"):
            by_sport[n["sport_id"]].append(n)

    print("Per-sport notes:")
    for sport in ("football", "mbb", "baseball"):
        items = by_sport.get(sport, [])
        if not items:
            sb.table("daily_sport_notes").delete().eq("id", f"{sport}|{today}").execute()
            print(f"  {SPORT_NAME[sport]}: (no news today)")
            continue
        headlines = "\n".join(f"- {n['headline']}" for n in items[:15])
        resp = client.messages.create(
            model="claude-haiku-4-5", max_tokens=60, system=NOTE_SYSTEM,
            messages=[{"role": "user", "content":
                       f"Today's WVU {SPORT_NAME[sport]} headlines:\n{headlines}\n\n"
                       f"One factual sentence on the single most notable {SPORT_NAME[sport]} development today."}],
        )
        note = "".join(b.text for b in resp.content if b.type == "text").strip()
        if not note or note.upper().startswith("NONE"):
            sb.table("daily_sport_notes").delete().eq("id", f"{sport}|{today}").execute()
            print(f"  {SPORT_NAME[sport]}: (nothing notable)")
            continue
        sb.table("daily_sport_notes").upsert(
            {"id": f"{sport}|{today}", "sport_id": sport, "date": today, "note": note},
            on_conflict="id").execute()
        print(f"  {SPORT_NAME[sport]}: {note}")

    print("\n[OK] Per-sport notes synced.")


if __name__ == "__main__":
    main()
