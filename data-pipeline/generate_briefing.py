"""
Mountaineer Pulse - Daily AI Briefing (per-sport, research-backed)
=================================================================
Claude reads the day's WVU headlines + confirmed roster moves + Pulse, then uses
web search to READ the actual articles and writes a briefing split into three
per-sport sections (Football / Men's Basketball / Baseball). Each section has a
few topics, a couple of sentences each — real detail (draft rounds, slot money,
who's staying/leaving), not one-liners. A sport with no genuine news is omitted.

Why search: our stored links are Google News redirects that don't fetch cleanly,
so we let Claude search the open web for each day's WVU stories and read the real
sources (SI, On3, 247, WV athletics, etc.). Grounding rules keep it to CONFIRMED,
current-program facts.

Writes daily_briefings.sections (jsonb) + a plain-text content fallback.
Needs ANTHROPIC_API_KEY. Run:  python generate_briefing.py
"""

import json
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone

from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

SB_URL = os.getenv("SUPABASE_URL")
SB_KEY = os.getenv("SUPABASE_SECRET_KEY")
ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY")

MODEL = "claude-sonnet-5"
WEB_SEARCH_TOOL = {"type": "web_search_20260209", "name": "web_search", "max_uses": 12}
SPORT_NAME = {"football": "Football", "mbb": "Men's Basketball", "baseball": "Baseball"}
SPORT_ORDER = ["football", "mbb", "baseball"]

# Sonnet-5 pricing per 1M tokens (intro pricing through 2026-08-31): $2 in / $10 out,
# cache write $2.50, cache read $0.20; web search $0.01/use. Used only for the cost readout.
PRICE = {"in": 2.0, "out": 10.0, "cache_w": 2.5, "cache_r": 0.20, "search": 0.01}

# Search budget: web search is the cost driver, but it's also what gives the briefing its real
# detail. Generous on a busy news day, self-limiting on a quiet one. Prompt caching (below) makes
# even a heavy day land near ~$0.50 by re-reading the stable context at ~10% instead of full price.
SEARCH_BUDGET = (
    "\n\nSEARCH BUDGET: web search is the costly part, so spend it well. FIRST make sure you've "
    "captured the biggest genuinely-new item in EACH sport that has one — do NOT tunnel every search "
    "into a single sport while another sport has real news (e.g. fall-camp/roster news on the football "
    "side while baseball has draft news). THEN add real depth (draft round & pick, slot/bonus money, "
    "snap counts, ERA/stats, honors) on the 1-2 most significant stories. For minor items, write from "
    "the DATA you already have instead of searching. Aim for roughly 8-12 searches on a busy news day "
    "and fewer on a quiet one. Once each sport's notable news is covered, STOP searching and write JSON."
)


def die(msg: str) -> None:
    print(f"\n[X] {msg}")
    sys.exit(1)


