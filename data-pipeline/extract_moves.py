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
                   f"{listing}\n\nExtract the roster moves."}],
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
