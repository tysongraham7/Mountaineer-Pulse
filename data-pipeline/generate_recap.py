"""
Mountaineer Pulse - Post-Game "By the Numbers"
==============================================
The scouting report's other half. Once a football game is final, this writes the handful
of numbers a fan would actually repeat: the 71-yard touchdown run that was the longest by a
WVU quarterback since Pat White, the first 2-0 start since 2018, the 316 rushing yards.
The Summary tab shows them above the scoring plays.

Two rules shape it, same as generate_matchup.py.

THE BOX SCORE IS GIVEN, THE HISTORY IS SEARCHED. Every number in the game comes from ESPN's
summary feed — final score, quarter line, team stats, every player's line, every scoring
play — and is handed to the model as fixed. The feed also carries the AP recap, which is
handed over as a source. What the box score cannot say is what any of it MEANS: "first
since", "longest since", "program record". Those are the interesting part, and the only
honest way to get them is to find them written down — WVU's postgame notes, the beat
writers — so the model has web search for that and is told that a historical claim it
cannot source does not go in.

IT RUNS TWICE PER GAME. Once as soon as the final is in the database, because that is when
fans open the app — the game-day workflow ticks every 30 minutes, so this lands within
half an hour of the final. Then once more after the dust settles (SETTLE_HOURS past
kickoff), because WVU's official postgame notes and the Sunday stories are where the best
"first since" facts live, and most of them are not indexed an hour after the game. Never a
third time: nothing about a finished game changes after that.

Football only for now: it is the one sport whose ESPN summary this pipeline has taken apart
(see mobile/src/lib/game-summary.ts), and the one with a play-by-play worth mining.

Writes to game_recaps (one row per game_id). Needs ANTHROPIC_API_KEY.
Run:  python generate_recap.py [--dry-run] [--force] [--game-id N]
"""

import html
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv
from supabase import create_client

import usage as api_usage
from generate_briefing import _create_resilient, extract_json, strip_tags

load_dotenv()

SB_URL = os.getenv("SUPABASE_URL")
SB_KEY = os.getenv("SUPABASE_SECRET_KEY")
ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY")

MODEL = "claude-sonnet-5"
SEARCH_BUDGET_N = 6
WEB_SEARCH_TOOL = {"type": "web_search_20260209", "name": "web_search", "max_uses": SEARCH_BUDGET_N}

WVU_ID = "277"
ET = ZoneInfo("America/New_York")
SUMMARY = "https://site.api.espn.com/apis/site/v2/sports/football/college-football/summary"
# ESPN 403s browser-impersonating agents; an honest one is allowed. See sync_espn.py.
UA = {"User-Agent": "MountaineerPulse/1.0 (+https://github.com/tysongraham/mountaineer-pulse)"}

# A final older than this is not news, and a recap written for it would be read by nobody.
# Also the window inside which the second pass can still happen.
RECAP_WINDOW_HOURS = 72
# Kickoff plus this is "the dust has settled": the game is long over, the postgame notes
# are up, the Sunday stories are indexed. A recap written before this gets one refresh
# after it.
SETTLE_HOURS = 12

SEARCH_BUDGET = (
    "\n\nSEARCH BUDGET: web search is the cost here. Spend it on CONTEXT the box score "
    "cannot give you — WVU's official postgame notes (wvusports.com), the beat writers "
    "(WV MetroNews, the Dominion Post, WVSports.com, EerSports, the Daily Athenaeum), the AP "
    "story. Good queries name the game and the word 'notes': "
    "'West Virginia UT Martin postgame notes', 'Hawkins 71-yard run longest WVU quarterback'. "
    "Do NOT search for the box score — it is given above. Aim for about 4 searches. Once "
    "you have what you can source, stop searching and write the JSON."
)


def die(msg: str) -> None:
    print(f"\n[X] {msg}")
    sys.exit(1)