def build_context(sb) -> str:
    """The day's real facts — the AGENDA Claude researches and writes from."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=40)).isoformat()
    news = (
        sb.table("news_items").select("headline,source_name,published_at,sport_id")
        .gte("published_at", cutoff).order("published_at", desc=True).limit(60).execute().data
    )
    by_sport: dict[str, list] = {s: [] for s in SPORT_ORDER}
    general: list[str] = []
    for n in news:
        line = f"- {n['headline']} ({n.get('source_name') or 'source'})"
        if n.get("sport_id") in by_sport:
            by_sport[n["sport_id"]].append(line)
        elif not n.get("sport_id"):
            general.append(line)

    lines = ["=== TODAY'S WVU HEADLINES (last ~40h), grouped by sport ==="]
    for s in SPORT_ORDER:
        lines.append(f"\n[{SPORT_NAME[s]}]")
        lines += (by_sport[s] or ["- (no classified headlines)"])
    if general:
        lines.append("\n[General WVU]")
        lines += general

    moves = (
        sb.table("roster_moves").select("player_name,position,direction,category,sport_id,other_school,alert,move_date")
        .order("move_date", desc=True).execute().data
    )
    if moves:
        # A move older than this is history, not news — tag it so the freshness rule can see
        # its age. Without a date on the line, the model had no way to tell a move that
        # happened today from one three weeks ago, so a web search could resurface an old
        # signing (e.g. Casteel) and re-report it as if new.
        FRESH_DAYS = 4
        today_d = date.today()
        lines.append("\n=== CONFIRMED ROSTER MOVES (the ONLY source of truth for who is in/out) ===")
        for m in moves:
            d = "IN" if m["direction"] == "in" else "OUT"
            pos = f" {m['position']}" if m.get("position") else ""
            sch = f" ({'from' if d == 'IN' else 'to'} {m['other_school']})" if m.get("other_school") else ""
            alert = f"  ** NOTE: {m['alert']}" if m.get("alert") else ""
            md = (m.get("move_date") or "")[:10]
            when = ""
            if md:
                try:
                    age = (today_d - date.fromisoformat(md)).days
                    when = (f"  (dated {md})" if age <= FRESH_DAYS
                            else f"  (dated {md} — {age}d ago, already reported; background only, do NOT lead with this)")
                except ValueError:
                    when = ""
            lines.append(f"- {d}: {m['player_name']}{pos}{sch} [{SPORT_NAME.get(m['sport_id'], m['sport_id'])}]{alert}{when}")

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


def recent_briefings(sb, today: str, n: int = 7) -> str:
    """The last week's briefings, so Claude leads with what's NEW instead of re-summarizing
    an ongoing story (e.g. a multi-day MLB Draft cycle). A week of memory (not 3 days) keeps
    a story like a player's return from resurfacing days later once web search rediscovers it.
    Without this the generator has no memory and reproduces near-identical briefings."""
    rows = (
        sb.table("daily_briefings").select("date,content")
        .lt("date", today).order("date", desc=True).limit(n).execute().data
    )
    rows = [r for r in rows if (r.get("content") or "").strip()]
    if not rows:
        return ""
    parts = ["=== WHAT YOU ALREADY TOLD USERS (recent briefings — do NOT repeat these) ==="]
    for r in rows:
        parts.append(f"\n[{r['date']}]\n{r['content'].strip()}")
    return "\n".join(parts)


SYSTEM = (
    "You write the daily briefing for Mountaineer Pulse, a West Virginia University sports app. "
    "Voice: sharp, factual, a plugged-in WVU fan. Never hype, never filler.\n\n"
    "You have web search. USE IT: for each genuinely notable item in the DATA, search and read the "
    "actual articles so your summary has real detail (draft round & pick number, slot money, who is "
    "staying vs leaving, scores, honors) — not vague one-liners.\n\n"
    "ABSOLUTE ACCURACY RULES — one wrong fact loses a fan's trust:\n"
    "1. Every roster fact must match CONFIRMED ROSTER MOVES. Never call a player a commit/transfer/"
    "signing unless he is on that list. If a move has a ** NOTE, reflect it faithfully (e.g. a signee "
    "who is now likely to leave).\n"
    "2. Rumors are not facts. 'reportedly', 'expected to', 'targets', 'linked', 'could' = mark clearly "
    "as such, never as done deals.\n"
    "3. WVU players being drafted (MLB/NFL) IS notable program news — include it. But ignore unrelated "
    "alumni pro-career news, off-field/legal/personal stories, and other teams.\n"
    "4. CURRENT program only. Exclude commitments from FUTURE high-school recruiting classes a year+ "
    "away (e.g. class of 2027 or later high-schoolers). Incoming college transfers for the upcoming "
    "season ARE current.\n"
    "5. Significance filter: include only items a fan would care about. Do NOT pad. If a sport has no "
    "genuine news, omit its section entirely.\n"
    "6. FRESHNESS — this is what keeps the briefing alive: you are given the last few days' briefings "
    "under 'WHAT YOU ALREADY TOLD USERS'. Do NOT re-report what you already covered. Lead with what is "
    "genuinely NEW since then. Only revisit an ongoing story if there is a REAL update (a decision made, "
    "a signing finalized, a game played) and frame it AS the update ('Henne still hasn't signed — "
    "deadline July 27', 'now official'), never a re-summary. If a sport has had no new development since "
    "the last briefing, either omit it or give it a single line naming the one thing still worth "
    "watching. A quiet day should read as a quiet day, not a rerun. And judge freshness by DATE: "
    "if a development (a commitment, a return, a signing) happened more than ~3 days ago, it is NOT "
    "new — do not lead with it just because a web search resurfaced it. Today's date is given below.\n\n"
    "OUTPUT — reply with ONLY a JSON object, no prose around it:\n"
    "{\n"
    '  "intro": "<one short, warm greeting line>",\n'
    '  "sections": [\n'
    '    {"sport": "football|mbb|baseball",\n'
    '     "items": [{"topic": "<3-6 word headline>", "body": "<2-3 factual sentences with real detail>"}]}\n'
    "  ]\n"
    "}\n"
    "Include a section ONLY for sports with real news (0-3 topics each). Order sections football, then "
    "men's basketball, then baseball. Keep each body tight (~2-3 sentences)."
)


def extract_json(text: str):
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except ValueError:
        return None


def call_model(client, context: str, recent: str, use_search: bool):
    data_block = f"DATA:\n{context}"
    if recent:
        data_block += f"\n\n{recent}"
    instruction = (
        "Research the genuinely NEW items with web search, then output the briefing JSON. Lead with "
        "what has changed since the recent briefings above — do not repeat them; a slow day should read "
        f"as a slow day. Today is {date.today().isoformat()}."
    ) + (SEARCH_BUDGET if use_search else "")
    # Prompt caching: the SYSTEM prompt and the large, stable DATA block are cached, so the web-search
    # loop re-reads them at ~10% price each turn instead of reprocessing at full price. This is what
    # keeps a busy, multi-search day near ~$0.50 instead of ~$1+.
    system_blocks = [{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}]
    user_content = [
        {"type": "text", "text": data_block, "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": instruction},
    ]
    kwargs = dict(
        model=MODEL,
        max_tokens=8000,
        thinking={"type": "adaptive"},
        system=system_blocks,
        messages=[{"role": "user", "content": user_content}],
    )
    if use_search:
        kwargs["tools"] = [WEB_SEARCH_TOOL]
    resp = client.messages.create(**kwargs)
    text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()
    searches = sum(1 for b in resp.content if getattr(b, "type", "") == "server_tool_use")
    if resp.stop_reason == "max_tokens":
        print(f"    (warning: hit max_tokens; output may be truncated — text {len(text)} chars)")
    return text, searches, resp.usage


def to_plaintext(intro: str, sections: list) -> str:
    parts = [intro.strip()] if intro else []
    for sec in sections:
        parts.append(f"\n{SPORT_NAME.get(sec['sport'], sec['sport']).upper()}")
        for it in sec.get("items", []):
            parts.append(f"• {it.get('topic', '').strip()}: {it.get('body', '').strip()}")
    return "\n".join(parts).strip()


def strip_tags(s: str) -> str:
    """web_search wraps sourced facts in <cite index="..">..</cite> tags. Keep the text,
    drop the tags, so the app never shows raw markup. Also collapses any doubled spaces left behind."""
    s = re.sub(r"</?cite[^>]*>", "", s or "")
    return re.sub(r"\s{2,}", " ", s).strip()


def clean_sections(obj) -> tuple[str, list]:
    """Validate + normalize the model's JSON into (intro, sections)."""
    intro = strip_tags(str(obj.get("intro", "")))
    out = []
    raw = obj.get("sections", []) if isinstance(obj, dict) else []
    by_sport = {s.get("sport"): s for s in raw if isinstance(s, dict)}
    for sp in SPORT_ORDER:  # enforce football -> mbb -> baseball order
        sec = by_sport.get(sp)
        if not sec:
            continue
        items = []
        for it in sec.get("items", []):
            topic = strip_tags(str(it.get("topic", "")))
            body = strip_tags(str(it.get("body", "")))
            if topic and body:
                items.append({"topic": topic, "body": body})
        if items:
            out.append({"sport": sp, "items": items[:3]})
    return intro, out


