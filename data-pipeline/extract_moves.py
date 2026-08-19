"""
Mountaineer Pulse - Automatic roster-move extraction from news
=============================================================
The whole point of the app is that a roster addition shows up EVERYWHERE — briefing,
movement, roster, depth, Pulse. Until now only the AI daily *note* was automatic; the
actual roster_moves rows came from hand-editing roster_moves.json. So the app could say
"WVU adds JUCO linebacker Destin Achi" in the Pulse note while Movement showed nothing.

This closes that gap: Claude reads the last ~48h of stored headlines and returns a typed
list of roster events, which are written to roster_moves as `auto-` rows.

Two rules keep it honest, because a wrong roster move is worse than a missing one:

  1. CURATED ALWAYS WINS. If roster_moves.json already covers a player (any direction),
     the auto row is skipped and any existing auto row for them is deleted. Your manual
     corrections are never overwritten by the model.
  2. REPORTED != CONFIRMED. A story that says "is set to join" / "reportedly" is written
     with status='reported', a visible alert, and pulse_neutral=True — it shows on the
     Movement page flagged, but does NOT move the Pulse score until it's official.

Grounded strictly in the stored headlines (no web search), so it can't invent a player.

Env: SUPABASE_URL, SUPABASE_SECRET_KEY, ANTHROPIC_API_KEY.
Run:  python extract_moves.py        (add --dry-run to print without writing)
"""

import hashlib
import json
import os
import sys
import unicodedata
from datetime import date, datetime, timedelta, timezone

from dotenv import load_dotenv
from supabase import create_client
import usage

load_dotenv()

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

SB_URL = os.getenv("SUPABASE_URL")
SB_KEY = os.getenv("SUPABASE_SECRET_KEY")
ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY")

MODEL = "claude-opus-5"
LOOKBACK_HOURS = 48
SPORTS = ("football", "mbb", "baseball")

SYSTEM = """You extract WVU (West Virginia University) ROSTER MOVES from news headlines.

A roster move is a player JOINING or LEAVING a current WVU team: a transfer in or out, a
JUCO or high-school signee reporting for the upcoming season, a portal entry, a player
removed from the roster, a departure, or a signee who signs pro instead of enrolling.

Extract ONLY what the headlines state. Never add a player, position, school, or claim from
your own knowledge. If the headlines do not name a specific player, extract nothing.

A MOVE IS AN EVENT THAT JUST HAPPENED. The headline must report the move itself. Fall camp
produces a flood of profile and retrospective pieces about players who are ALREADY on the
team, and those are NOT moves no matter how much they sound like arrivals:
  "How X's different stops prepared him for WVU"        -> NOT a move (profile)
  "What X learned from being tested in the Big Ten"     -> NOT a move (profile)
  "What X's walk-on path taught him before arriving"    -> NOT a move (profile)
  "Freshman RB X is who the coach thought he was"       -> NOT a move (analysis)
  "X's dismissal from [other school] brings his WVU
   departure back into focus"                           -> NOT a move (he left long ago)
Phrases like "arriving at", "his path to", "before he got to", "prepared him for" describe
a journey already completed. Extract only on event verbs reporting something NEW: signs,
commits, transfers to/from, joins, enrolls, enters the portal, leaves, is dismissed,
is removed from the roster, announces his return.

You are given the CURRENT ROSTER below. Use it:
- A player already on that roster is NOT arriving. Do not extract an "in" for him unless the
  headline reports a brand-new move that happened now.
- A player NOT on that roster has already left or never joined, so he cannot depart. Do not
  extract an "out" for him.

DO NOT extract:
- Former players / alumni, or anything about their pro careers.
- Eligibility lawsuits, waivers, or court cases — those are status news, not roster moves,
  UNLESS the headline states the player has actually joined or left the roster.
- Injuries, suspensions, depth-chart changes, or position switches.
- Recruits for a FUTURE class (2027 and later). This app tracks the current program only.
- Coaches and staff.
- A player merely being "linked to", "targeting", "interested in", or "visiting" WVU.

status:
  "confirmed" — the headline states the move as fact ("signs with", "joins", "removed from
                roster", "enters portal", "transfers to").
  "reported"  — hedged or not yet official ("set to add", "reportedly", "expected to",
                "plans to", "per sources", "talks late addition").
  When in doubt between the two, choose "reported".

confidence: "high" if the headline plainly names the player and the move; "medium" if it is
implied but clear; "low" if you are guessing. Low-confidence rows are discarded, so prefer
"low" over inventing certainty.

evidence: quote the headline you took it from, verbatim. Do not paraphrase.

Leave position or other_school as an empty string when the headlines don't state them."""