# ---------------------------------------------------------------------------
# which game
# ---------------------------------------------------------------------------

def due_games(sb, now: datetime, game_id: int | None, force: bool) -> list[dict]:
    """Every recent football final that still owes a recap pass (or the one asked for)."""
    if game_id:
        rows = sb.table("games").select("*").eq("id", game_id).execute().data
        return rows or []
    cutoff = (now - timedelta(hours=RECAP_WINDOW_HOURS)).isoformat()
    rows = (sb.table("games").select("*")
            .eq("sport_id", "football").eq("status", "final")
            .gte("start_date", cutoff).lte("start_date", now.isoformat())
            .order("start_date").execute().data or [])
    rows = [g for g in rows if g.get("home_points") is not None and g.get("away_points") is not None]
    if force or not rows:
        return rows
    ids = [g["id"] for g in rows]
    have = {r["game_id"]: r for r in
            (sb.table("game_recaps").select("game_id,generated_at").in_("game_id", ids)
             .execute().data or [])}
    due = []
    for g in rows:
        settled_at = datetime.fromisoformat(g["start_date"]) + timedelta(hours=SETTLE_HOURS)
        rec = have.get(g["id"])
        if not rec:
            due.append(g)                                       # first pass
        elif now >= settled_at and datetime.fromisoformat(rec["generated_at"]) < settled_at:
            due.append(g)                                       # second, settled pass
    return due


# ---------------------------------------------------------------------------
# the box score, as text the model can read
# ---------------------------------------------------------------------------

def fetch_summary(event_id: int) -> dict:
    r = requests.get(SUMMARY, params={"event": event_id}, headers=UA, timeout=30)
    r.raise_for_status()
    return r.json()


def _sides(comp: dict) -> tuple[dict, dict]:
    wvu = opp = None
    for c in comp.get("competitors") or []:
        if str((c.get("team") or {}).get("id")) == WVU_ID:
            wvu = c
        else:
            opp = c
    if not wvu or not opp:
        die("ESPN summary has no WVU competitor")
    return wvu, opp


def box_text(summary: dict, game: dict) -> str:
    """Everything that happened, in ~2 KB. Same feed the app's Summary tab parses; the
    shape notes in mobile/src/lib/game-summary.ts apply here too."""
    comp = ((summary.get("header") or {}).get("competitions") or [{}])[0]
    wvu, opp = _sides(comp)
    opp_name = (opp.get("team") or {}).get("displayName") or "Opponent"
    lines: list[str] = []

    def rec(c: dict) -> str:
        for r in c.get("record") or []:
            if r.get("type") == "total":
                return r.get("displayValue") or ""
        return ""

    lines.append(f"FINAL: West Virginia {wvu.get('score')}, {opp_name} {opp.get('score')}")
    lines.append(f"Records after the game: WVU {rec(wvu) or '?'}, {opp_name} {rec(opp) or '?'}")
    wl = [x.get("displayValue") for x in wvu.get("linescores") or []]
    ol = [x.get("displayValue") for x in opp.get("linescores") or []]
    if wl:
        lines.append(f"By quarter: WVU {'-'.join(wl)} | {opp_name} {'-'.join(ol)}")

    # Team stats, side by side.
    teams = (summary.get("boxscore") or {}).get("teams") or []
    stats = {str((t.get("team") or {}).get("id")): {s["name"]: s.get("displayValue")
             for s in t.get("statistics") or []} for t in teams}
    ws = stats.get(WVU_ID, {})
    os_ = next((v for k, v in stats.items() if k != WVU_ID), {})
    if ws or os_:
        lines.append("\nTEAM STATS (WVU | opponent):")
        for k in sorted(set(ws) | set(os_)):
            lines.append(f"- {k}: {ws.get(k, '-')} | {os_.get(k, '-')}")

    # Every player line, both teams. WVU first.
    players = (summary.get("boxscore") or {}).get("players") or []
    players.sort(key=lambda p: str((p.get("team") or {}).get("id")) != WVU_ID)
    for p in players:
        team = (p.get("team") or {}).get("displayName") or "?"
        lines.append(f"\nPLAYER STATS — {team}:")
        for st in p.get("statistics") or []:
            labels = st.get("labels") or []
            rows = [a for a in st.get("athletes") or [] if (a.get("athlete") or {}).get("displayName")]
            if not rows:
                continue
            lines.append(f"  {st.get('name')} [{', '.join(labels)}]")
            for a in rows:
                lines.append(f"    {a['athlete']['displayName']}: {', '.join(str(x) for x in a.get('stats') or [])}")

    plays = summary.get("scoringPlays") or []
    if plays:
        lines.append("\nSCORING PLAYS (score after, home-away):")
        for s in plays:
            q = (s.get("period") or {}).get("number")
            clk = (s.get("clock") or {}).get("displayValue")
            lines.append(f"- Q{q} {clk} {s.get('text')} ({s.get('homeScore')}-{s.get('awayScore')})")

    info = summary.get("gameInfo") or {}
    att = info.get("attendance")
    if att:
        lines.append(f"\nAttendance: {att:,}")
    return "\n".join(lines)


