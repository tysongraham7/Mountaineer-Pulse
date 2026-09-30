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

Grounded in the stored headlines and the summaries notify_news researched for pushed stories.
A headline that reports a move without naming anyone gets one web search, and the name
is only kept if it appears in a search result (see resolve_unnamed).

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
RESOLVE_MODEL = "claude-sonnet-5"
WEB_SEARCH_TOOL = {"type": "web_search_20260209", "name": "web_search", "max_uses": 2}
# Unnamed headlines resolved per run. Each costs a search call; a busy news day repeats
# the same teaser across outlets, and anything past this waits for the next run.
MAX_RESOLVE = 3
SPORTS = ("football", "mbb", "baseball")

SYSTEM = """You extract WVU (West Virginia University) ROSTER MOVES from news headlines.

A roster move is a player JOINING or LEAVING a current WVU team: a transfer in or out, a
JUCO or high-school signee reporting for the upcoming season, a portal entry, a player
removed from the roster, a departure, a signee who signs pro instead of enrolling, or a
player CLEARED TO PLAY by an eligibility ruling (a court grants an injunction or a fifth
year, the NCAA approves a waiver).

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
  headline reports a brand-new move that happened now. The exception is an eligibility ruling:
  a player on the roster who has just been cleared to play IS extracted, category "eligibility".
- A player NOT on that roster has already left or never joined, so he cannot depart. Do not
  extract an "out" for him.

DO NOT extract:
- Former players / alumni, or anything about their pro careers.
- Eligibility cases that have not been decided: a lawsuit filed, a hearing scheduled, a ruling
  awaited, an appeal. Only a decision that clears (or finally ends) a named player's
  eligibility is a move.
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

category "eligibility": a named player cleared to play by a ruling or waiver (direction "in"),
or whose eligibility a ruling has ended so he is done at WVU (direction "out"). One ruling can
clear several players — extract each one named. If the player is a newcomer from another
school ("former Georgia safety X cleared to play for WVU"), put that school in other_school.

Leave position or other_school as an empty string when the headlines don't state them.

RESEARCHED SUMMARIES, when given, are our own write-ups of stories we pushed to fans, made from
the full articles. They often name the players a headline left out ("four WVU athletes" ->
the four names). Treat them as a source just like the headlines; quote the summary sentence
as evidence.

unnamed: headlines that clearly report a WVU roster move by the rules above but never name the
player anywhere in the headlines or summaries ("WVU lands ex-Utah RB in transfer portal").
Copy each such headline verbatim. Do not list a headline whose player you extracted."""

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
                        "enum": ["transfer", "juco", "signing", "portal", "departure", "draft",
                                 "eligibility", "other"],
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
        },
        "unnamed": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["moves", "unnamed"],
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


def extract(sb, headlines: list[str], summaries: list[str], today: str) -> tuple[list[dict], list[str]]:
    import anthropic

    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    listing = "\n".join(f"- {h}" for h in headlines)
    researched = ""
    if summaries:
        researched = ("\n\nRESEARCHED SUMMARIES of stories we pushed:\n"
                      + "\n".join(f"- {s}" for s in summaries))
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
                   f"{listing}{researched}{roster_block(roster_index(sb), sb)}\n\n"
                   "Extract the roster moves."}],
    )
    usage.log(sb, "extract_moves", MODEL, resp)
    if resp.stop_reason == "refusal":
        die("Model declined the extraction request.")
    raw = "".join(b.text for b in resp.content if b.type == "text")
    try:
        obj = json.loads(raw)
    except ValueError:
        die(f"Could not parse model output: {raw[:200]}")
        return [], []
    return obj.get("moves", []), obj.get("unnamed", [])


RESOLVE_SYSTEM = """A WVU sports headline reports a roster move but does not name the player.
Search the web to find out who it is. Answer with ONLY this JSON:

{"player_name": "", "sport_id": "football|mbb|baseball", "direction": "in|out",
 "position": "", "other_school": "", "status": "confirmed|reported", "source_url": ""}

player_name must be printed in a search result you found, and source_url must be that result.
If the searches don't settle who it is, return {"player_name": ""}. A wrong name is far worse
than none: this goes straight onto a roster fans read."""