def main() -> None:
    if not SB_URL or not SB_KEY:
        die("Missing SUPABASE_URL or SUPABASE_SECRET_KEY in .env")
    if not ANTHROPIC_KEY:
        die("No ANTHROPIC_API_KEY in .env — get one at https://console.anthropic.com")

    import anthropic

    sb = create_client(SB_URL, SB_KEY)
    today = date.today().isoformat()
    context = build_context(sb)
    recent = recent_briefings(sb, today)
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

    # Try with web search; if the tool is unavailable, fall back to headline-only.
    text, searches, usage = "", 0, None
    for use_search in (True, False):
        try:
            text, searches, usage = call_model(client, context, recent, use_search)
            if text:
                break
        except Exception as e:
            print(f"    ({'with' if use_search else 'no'} search failed: {str(e)[:120]})")
            continue

    obj = extract_json(text)
    if not obj:
        print(f"    (raw text was {len(text)} chars; tail: ...{text[-300:]!r})")
        die("Claude returned no parseable briefing JSON.")
    intro, sections = clean_sections(obj)
    if not sections:
        die("Briefing had no valid sport sections.")

    content = to_plaintext(intro, sections)
    sb.table("daily_briefings").upsert(
        {"date": today, "content": content, "sections": {"intro": intro, "sections": sections}},
        on_conflict="date",
    ).execute()

    # Notify subscribers that the morning briefing is ready (best-effort — never fail the run).
    try:
        from send_push import send_push
        teaser = (intro or "Your morning WVU rundown is ready.").strip()
        send_push("Your Mountaineer briefing 🏔️", teaser[:160], data={"screen": "pulse"})
    except Exception as e:
        print(f"    (push notify skipped: {str(e)[:120]})")

    print(f"Daily Briefing ({today}) — {MODEL}, {searches} searches\n" + "-" * 60)
    print(intro)
    for sec in sections:
        print(f"\n{SPORT_NAME[sec['sport']].upper()}")
        for it in sec["items"]:
            print(f"  • {it['topic']}: {it['body']}")
    print("-" * 60)
    if usage:
        cw = getattr(usage, "cache_creation_input_tokens", 0) or 0
        cr = getattr(usage, "cache_read_input_tokens", 0) or 0
        est = (usage.input_tokens / 1e6 * PRICE["in"] + usage.output_tokens / 1e6 * PRICE["out"]
               + cw / 1e6 * PRICE["cache_w"] + cr / 1e6 * PRICE["cache_r"] + searches * PRICE["search"])
        print(f"\n[OK] Briefing stored. {searches} searches | tokens: in {usage.input_tokens} / "
              f"cache-read {cr} / out {usage.output_tokens} | est. cost ~${est:.3f}")


if __name__ == "__main__":
    main()