def article_text(summary: dict) -> str:
    """ESPN ships the AP game story inside the summary. It is the one source that exists
    the minute the game ends, so it goes in as-is (HTML stripped) and is cited by name."""
    art = summary.get("article") or {}
    story = art.get("story") or ""
    if not story:
        return ""
    story = re.sub(r"<[^>]+>", "", story)
    story = html.unescape(story)
    story = re.sub(r"[ \t]+", " ", story)
    story = re.sub(r"\n\s*\n+", "\n\n", story).strip()
    head = art.get("headline") or ""
    return f"{head}\n\n{story}"[:6000]


def season_context(sb, game: dict) -> str:
    """WVU's results so far this season, from our own table — the model should not have to
    search for whether this was the fourth straight win."""
    rows = (sb.table("games").select("start_date,home_team,away_team,home_points,away_points,is_wvu_home,status,season_type")
            .eq("sport_id", "football").eq("season", game["season"])
            # Explicit null branch: a bare neq drops nulls (see generate_matchup.next_game).
            .or_("season_type.is.null,season_type.neq.exhibition").eq("status", "final")
            .order("start_date").execute().data or [])
    out = []
    for g in rows:
        if g.get("home_points") is None or g.get("away_points") is None:
            continue
        home = bool(g.get("is_wvu_home"))
        w, o = (g["home_points"], g["away_points"]) if home else (g["away_points"], g["home_points"])
        opp = g["away_team"] if home else g["home_team"]
        res = "W" if w > o else "L" if w < o else "T"
        out.append(f"- {g['start_date'][:10]} {'vs' if home else 'at'} {opp}: {res} {w}-{o}")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# the model
# ---------------------------------------------------------------------------