def resolve_unnamed(sb, headline: str, today: str) -> dict | None:
    """Put a name to a headline that withheld it ("WVU lands ex-Utah RB in transfer portal").

    NaQuari Rogers joined on 2026-09-24 and every headline about it said "ex-Utah RB", so the
    extractor, which must not guess, had nothing to write and he never reached Movement. Web
    search can answer the question the headline dodged, but a name is only accepted when it
    appears in a result title or URL we can see; the model's say-so is not enough."""
    import anthropic

    from generate_briefing import extract_json

    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    kwargs = dict(
        model=RESOLVE_MODEL,
        max_tokens=1200,
        system=RESOLVE_SYSTEM,
        messages=[{"role": "user", "content": f'Today is {today}.\n\nHeadline: "{headline}"'}],
        tools=[WEB_SEARCH_TOOL],
    )
    # Same bounded two-call shape as notify_news.summarize(): one call that may search, then
    # at most one tool-free call to write the JSON. Never an open-ended pause_turn loop.
    try:
        resp = client.messages.create(**kwargs)
        blocks = list(resp.content)
        searches = getattr(getattr(resp.usage, "server_tool_use", None), "web_search_requests", 0) or 0
        usage.log_raw(sb, "extract_moves.resolve", RESOLVE_MODEL, resp.usage, searches)
        if resp.stop_reason == "pause_turn":
            follow = {k: v for k, v in kwargs.items() if k != "tools"}
            follow["messages"] = list(kwargs["messages"]) + [
                {"role": "assistant", "content": resp.content}]
            resp2 = client.messages.create(**follow)
            blocks += list(resp2.content)
            usage.log_raw(sb, "extract_moves.resolve", RESOLVE_MODEL, resp2.usage, 0)
    except Exception as e:
        print(f"  (could not resolve '{headline[:60]}': {str(e)[:120]})")
        return None

    seen = []  # every result title and URL the searches actually returned
    for b in blocks:
        if getattr(b, "type", "") == "web_search_tool_result" and isinstance(b.content, list):
            for item in b.content:
                seen.append(f"{getattr(item, 'title', '')} {getattr(item, 'url', '')}")
    haystack = norm_name(" ".join(seen).replace("/", " "))
    text = "".join(b.text for b in blocks if getattr(b, "type", "") == "text")
    obj = extract_json(text) or {}
    name = (obj.get("player_name") or "").strip()
    if not name:
        return None
    if norm_name(name) not in haystack:
        print(f"  (dropped '{name}' for '{headline[:60]}': not in any search result)")
        return None
    if obj.get("sport_id") not in SPORTS or obj.get("direction") not in ("in", "out"):
        return None
    return {
        "player_name": name,
        "sport_id": obj["sport_id"],
        "direction": obj["direction"],
        "category": "transfer",
        "status": "confirmed" if obj.get("status") == "confirmed" else "reported",
        "confidence": "high",
        "position": (obj.get("position") or "").strip(),
        "other_school": (obj.get("other_school") or "").strip(),
        "evidence": headline,
        "source_url": (obj.get("source_url") or "").strip(),
    }