MOVE_SCHEMA = {
    "type": "object",
    "properties": {
        "moves": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "player_name": {"type": "string"},
                    "sport_id": {"type": "string", "enum": list(SPORTS)},
                    "direction": {"type": "string", "enum": ["in", "out"]},
                    "category": {
                        "type": "string",
                        "enum": ["transfer", "juco", "signing", "portal", "departure", "draft", "other"],
                    },
                    "status": {"type": "string", "enum": ["confirmed", "reported"]},
                    "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                    "position": {"type": "string"},
                    "other_school": {"type": "string"},
                    "evidence": {"type": "string"},
                },
                "required": ["player_name", "sport_id", "direction", "category", "status",
                             "confidence", "position", "other_school", "evidence"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["moves"],
    "additionalProperties": False,
}


def die(msg: str) -> None:
    print(f"\n[X] {msg}")
    sys.exit(1)


def norm_name(name: str) -> str:
    """Same normalization sync_moves.py uses, so curated and auto rows dedupe against
    each other even when one spells a name with a period, hyphen, or accent."""
    s = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode()
    return " ".join(s.lower().replace(".", " ").replace("'", "").replace("-", " ").split())


def curated_keys() -> set[tuple[str, str]]:
    """(sport, normalized name) for every hand-curated move that automation must NOT touch.

    Rows flagged `"provisional": true` are deliberately EXCLUDED, so news can supersede them.
    Without that escape hatch, hand-entering a player froze him out of automation forever:
    Brenen Lorient sat in this file as an 'out' with the note "eligibility case unresolved",
    so when he was reported returning on 2026-08-12, every future extraction skipped him for
    being curated. A provisional row says "this is my best guess pending news" — exactly the
    case automation should be allowed to resolve. Confirmed rows stay untouchable.
    """
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "roster_moves.json")
    try:
        with open(path, encoding="utf-8") as f:
            moves = json.load(f)
    except (OSError, ValueError):
        return set()
    return {(m.get("sport_id"), norm_name(m.get("player_name", ""))) for m in moves
            if m.get("player_name") and not m.get("provisional", False)}


def roster_index(sb) -> dict[str, set[str]]:
    """{sport_id: {normalized names currently on the scraped roster}}. This is the ground
    truth the extractor was missing: without it a profile piece about a four-year starter
    reads exactly like a transfer announcement."""
    idx: dict[str, set[str]] = {s: set() for s in SPORTS}
    rows = sb.table("players").select("first_name,last_name,sport_id").execute().data or []
    for r in rows:
        sid = r.get("sport_id")
        if sid in idx:
            n = norm_name(f"{r.get('first_name') or ''} {r.get('last_name') or ''}")
            if n:
                idx[sid].add(n)
    return idx


def roster_block(idx: dict[str, set[str]], sb) -> str:
    """The rosters, formatted for the prompt. Names only — position and class add tokens
    without helping the one judgment being made (is this person already here?)."""
    rows = sb.table("players").select("first_name,last_name,sport_id").execute().data or []
    by_sport: dict[str, list[str]] = {s: [] for s in SPORTS}
    for r in rows:
        sid = r.get("sport_id")
        if sid in by_sport:
            full = f"{r.get('first_name') or ''} {r.get('last_name') or ''}".strip()
            if full:
                by_sport[sid].append(full)
    parts = ["\n\nCURRENT ROSTERS (already on the team — see the rules above):"]
    for s in SPORTS:
        names = sorted(by_sport[s])
        parts.append(f"\n[{s}] {', '.join(names) if names else '(none loaded)'}")
    return "".join(parts)


def extract(sb, headlines: list[str], today: str) -> list[dict]:
    import anthropic

    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    listing = "\n".join(f"- {h}" for h in headlines)
    resp = client.messages.create(
        model=MODEL,
        max_tokens=8000,  # thinking is on by default on Opus 5 and shares this budget
        system=SYSTEM,
        output_config={
            "effort": "medium",
            "format": {"type": "json_schema", "schema": MOVE_SCHEMA},
        },
        messages=[{"role": "user", "content":
                   f"Today is {today}. WVU headlines from the last {LOOKBACK_HOURS} hours:\n\n"
                   f"{listing}{roster_block(roster_index(sb), sb)}\n\nExtract the roster moves."}],
    )
    usage.log(sb, "extract_moves", MODEL, resp)
    if resp.stop_reason == "refusal":
        die("Model declined the extraction request.")
    raw = "".join(b.text for b in resp.content if b.type == "text")
    try:
        return json.loads(raw).get("moves", [])
    except ValueError:
        die(f"Could not parse model output: {raw[:200]}")
    return []