SYSTEM = (
    "You write the post-game 'By the Numbers' for Mountaineer Pulse, a West Virginia "
    "University sports app. A fan has just watched the game; you hand them the four to "
    "seven numbers worth repeating at work on Monday. Voice: sharp, factual, a plugged-in "
    "fan who has done the homework. Never hype, never a game story — the numbers ARE the story.\n\n"
    "AMERICAN SPELLING throughout — offense, defense, favorite, yards. This is a US college "
    "sports app and British spellings read as foreign.\n\n"
    "ABSOLUTE RULES — one wrong fact loses a fan's trust:\n"
    "1. THE BOX SCORE IS GIVEN TO YOU and is authoritative. Every yard, carry, completion and "
    "score you cite must match the DATA block exactly. Never round, never estimate, never "
    "substitute a number you found online for one in the box score.\n"
    "2. HISTORY MUST BE SOURCED. Any claim of the form 'first since', 'longest since', 'most "
    "since', 'program record', 'career high', 'streak' must come from the AP story in the DATA "
    "block or from a page you found by searching — WVU's official postgame notes, a beat "
    "writer, a wire story. Never from memory. A fact you cannot source does not go in, however "
    "good it sounds. Fewer true notes beat more notes.\n"
    "3. Name the source for every note in its 'source' field ('WVU Athletics postgame notes', "
    "'AP', 'WV MetroNews'). A note straight from the box score with no historical claim may "
    "say 'Box score'.\n"
    "4. WVU is the subject. An opponent fact makes the cut only if it says something about WVU "
    "(e.g. the opponent's first shutout loss since ...).\n"
    "5. No opinion, no 'should', no injuries, no looking ahead to next week.\n\n"
    "WHAT MAKES A NOTE. The best ones pair a number from THIS game with context that makes "
    "it land: a 71-yard run that was the longest by a WVU quarterback since Pat White; a 2-0 "
    "start for the first time since 2018; 316 rushing yards, the most since a named game; a "
    "quarterback who accounted for four touchdowns. A bare box-score line ('Epps had 112 "
    "yards') is filler unless the number is striking on its own (a 56.0-yard average is; 8 "
    "tackles is not). Lead with the note a fan would text a friend.\n\n"
    "OUTPUT — reply with ONLY a JSON object, no prose around it:\n"
    "{\n"
    '  "headline": "<one sentence, the game in a line — the score is shown separately, so '
    "don't repeat it>\",\n"
    '  "notes": [\n'
    '    {"figure": "<the number, as short as it can be: 71, 2-0, 316, 4, 56.0>",\n'
    '     "label": "<at most three words naming what the figure is: yard TD run, start, '
    "rushing yards, total TDs>\",\n"
    '     "body": "<one or two sentences. Who, what, and the context that makes it matter. '
    "Full names on first mention>\",\n"
    '     "source": "<where the context came from>"}\n'
    "  ]\n"
    "}\n"
    "Give 4-7 notes, best first. 'figure' is rendered large, so keep it to a number, a "
    "record like 2-0, or a short count; never a sentence."
)


def to_plaintext(obj: dict) -> str:
    parts = [obj.get("headline", "").strip()]
    for n in obj.get("notes", []):
        parts.append(f"\n• {n.get('figure', '')} {n.get('label', '')}: {n.get('body', '')}")
    return "\n".join(p for p in parts if p and p.strip()).strip()


def clean(obj: dict) -> dict:
    """Strip web-search cite tags everywhere, drop malformed notes, cap the count."""
    out = {"headline": strip_tags(str(obj.get("headline", ""))), "notes": []}
    for n in (obj.get("notes") or [])[:7]:
        if not isinstance(n, dict):
            continue
        figure = strip_tags(str(n.get("figure", ""))).strip()
        label = strip_tags(str(n.get("label", ""))).strip()
        body = strip_tags(str(n.get("body", ""))).strip()
        source = strip_tags(str(n.get("source", ""))).strip()
        # A figure that has turned into a sentence would be rendered at 30pt. Drop the
        # figure and keep the note as prose rather than lose the note.
        if len(figure) > 8:
            figure = ""
        if body:
            out["notes"].append({"figure": figure, "label": label, "body": body, "source": source})
    return out


