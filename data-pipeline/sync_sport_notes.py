"""
Mountaineer Pulse - Daily Per-Sport News Note
=============================================
Writes one grounded, CURRENT-program news line per sport (from that sport's
classified news plus the day's general WVU headlines) into daily_sport_notes.
This feeds two things, so it must run BEFORE backfill_pulse.py / compute_pulse.py:

  1. the Pulse chart's per-point note (shown for EVERY note day), and
  2. the "news hype" bump in the Pulse score (ONLY for notes flagged `hype`).

So the graph gets a line most days (season outlook, previews, commits, results,
rankings, camps, coaching), but only genuinely BIG news (an award, a commitment,
a ranking, a major win/hire) nudges the actual Pulse number — routine analysis
and columns never move the line.

Grounding: only the provided headlines; skip former players, off-field/legal/pro
news, and rumors-as-fact. If a sport has no relevant WVU headline, no note is
written (and any stale one for today is removed).

Needs ANTHROPIC_API_KEY. Run:  python sync_sport_notes.py
"""

import json
import os
import re
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
    "You write a ONE-LINE daily news note about WVU {sport} for a fan app, based ONLY on "
    "the provided headlines.\n"
    "GOAL: capture what is happening with the CURRENT WVU {sport} program today — season "
    "outlook/schedule analysis, previews, recruiting/commits/signings, portal moves, game "
    "results, rankings, awards, camps, coaching, team news.\n"
    "RULES:\n"
    "1. Use ONLY facts present in the headlines — never add a name, number, ranking, or claim "
    "from your own knowledge.\n"
    "2. Use ONLY headlines clearly about WVU {sport}. Ignore headlines about other teams, other "
    "sports, or unrelated topics.\n"
    "3. EXCLUDE entirely: FORMER players/alumni; off-field/legal/arrest/personal stories; "
    "NFL/NBA/MLB or other pro news; national or other-team stories not about WVU.\n"
    "4. Rumors ('reportedly', 'could', 'targets', 'linked', 'trending', 'source') may be framed "
    "as discussion but NEVER stated as fact — prefer confirmed news.\n"
    "5. If there is genuinely no relevant WVU {sport} headline, the note is NONE.\n"
    "Also decide \"big\": true ONLY when the note is a genuinely notable POSITIVE development that "
    "raises the program's stock — an award/honor, a commitment or signing, a ranking, a major win, "
    "or a big hire. Routine analysis, previews, columns, and schedule breakdowns are big=false.\n"
    "Reply as compact JSON on ONE line: "
    "{{\"note\": \"<one factual sentence, max 18 words, or NONE>\", \"big\": <true or false>}}"
)


def die(msg: str) -> None:
    print(f"\n[X] {msg}")
    sys.exit(1)


def parse_note(raw: str):
    """Return (note, big). Tolerant of stray prose around the JSON."""
    raw = (raw or "").strip()
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if m:
        try:
            obj = json.loads(m.group(0))
            note = str(obj.get("note", "")).strip()
            return note, bool(obj.get("big", False))
        except (ValueError, TypeError):
            pass
    # Fallback: treat the whole reply as the note, not big.
    return raw, False


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
            .gte("published_at", cutoff).order("published_at", desc=True).limit(120).execute().data)
    by_sport = defaultdict(list)
    general = []  # WVU headlines with no sport classification — offered to every sport
    for n in news:
        sid = n.get("sport_id")
        if sid in SPORT_NAME:
            by_sport[sid].append(n["headline"])
        elif not sid:
            general.append(n["headline"])

    print("Per-sport notes:")
    for sport in ("football", "mbb", "baseball"):
        # This sport's own headlines first, then the day's general WVU headlines
        # (the model keeps only the ones clearly about this sport).
        own = by_sport.get(sport, [])
        candidates = own + [h for h in general if h not in own]
        if not candidates:
            sb.table("daily_sport_notes").delete().eq("id", f"{sport}|{today}").execute()
            print(f"  {SPORT_NAME[sport]}: (no news today)")
            continue

        headlines = "\n".join(f"- {h}" for h in candidates[:18])
        resp = client.messages.create(
            model="claude-haiku-4-5", max_tokens=120,
            system=NOTE_SYSTEM.format(sport=SPORT_NAME[sport]),
            messages=[{"role": "user", "content":
                       f"Today's WVU headlines (some may not be about {SPORT_NAME[sport]}):\n"
                       f"{headlines}\n\nWrite the JSON note for WVU {SPORT_NAME[sport]}."}],
        )
        raw = "".join(b.text for b in resp.content if b.type == "text")
        note, big = parse_note(raw)
        if not note or note.upper().startswith("NONE"):
            sb.table("daily_sport_notes").delete().eq("id", f"{sport}|{today}").execute()
            print(f"  {SPORT_NAME[sport]}: (nothing relevant)")
            continue
        sb.table("daily_sport_notes").upsert(
            {"id": f"{sport}|{today}", "sport_id": sport, "date": today, "note": note, "hype": big},
            on_conflict="id").execute()
        print(f"  {SPORT_NAME[sport]}: {'[BIG] ' if big else ''}{note}")

    print("\n[OK] Per-sport notes synced.")


if __name__ == "__main__":
    main()
