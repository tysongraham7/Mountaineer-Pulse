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
    "as discussion but NEVER stated as fact — prefer confirmed news. Hedged wording is a reason "
    "to ATTRIBUTE it ('reportedly set to add X'), not a reason to omit it.\n"
    "5. NONE means 'this sport had no qualifying WVU headline at all today'. It is not a quality "
    "bar. If ANY headline qualifies under rules 2-3, write a note about the most notable one with "
    "delta 0 — a routine day still deserves a line. Only return NONE when there is genuinely "
    "nothing about this sport's current program to say.\n"
    "6. PLAUSIBILITY & SEASON CHECK (today's date is given below): ignore any headline that is "
    "implausible for the current calendar or clearly garbled/clickbait. WVU seasons: football "
    "~Aug–Jan, men's basketball ~Nov–Apr, baseball ~Feb–Jun. A headline implying a game, a matchup "
    "'Saturday', or a past 'win/loss/blowout' when THIS sport is out of season is nonsense — OMIT it. "
    "(Offseason SCHEDULING news is fine — 'in talks to play', 'will play X on [a future date]' — but a "
    "past-tense RESULT or an imminent game that cannot be happening now is not.) If a headline reads as "
    "nonsensical, self-contradictory, or too-good-to-be-true clickbait, OMIT it rather than repeat it.\n"
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
    "A DEPARTURE ONLY COUNTS IF THE PLAYER IS ON THE CURRENT ROSTER, which you are given below. "
    "If someone entering the portal, transferring out, or leaving is NOT on that roster, he already "
    "left or his eligibility already ended — this year's team loses nothing it had, so delta is 0. "
    "Word it so a reader can tell he wasn't on this year's team ('former corner', 'ex-Mountaineer'), "
    "never 'WVU loses'. In particular, when a ruling makes an ex-player eligible again and he then "
    "goes elsewhere, the roster is exactly where it started: delta 0, never negative.\n"
    "IF THE HEADLINE DOES NOT NAME THE PLAYER ('a starting cornerback', 'a veteran lineman'), you "
    "cannot check him against the roster, so you MUST NOT give it a negative delta — use 0. A title "
    "like 'starting cornerback' is the writer's shorthand and often means LAST season's starter, who "
    "may not be on this year's team at all. Never infer a current roster spot from a job title.\n"
    "UNCONFIRMED NEWS IS ALWAYS delta 0. If the source hedges ('set to add', 'reportedly', "
    "'expected to', 'per sources'), the event has not happened yet — word the note with the hedge "
    "intact ('reportedly set to add X', not 'adds X') and give it delta 0. Score it later, once a "
    "headline confirms it. Announcing an unconfirmed move as fact is the worst error you can make.\n"
    "7. NO REPEATS — this is critical: you are shown 'ALREADY REPORTED' notes from recent days. If "
    "today's biggest item is the SAME event you already reported (e.g. a signing/draft/commitment you "
    "noted days ago, just re-worded by another outlet), do NOT report it again and do NOT apply another "
    "delta — its Pulse hit was already counted. Only write a note for a genuinely NEW development. If a "
    "prior note was a POSSIBILITY ('drafted, awaiting decision') and today it's CONFIRMED ('signed'), "
    "that IS new — report the confirmation, but with a SMALL delta (±1), since the possibility was "
    "already partly priced in. If today's BIGGEST item is a repeat, do not return NONE — move down "
    "to the next qualifying headline and write that with delta 0. NONE is only for a day with no "
    "qualifying headline at all (see rule 5).\n"
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


def recent_notes(sb, sport: str, today: str, days: int = 7) -> str:
    """The last week's notes for this sport, so the model leads with what's NEW instead of
    re-reporting (and re-penalizing) a story it already covered. Without this memory the daily
    note re-wrote the same signing for days, stacking a fresh delta each time."""
    since = (date.fromisoformat(today) - timedelta(days=days)).isoformat()
    rows = (sb.table("daily_sport_notes").select("date,note")
            .eq("sport_id", sport).gte("date", since).lt("date", today)
            .order("date", desc=True).execute().data or [])
    rows = [r for r in rows if (r.get("note") or "").strip()]
    if not rows:
        return ""
    lines = "\n".join(f"- [{r['date']}] {r['note']}" for r in rows)
    return f"\nALREADY REPORTED (recent notes — do NOT repeat these or re-apply their delta):\n{lines}"


# Phrases that mean "a player is leaving the program". Deliberately excludes decommits
# and flips: a recruit was never on the roster, so that check doesn't apply to them.
DEPARTURE_WORDS = (
    "transfer portal", "enter the portal", "enters the portal", "entering the portal",
    "transferring", "transfers out", "transfer out", "leaving the program",
    "departs", "departing", "exits the program",
)