def generate(sb, client, game: dict, dry: bool) -> None:
    kickoff = game["start_date"]
    home = bool(game.get("is_wvu_home"))
    opp = game["away_team"] if home else game["home_team"]
    wvu_pts, opp_pts = ((game["home_points"], game["away_points"]) if home
                        else (game["away_points"], game["home_points"]))
    where = "vs" if home else "at"
    print(f"Football: WVU {where} {opp} — {kickoff} — final {wvu_pts}-{opp_pts}")
    # Local time, so a 1 p.m. kickoff is not written up as "a night" — it was, once.
    ko_et = datetime.fromisoformat(kickoff).astimezone(ET)
    when = ko_et.strftime("%A, %B %d, %Y at %I:%M %p ET").replace(" 0", " ")

    event_id = game.get("espn_event_id") or game["id"]
    summary = fetch_summary(event_id)
    state = (((summary.get("header") or {}).get("competitions") or [{}])[0].get("status") or {}).get("type", {}).get("state")
    if state != "post":
        print(f"  ESPN says the game is '{state}', not final — skipping.")
        return

    data = (
        f"=== THE GAME ===\n"
        f"- Football, week {game.get('week') or '?'}, {game['season']} {game.get('season_type') or 'regular'} season\n"
        f"- West Virginia {where} {opp}, {when}, {game.get('venue') or 'venue unknown'}\n"
        f"- WVU was {'HOME' if home else 'AWAY'}\n\n"
        f"=== BOX SCORE (authoritative) ===\n{box_text(summary, game)}\n\n"
        f"=== WVU {game['season']} RESULTS SO FAR (from our database, this game included) ===\n"
        f"{season_context(sb, game) or '- none on file'}"
    )
    story = article_text(summary)
    if story:
        data += f"\n\n=== AP GAME STORY (a source; cite as 'AP') ===\n{story}"

    instruction = (
        f"Write the By the Numbers JSON for this game. Today is "
        f"{datetime.now(timezone.utc).date().isoformat()}. The box score above is correct and "
        f"must be used as given; search for the CONTEXT — WVU's postgame notes and the beat "
        f"writers — that turns its numbers into notes."
    ) + SEARCH_BUDGET

    kwargs = dict(
        model=MODEL,
        # Thinking, six searches, the pages they fetch and the answer all draw on this. At
        # 6000 a run stopped mid-JSON and the whole recap was lost.
        max_tokens=12000,
        thinking={"type": "adaptive"},
        system=[{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": [
            {"type": "text", "text": f"DATA:\n{data}", "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": instruction},
        ]}],
        tools=[WEB_SEARCH_TOOL],
    )
    blocks, resp = _create_resilient(client, kwargs, search_budget=SEARCH_BUDGET_N)
    text = "".join(b.text for b in blocks if getattr(b, "type", "") == "text").strip()
    # Searches are what cost money, so count the search RESULTS. The tool also fetches
    # the pages it found, and each fetch is a server_tool_use block as well — counting
    # those reported a 6-search run as 12 (and matchup's 10-cap run as 24).
    searches = sum(1 for b in blocks if getattr(b, "type", "") == "web_search_tool_result")
    if resp.stop_reason == "max_tokens":
        print(f"    (warning: hit max_tokens — text {len(text)} chars)")

    obj = extract_json(text)
    if not obj:
        die(f"No parseable JSON. Tail: ...{text[-300:]!r}")
    recap = clean(obj)
    if not recap["notes"]:
        die("Recap came back with no notes.")

    content = to_plaintext(recap)
    print("-" * 60)
    print(content)
    print("-" * 60)
    api_usage.log_raw(sb, "generate_recap", MODEL, resp.usage, searches)

    if dry:
        print(f"\n[dry run] {searches} searches. Nothing written.")
        return

    sb.table("game_recaps").upsert({
        "game_id": game["id"],
        "sport_id": game["sport_id"],
        "kickoff": kickoff,
        "opponent": opp,
        "wvu_points": wvu_pts,
        "opp_points": opp_pts,
        "sections": recap,
        "content": content,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }, on_conflict="game_id").execute()
    print(f"\n[OK] Recap stored for game {game['id']} ({searches} searches).")


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
    now = datetime.now(timezone.utc)
    games = due_games(sb, now, gid, force)
    if not games:
        print(f"No football final in the last {RECAP_WINDOW_HOURS}h owes a recap — nothing to do.")
        return

    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    for game in games:
        generate(sb, client, game, dry)


if __name__ == "__main__":
    main()
