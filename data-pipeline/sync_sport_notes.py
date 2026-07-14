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
    "2. Use ONLY headlines EXPLICITLY about WVU {sport}. A headline qualifies only if it names the "
    "sport, a known WVU {sport} player/coach, or a {sport}-specific event (a game, signing, ranking, "
    "camp). If a WVU headline is generic and does NOT clearly indicate the sport (e.g. 'Texas standout "
    "commits to WVU', 'recruit picks the Mountaineers' — no sport named), OMIT it. NEVER guess which "
    "sport an ambiguous headline belongs to; when in doubt, leave it out.\n"
    "3. EXCLUDE entirely: FORMER players/alumni; off-field/legal/arrest/personal stories; "
    "NFL/NBA/MLB or other pro news; national or other-team stories not about WVU; and commitments "
    "from FUTURE recruiting classes (high-schoolers a year or more away, e.g. class of 2027 or "
    "later) — this app tracks the CURRENT program only. A 'commit'/'standout'/'pledge' with no stated "
    "college class, transfer origin, or signing for THIS upcoming season may well be a high-school "
    "prospect from a future class — do NOT use it unless it is clearly an incoming college TRANSFER or "
    "a confirmed signee for the current/upcoming season.\n"
    "4. Rumors ('reportedly', 'could', 'targets', 'linked', 'trending', 'source') may be framed "
    "as discussion but NEVER stated as fact — prefer confirmed news.\n"
    "5. If there is genuinely no relevant WVU {sport} headline, the note is NONE.\n"
    "Then set \"delta\": a SIGNED integer for how this news moves the program's Pulse. Be "
    "CONSERVATIVE — most days are 0. Use small values only, never large swings:\n"
    "  +2 = MAJOR good news raising national standing (national/conference honor, top-25 ranking, "
    "marquee or ranked win, major coaching hire, a marquee commitment).\n"
    "  +1 = solid good news (a notable commitment/signing, a clear quality win).\n"
    "   0 = routine/neutral (previews, analysis, schedule talk, minor notes) — the DEFAULT.\n"
    "  -1 = notable bad program news (a rotation player enters the portal, a recruit decommits, a "
    "meaningful injury).\n"
    "  -2 = significant bad news hurting the current program (losing a key starter or vital signee, "
    "a major injury to a star, a stunning off-field loss to the roster).\n"
    "NEVER assign a negative delta for a normal game LOSS — game results already move the Pulse "
    "elsewhere; delta is for roster/off-field program news only. Be strict and default to 0.\n"
    "Reply as compact JSON on ONE line: "
    "{{\"note\": \"<one factual sentence, max 18 words, or NONE>\", \"delta\": <integer -2..2>}}"
)


def die(msg: str) -> None:
    print(f"\n[X] {msg}")
    sys.exit(1)


def parse_note(raw: str):
    """Return (note, delta). Tolerant of stray prose around the JSON."""
    raw = (raw or "").strip()
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if m:
        try:
            obj = json.loads(m.group(0))
            note = str(obj.get("note", "")).strip()
            try:
                delta = int(obj.get("delta", 0))
            except (ValueError, TypeError):
                delta = 0
            return note, max(-2, min(2, delta))  # clamp AI to the small-nudge range
        except (ValueError, TypeError):
            pass
    # Fallback: treat the whole reply as the note, no Pulse move.
    return raw, 0


def seed_curated(sb, today: str) -> None:
    """Upsert hand-curated Pulse events (curated_notes.json) as note rows with an
    exact signed delta and id `sport|date|c`, so they live alongside the AI daily
    note (id `sport|date`) without colliding. Idempotent — safe every run, and a DB
    rebuild restores them. Remove an entry from the JSON to reverse it (e.g. if a
    player who was 'likely gone' returns)."""
    path = os.path.join(os.path.dirname(__file__), "curated_notes.json")
    try:
        with open(path, encoding="utf-8") as f:
            events = json.load(f)
    except (OSError, ValueError):
        return
    n = 0
    for e in events:
        sport, d = e.get("sport_id"), e.get("date")
        if sport not in SPORT_NAME or not d:
            continue
        delta = int(e.get("delta", 0))
        sb.table("daily_sport_notes").upsert(
            {"id": f"{sport}|{d}|c", "sport_id": sport, "date": d,
             "note": e.get("note", ""), "hype": delta > 0, "pulse_delta": delta},
            on_conflict="id").execute()
        n += 1
    print(f"  curated events seeded: {n}")


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
        note, delta = parse_note(raw)
        if not note or note.upper().startswith("NONE"):
            sb.table("daily_sport_notes").delete().eq("id", f"{sport}|{today}").execute()
            print(f"  {SPORT_NAME[sport]}: (nothing relevant)")
            continue
        sb.table("daily_sport_notes").upsert(
            {"id": f"{sport}|{today}", "sport_id": sport, "date": today, "note": note,
             "hype": delta > 0, "pulse_delta": delta},
            on_conflict="id").execute()
        tag = f"[{'+' if delta > 0 else ''}{delta}] " if delta else ""
        print(f"  {SPORT_NAME[sport]}: {tag}{note}")

    seed_curated(sb, today)
    print("\n[OK] Per-sport notes synced.")


if __name__ == "__main__":
    main()