def main() -> None:
    dry = "--dry-run" in sys.argv
    if not SB_URL or not SB_KEY:
        die("Missing SUPABASE_URL or SUPABASE_SECRET_KEY")
    if not ANTHROPIC_KEY:
        die("No ANTHROPIC_API_KEY")

    sb = create_client(SB_URL, SB_KEY)
    today = date.today().isoformat()

    cutoff = (datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)).isoformat()
    news = (sb.table("news_items").select("headline,published_at,summary")
            .gte("published_at", cutoff).order("published_at", desc=True)
            .limit(80).execute().data or [])
    headlines = [n["headline"] for n in news if n.get("headline")]
    # The write-ups notify_news researched for pushed stories. On 2026-09-30 the pushed
    # headline was "Four Mountaineers granted a fifth year of eligibility"; its summary named
    # all four. Without it, only the players who got a headline of their own could be found.
    summaries = [n["summary"] for n in news if n.get("summary")]
    if not headlines:
        print("No recent headlines — nothing to extract.")
        return
    print(f"Reading {len(headlines)} headlines and {len(summaries)} researched summaries "
          f"from the last {LOOKBACK_HOURS}h...")

    moves, unnamed = extract(sb, headlines, summaries, today)

    existing = {r["id"]: r for r in (sb.table("roster_moves")
                                     .select("id,sport_id,player_name,status,move_date,notes")
                                     .like("id", "auto-%").execute().data or [])}
    # Name the players the headlines withheld. Skip a headline an earlier run already turned
    # into a row, so each teaser costs one search, not one per run while it stays in window.
    handled = [(r.get("notes") or "") for r in existing.values()]
    for h in unnamed[:MAX_RESOLVE]:
        if any(h in n for n in handled):
            continue
        print(f"  resolving unnamed: {h}")
        hit = resolve_unnamed(sb, h, today)
        if hit:
            print(f"    -> {hit['player_name']} ({hit['source_url']})")
            moves.append(hit)

    if not moves:
        print("No roster moves found in the news. (This is normal on a quiet day.)")

    curated = curated_keys()
    roster = roster_index(sb)
    rows, skipped, taken = [], [], set()
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
        eligibility = m.get("category") == "eligibility"
        if m["direction"] == "out" and not on_roster:
            # Can't leave a team you're not on. This is the Chambers/Vaughn case: an
            # ex-player's news is not this year's roster losing anything.
            skipped.append(f"{name} (out, but not on the current roster)")
            continue
        if m["direction"] == "in" and on_roster and not eligibility:
            # Already on the roster, so the app already shows him. An auto row here adds
            # nothing and is nearly always a profile piece misread as an arrival. An
            # eligibility ruling is the exception: the player IS listed, and the news is that
            # he can now play. The four players cleared on 2026-09-30 were all on the roster,
            # and this check alone would have kept every one of them off Movement.
            skipped.append(f"{name} (in, but already on the current roster)")
            continue

        category = m.get("category") or "transfer"
        if eligibility and m["direction"] == "in" and (m.get("other_school") or "").strip():
            # Cleared to play AND from another school = a newcomer (JaCorey Thomas, Georgia).
            # The app files 'eligibility' under returners with no previous school, so he'd
            # read as a player who was already here.
            category = "transfer"

        uid = "auto-" + hashlib.md5(
            f"{m['sport_id']}|{name}|{m['direction']}".encode()).hexdigest()
        if uid in taken:
            continue  # one ruling often makes several headlines about the same player
        taken.add(uid)
        prior = existing.get(uid) or {}
        # A later hedged headline never un-confirms a move an earlier run saw confirmed.
        reported = m.get("status") == "reported" and prior.get("status") != "confirmed"
        rows.append({
            "id": uid,
            "sport_id": m["sport_id"],
            "player_name": name,
            "position": (m.get("position") or "").strip() or None,
            "direction": m["direction"],
            "category": category,
            "status": "reported" if reported else "confirmed",
            "other_school": (m.get("other_school") or "").strip() or None,
            # The day we first saw it, kept across runs: the briefing's freshness rule and the
            # Pulse's move window both read this, and restamping it every run made old news new.
            "move_date": prior.get("move_date") or today,
            "source_name": "Auto-detected from news",
            "source_url": m.get("source_url") or None,
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
        print(f"  {r['direction'].upper():<3} {r['player_name']}{pos} "
              f"({r['sport_id']}, {r['category']}){flag}")
        print(f"      {r['notes']}")
    for s in skipped:
        print(f"  (skipped) {s}")

    # Auto rows a hand-curated entry now covers. Curated always wins.
    superseded = [i for i, r in existing.items()
                  if (r.get("sport_id"), norm_name(r.get("player_name") or "")) in curated]

    if dry:
        print(f"\n[dry run] Nothing written. ({len(superseded)} auto row(s) would hand over "
              f"to curated entries.)")
        return

    # Auto rows are KEPT between runs. This used to delete every auto row and rebuild from
    # the last 48h of headlines, so a move dropped off Movement, the roster and the briefing
    # two days after it happened; by 2026-09-30 there were none left at all. A row now
    # leaves only when a hand-curated entry takes it over.
    for i in superseded:
        sb.table("roster_moves").delete().eq("id", i).execute()
    if rows:
        sb.table("roster_moves").upsert(rows).execute()
    print(f"\n[OK] roster_moves -> {len(rows)} auto row(s) written, "
          f"{len(superseded)} handed over to curated entries.")


if __name__ == "__main__":
    main()