def main() -> None:
    dry = "--dry-run" in sys.argv
    if not SB_URL or not SB_KEY:
        die("Missing SUPABASE_URL or SUPABASE_SECRET_KEY")
    if not ANTHROPIC_KEY:
        die("No ANTHROPIC_API_KEY")

    sb = create_client(SB_URL, SB_KEY)
    today = date.today().isoformat()

    cutoff = (datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)).isoformat()
    news = (sb.table("news_items").select("headline,published_at")
            .gte("published_at", cutoff).order("published_at", desc=True)
            .limit(80).execute().data or [])
    headlines = [n["headline"] for n in news if n.get("headline")]
    if not headlines:
        print("No recent headlines — nothing to extract.")
        return
    print(f"Reading {len(headlines)} headlines from the last {LOOKBACK_HOURS}h...")

    moves = extract(sb, headlines, today)
    if not moves:
        print("No roster moves found in the news. (This is normal on a quiet day.)")

    curated = curated_keys()
    roster = roster_index(sb)
    rows, skipped = [], []
    for m in moves:
        name = (m.get("player_name") or "").strip()
        if not name or m.get("confidence") == "low":
            skipped.append(f"{name or '?'} (low confidence)")
            continue
        key = (m.get("sport_id"), norm_name(name))
        if key in curated:
            skipped.append(f"{name} (already curated by hand)")
            continue

        # Roster reality check, enforced in code because the prompt rule above is not
        # reliably obeyed — the same reason sync_sport_notes clamps departures itself.
        # Fall camp broke this loudly on 2026-08-19: profile pieces ("How X's stops
        # prepared him for WVU") produced four bogus transfers-in for players who had
        # been on the team for years, and a story about Cam Vaughn being dismissed by
        # MIAMI became a fresh WVU departure.
        on_roster = norm_name(name) in roster.get(m.get("sport_id"), set())
        if m["direction"] == "out" and not on_roster:
            # Can't leave a team you're not on. This is the Chambers/Vaughn case: an
            # ex-player's news is not this year's roster losing anything.
            skipped.append(f"{name} (out, but not on the current roster)")
            continue
        if m["direction"] == "in" and on_roster:
            # Already on the roster, so the app already shows him. An auto row here adds
            # nothing and is nearly always a profile piece misread as an arrival. The
            # tradeoff: a real transfer who enrolls fast enough to appear on the scrape
            # before the news lands loses his Movement entry — acceptable, since the
            # whole point of auto-extraction is surfacing people the roster hasn't got yet.
            skipped.append(f"{name} (in, but already on the current roster)")
            continue

        reported = m.get("status") == "reported"
        uid = "auto-" + hashlib.md5(
            f"{m['sport_id']}|{name}|{m['direction']}".encode()).hexdigest()
        rows.append({
            "id": uid,
            "sport_id": m["sport_id"],
            "player_name": name,
            "position": (m.get("position") or "").strip() or None,
            "direction": m["direction"],
            "category": m.get("category") or "transfer",
            "status": m.get("status"),
            "other_school": (m.get("other_school") or "").strip() or None,
            "move_date": today,
            "source_name": "Auto-detected from news",
            "notes": (m.get("evidence") or "").strip() or None,
            # A report isn't a fact yet: show it, flag it, but keep it out of the Pulse
            # math until a later run sees it confirmed (or you curate it by hand).
            "alert": "Reported — not yet official" if reported else None,
            "pulse_neutral": reported,
        })

    print(f"\n{len(rows)} auto move(s) to write:")
    for r in rows:
        flag = "  [REPORTED]" if r["pulse_neutral"] else ""
        pos = f" {r['position']}" if r["position"] else ""
        print(f"  {r['direction'].upper():<3} {r['player_name']}{pos} ({r['sport_id']}){flag}")
        print(f"      {r['notes']}")
    for s in skipped:
        print(f"  (skipped) {s}")

    if dry:
        print("\n[dry run] Nothing written.")
        return

    # Rebuild the auto set so a move that drops out of the news window (or that you've
    # since curated by hand) disappears instead of lingering forever.
    sb.table("roster_moves").delete().like("id", "auto-%").execute()
    if rows:
        sb.table("roster_moves").upsert(rows).execute()
    print(f"\n[OK] roster_moves -> {len(rows)} auto row(s) synced.")


if __name__ == "__main__":
    main()