def clamp_unverified_departure(note: str, delta: int, roster: list[str]) -> tuple[int, str | None]:
    """Refuse a negative Pulse hit for a departure we can't tie to someone on the roster.

    Headlines write "WVU Starting Cornerback to Enter Transfer Portal" without a name, and
    that job title usually means LAST season's starter. Jason Chambers was the 2025 starter
    whose eligibility had ended; he was never on the 2026 roster, so his leaving cost this
    team nothing -- but the phrasing reads exactly like losing a starter, and the model kept
    scoring it -1 no matter how the instruction was worded. Prompt rules the model ignores
    are worth enforcing in code.
    """
    if delta >= 0:
        return delta, None
    low = note.lower()
    if not any(w in low for w in DEPARTURE_WORDS):
        return delta, None
    if any(n.lower() in low for n in roster if n):
        return delta, None       # a real current player -- the hit stands
    return 0, "departure doesn't name anyone on the current roster"


def roster_names(sb, sport: str) -> list[str]:
    rows = (sb.table("players").select("first_name,last_name")
            .eq("sport_id", sport).execute().data or [])
    return sorted(
        n for n in (f"{r.get('first_name') or ''} {r.get('last_name') or ''}".strip() for r in rows) if n
    )


def roster_block(names: list[str]) -> str:
    """The current roster, so 'X enters the portal' can be checked against who's on the team."""
    if not names:
        return ""
    return ("\nCURRENT ROSTER (anyone NOT on this list has already left the program — "
            f"their departure is delta 0):\n{', '.join(names)}\n")


def seed_curated(sb, today: str) -> set[str]:
    """Upsert hand-curated Pulse events (curated_notes.json) as note rows with an
    exact signed delta and id `sport|date|c`, so they live alongside the AI daily
    note (id `sport|date`) without colliding. Idempotent — safe every run, and a DB
    rebuild restores them. Remove an entry from the JSON to reverse it (e.g. if a
    player who was 'likely gone' returns).

    Returns the sports curated for TODAY, so the AI note can stand down for them:
    the app shows one note per day and picks arbitrarily between two rows with the
    same date, so leaving both would make the displayed wording a coin flip."""
    path = os.path.join(os.path.dirname(__file__), "curated_notes.json")
    try:
        with open(path, encoding="utf-8") as f:
            events = json.load(f)
    except (OSError, ValueError):
        return set()
    n = 0
    curated_today: set[str] = set()
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
        if d == today:
            curated_today.add(sport)
    print(f"  curated events seeded: {n}")
    return curated_today


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

    # Seed curated events FIRST, so the daily-note memory (recent_notes) already includes any
    # hand-set event and the AI won't re-report the same story with a second delta.
    curated_today = seed_curated(sb, today)

    print("Per-sport notes:")
    for sport in ("football", "mbb", "baseball"):
        # A hand-written note for today is the final word on that day — drop any AI note
        # for the same date rather than let the app pick between them at random.
        if sport in curated_today:
            sb.table("daily_sport_notes").delete().eq("id", f"{sport}|{today}").execute()
            print(f"  {SPORT_NAME[sport]}: curated note owns today — AI note skipped")
            continue
        # This sport's own headlines first, then the day's general WVU headlines
        # (the model keeps only the ones clearly about this sport).
        own = by_sport.get(sport, [])
        candidates = own + [h for h in general if h not in own]
        if not candidates:
            sb.table("daily_sport_notes").delete().eq("id", f"{sport}|{today}").execute()
            print(f"  {SPORT_NAME[sport]}: (no news today)")
            continue

        headlines = "\n".join(f"- {h}" for h in candidates[:18])
        already = recent_notes(sb, sport, today)
        names = roster_names(sb, sport)
        roster = roster_block(names)
        resp = client.messages.create(
            model="claude-haiku-4-5", max_tokens=120,
            system=NOTE_SYSTEM.format(sport=SPORT_NAME[sport]),
            messages=[{"role": "user", "content":
                       f"Today is {today}. WVU headlines (some may not be about {SPORT_NAME[sport]}):\n"
                       f"{headlines}\n{already}\n{roster}\n"
                       f"Write the JSON note for WVU {SPORT_NAME[sport]}."}],
        )
        raw = "".join(b.text for b in resp.content if b.type == "text")
        note, delta = parse_note(raw)
        delta, clamped = clamp_unverified_departure(note, delta, names)
        if clamped:
            print(f"  {SPORT_NAME[sport]}: delta forced to 0 — {clamped}")
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

    print("\n[OK] Per-sport notes synced.")


if __name__ == "__main__":
    main()
