"""
Mountaineer Pulse - Breaking-news push
======================================
The morning briefing is a digest; this is the interrupt. When something real breaks
between scans — a player returning, a commitment, a coaching change — this pushes ONE
alert instead of making people wait until 7am. Brenen Lorient's return broke at 8pm and
users didn't see it until the next morning; that is the gap this closes.

A push interrupts someone's day, so the bar is deliberately high and enforced in three
independent places:

  1. WINDOW    only headlines from the last LOOKBACK_HOURS, which is the gap since the
               morning run — so anything today's briefing already covered is out of scope.
  2. JUDGMENT  a cheap model picks at most ONE genuinely notable item, or none. Most
               afternoons return none, and that is the expected outcome.
  3. LIMITS    a hard daily cap and quiet hours, applied in code. The model cannot vote
               itself past these.

Every pushed headline is stamped `notified_at`, along with any near-duplicate of the same
story, so a syndicated repost tomorrow can't fire a second alert for the same news.

Run:  python notify_news.py [--dry-run] [--force]
        --dry-run  decide and print, send nothing, write nothing
        --force    ignore quiet hours (still respects the daily cap)
"""

import json
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from supabase import create_client

import usage
from send_push import send_push
# Same near-duplicate detection the news sync uses to collapse syndicated copies, so a
# story we already pushed can't come back tomorrow under another outlet's headline.
from names import norm_name, split_name
from sync_news import near_duplicate, story_tokens

load_dotenv()

SB_URL = os.getenv("SUPABASE_URL")
SB_KEY = os.getenv("SUPABASE_SECRET_KEY")
ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY")

MODEL = "claude-haiku-4-5"
# Writing the in-app summary is a research job, not a classification one, so it gets the
# better model. It runs at most MAX_PER_DAY times a day and only after a push is already
# committed, which bounds the cost to a couple of dollars a month.
SUMMARY_MODEL = "claude-sonnet-5"
# Three, not six: a breaking headline has little coverage yet, so extra searches return the
# same two aggregator posts and cost real money for nothing.
WEB_SEARCH_TOOL = {"type": "web_search_20260209", "name": "web_search", "max_uses": 3}
ET = ZoneInfo("America/New_York")

# Slightly wider than the two-hour gap between scans, so a failed scan doesn't punch a hole
# in the coverage — but no wider. This used to be 10 hours, sized for a single daily run, and
# left at 10 it would have meant every story sitting in the candidate list for five
# consecutive scans: five independent chances for the model to talk itself into pushing
# something it had already, correctly, passed on.
#
# It does NOT need to reach back across the night. The 11:00 UTC briefing covers everything
# that broke while quiet hours held alerts back, and by 8am that news is the morning
# briefing's, not breaking. A scan that reached back twelve hours would just re-alert on what
# users had already read over breakfast.
LOOKBACK_HOURS = 3
MAX_PER_DAY = 2          # counting the morning briefing's own push, this is the ceiling
QUIET_START_HOUR = 22    # 10pm ET
QUIET_END_HOUR = 8       # 8am ET
MAX_TITLE = 60
MAX_BODY = 155           # Expo truncates past ~160; leave headroom

SYSTEM = """You decide whether a WVU (West Virginia University) sports headline deserves a
PUSH NOTIFICATION to fans' phones, and if so you write it.

A push interrupts someone's day. Most days the answer is NO. Returning notify=false is the
normal, correct outcome — you are not expected to find something.

SCOPE — check this FIRST. This app covers exactly three programs: WVU FOOTBALL, WVU MEN'S
BASKETBALL, and WVU BASEBALL. Plus athletics-wide news that affects the whole department
(a sponsorship across all sports, facilities, conference realignment). Anything about ANY
other program — women's basketball, women's soccer, gymnastics, wrestling, rifle, volleyball,
soccer, track — is OUT OF SCOPE, no matter how genuinely dramatic it is. The news feed
carries those stories; this app does not show them, so alerting on one would push a fan to
a screen where the story does not exist. If the only notable item is another sport, return
notify=false.

PUSH-WORTHY (a fan would want to be interrupted):
- A player confirmed joining or leaving the roster (transfer, signing, portal, returning
  from an eligibility ruling, drafted and signing pro).
- A coaching or staff change: hire, firing, resignation.
- A season-ending or major injury to a significant player.
- A game result, but only a completed one.
- A major program announcement: a big sponsorship, a facilities project, conference or
  scheduling news of real consequence.

NOT PUSH-WORTHY (the overwhelming majority):
- Analysis, columns, previews, projections, mailbags, "what to watch", depth-chart
  predictions, podcasts, "5 takeaways".
- Rumors and hedged reports: "reportedly", "could", "expected to", "targeting", "linked",
  "sources say", "set to". If it has not happened yet, it is not breaking.
- Recruiting visits, offers, or interest — only an actual commitment counts.
- Practice reports, press conference recaps, fan-day logistics, ticket news.
- Anything about former players' pro careers, or other teams.
- Off-field, legal, or personal stories about individuals.

If several headlines cover the SAME event, choose the single clearest one.

AGE. Every candidate is labelled with how long ago it was published, and you run every two
hours — so some of what you see, you have already passed on once. That earlier judgment was
probably right; do not change your mind just because a story is still there. Nothing more
than about four hours old is breaking any more: it will be in tomorrow's briefing, and
interrupting someone for it now makes the alerts feel random. When two headlines cover the
same event, prefer the newer one.

NEVER RE-ALERT. You may be shown an ALREADY ALERTED list of stories pushed in recent days.
If today's candidate is the same EVENT as one of those — even worded completely differently,
even from a different outlet, even as a follow-up, reaction or analysis of it — return
notify=false. Fans were already interrupted for that news once. Only a genuinely new
development counts (a decision that was pending is now final, a player who was reported
is now signed), and then the alert must be about what CHANGED.

Write the alert yourself:
  title: under 55 characters. Lead with the news, not the app name. No clickbait.
  body:  under 150 characters, one or two plain sentences with the actual facts from the
         headline. Never add a detail the headline does not state.

Reply with ONLY a JSON object, no prose around it:
{"notify": true|false, "id": "<the id of the chosen headline, or empty>",
 "title": "<alert title>", "body": "<alert body>", "why": "<short reason for your call>"}"""


def die(msg: str) -> None:
    print(f"\n[X] {msg}")
    sys.exit(1)


def in_quiet_hours(now_et: datetime) -> bool:
    """True between QUIET_START_HOUR and QUIET_END_HOUR ET (the window wraps midnight)."""
    h = now_et.hour
    return h >= QUIET_START_HOUR or h < QUIET_END_HOUR


def pushed_today(sb, now_et: datetime) -> int:
    """How many alerts have already gone out today, counted in EASTERN days — a push at
    9pm ET is stored as tomorrow in UTC, and counting UTC days would reset the cap mid-evening."""
    start_utc = (now_et.replace(hour=0, minute=0, second=0, microsecond=0)
                 .astimezone(timezone.utc).isoformat())
    rows = (sb.table("news_items").select("id")
            .gte("notified_at", start_utc).execute().data or [])
    return len(rows)


def candidates(sb) -> list[dict]:
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)).isoformat()
    return (sb.table("news_items")
            .select("id,headline,source_name,sport_id,published_at")
            .gte("published_at", cutoff).is_("notified_at", "null")
            .order("published_at", desc=True).limit(40).execute().data or [])


def alerted_rows(sb, days: int = 4) -> list[dict]:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    return (sb.table("news_items")
            .select("headline,notified_at,summary,summary_headline,summary_player")
            .gte("notified_at", cutoff).order("notified_at", desc=True)
            .limit(20).execute().data or [])


def recently_alerted(rows: list[dict]) -> str:
    """What we already pushed in the last few days, so the model can recognize a follow-up
    as the SAME event and decline it.

    Token overlap alone is not enough: "BREAKING: Brenen Lorient plans to return to WVU" and
    "Lorient to return to WVU for fifth season of eligibility" share two distinctive words
    and score under the near-duplicate threshold, yet are plainly one story.

    The headline alone is not enough EITHER, which cost users a duplicate alert. We pushed
    "SOURCE: WVU Basketball player is no longer with the program" one evening, and the next
    morning a second outlet published "Evans Barning Jr. exits WVU Men's Basketball". Same
    event. But the first headline never names anyone — a teaser written to sell a
    subscription — so the two share nothing, and nothing in this list said who it was about.
    We knew: the summary written minutes after that push named him. It just wasn't shown
    here. So the summary comes along now, and the name most of all.
    """
    if not rows:
        return ""
    lines = []
    for r in rows:
        lines.append(f'- [{(r["notified_at"] or "")[:10]}] {r["headline"]}')
        if r.get("summary_player"):
            lines.append(f'    this was about: {r["summary_player"]}')
        if r.get("summary_headline"):
            lines.append(f'    we told users: {r["summary_headline"]}')
        if r.get("summary"):
            lines.append(f'    detail: {r["summary"][:220]}')
    return ("\n\nALREADY ALERTED (do NOT alert the same event again, however differently "
            "it is worded, and however much more detail a later report adds):\n"
            + "\n".join(lines))


def blocked_by_prior_alert(headline: str, rows: list[dict]) -> str | None:
    """A hard, model-free block: this headline is about someone we already alerted on.

    The prompt asks the model not to re-alert, and it mostly won't — but a named follow-up
    to an unnamed scoop reads like brand-new information, and it slipped through once. A
    person is only 'no longer with the program' once, so a second alert naming them days
    later is a repeat by definition. Deterministic guard, same shape as the roster checks in
    extract_moves.py that stopped the phantom transfers.
    """
    hay = f" {norm_name(headline)} "
    for r in rows:
        who = (r.get("summary_player") or "").strip()
        if not who:
            continue
        first, last = split_name(who)
        # Match on the full name, and on a surname distinctive enough not to collide.
        needles = [norm_name(who)]
        if len(last) >= 5:
            needles.append(norm_name(last))
        if any(f" {n} " in hay for n in needles if n):
            return who
    return None


def age_label(published_at: str | None) -> str:
    """How long ago this headline was published, for the candidate list."""
    if not published_at:
        return "age unknown"
    try:
        pub = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
    except ValueError:
        return "age unknown"
    mins = int((datetime.now(timezone.utc) - pub).total_seconds() // 60)
    if mins < 90:
        return f"{max(0, mins)}m ago"
    return f"{mins // 60}h ago"


def decide(sb, items: list[dict], prior: list[dict]) -> dict | None:
    import anthropic

    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    # Age matters now that this runs every three hours: the same story sits in the candidate
    # list for several consecutive runs, and without a timestamp the model can't tell a
    # twenty-minute-old scoop from one it already declined this morning.
    listing = "\n".join(
        f'- id={i["id"]} | [{age_label(i.get("published_at"))}] {i["headline"]} '
        f'({i.get("source_name") or "source"})' for i in items
    )
    resp = client.messages.create(
        model=MODEL, max_tokens=400, system=SYSTEM,
        messages=[{"role": "user", "content":
                   f"Today is {date.today().isoformat()}. New WVU headlines since the "
                   f"morning briefing:\n\n{listing}{recently_alerted(prior)}\n\nDecide."}],
    )
    usage.log(sb, "notify_news", MODEL, resp)
    raw = "".join(b.text for b in resp.content if b.type == "text")
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        print(f"  (unparseable reply: {raw[:160]})")
        return None
    try:
        return json.loads(m.group(0))
    except ValueError:
        print(f"  (bad JSON: {raw[:160]})")
        return None


SUMMARY_SYSTEM = """You write the short in-app explainer that a WVU fan reads right after
tapping a breaking-news alert on their phone.

Why this exists: the alert links to an article that is often paywalled or vague on purpose
("SOURCE: a player is no longer with the program"). A fan who taps and hits a login wall
learns nothing. Your job is to tell them what actually happened, in the app, in plain
language, so they never have to leave.

Search the web to find out what the headline is actually about — especially the NAME of any
player involved, which teaser headlines withhold. Free aggregators and local outlets usually
carry the same story.

WRITE IN YOUR OWN WORDS. Never reproduce sentences from any article you find. You are
stating the facts of an event, not republishing someone's reporting.

RULES
- 2 to 4 short sentences. A fan on a phone, not a press release.
- Lead with the concrete fact: who, and what happened.
- State ONLY what your sources support. If searching turned up nothing beyond the headline,
  say plainly what is known and that details have not been reported yet. NEVER invent a
  name, a school, a number, or a reason. An honest "the player has not been named yet" is a
  correct answer and far better than a guess.
- NEVER NAME A CANDIDATE. Name a player only if a source ties that person to THIS event. Do
  not reason about who it is likely to be, do not raise a player whose situation was
  unresolved, do not write "possibly X" or "the most recent situation involved X". Naming
  the wrong player is the worst thing you can do here: the fan believes it, and it sits in
  the app next to roster data that says otherwise. If the story does not name anyone, then
  neither do you — two sentences saying so is the right answer.
- No hype, no speculation about what it means for the season, no "stay tuned".
- Do not tell the reader to check back or follow the story. Just say what is known.
- American spellings throughout (offense, defense, canceled, traveled).

Also decide where in the app this change shows up, for a "see it in the app" button:
  "movement" - a player joining or leaving (Team tab, Movement)
  "roster"   - a change to who is on the roster (Team tab)
  "scores"   - a game result
  ""         - nothing in the app reflects this story

Write a headline for it too. The source's own headline is often a teaser written to sell a
subscription ("SOURCE: a player is no longer with the program") and by now you usually know
more than it does. Yours should say the actual news in under 60 characters — plain, specific,
no colon-prefix, no outlet name. If you never learned more than the source headline said,
return an empty string and we'll use theirs.

Reply with ONLY a JSON object:
{"headline": "<under 60 chars, or empty>", "summary": "<2-4 sentences>",
 "section": "movement"|"roster"|"scores"|"",
 "player": "<the player's name if you found it, else empty>"}"""


def app_context(sb, sport_id: str | None) -> str:
    """Roster moves the app already shows for this sport, as grounding.

    Two jobs. It stops the summary contradicting the app — a card reading "it may involve
    Player X" sitting above a Movement tab that says Player Y left is worse than no card at
    all. And when the move has already been curated, the summary can simply name the player
    the teaser headline withheld."""
    if not sport_id:
        return ""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=14)).date().isoformat()
    rows = (sb.table("roster_moves")
            .select("player_name,direction,category,move_date,notes")
            .eq("sport_id", sport_id).gte("move_date", cutoff)
            .order("move_date", desc=True).limit(10).execute().data or [])
    if not rows:
        return ""
    lines = "\n".join(
        f'- {r["player_name"]} ({"joined" if r["direction"] == "in" else "left"}, '
        f'{r.get("move_date")}){": " + r["notes"] if r.get("notes") else ""}' for r in rows)
    return ("\nWhat the app already shows for this sport in the last two weeks. These are "
            "confirmed and may well be the event in the headline — but do NOT assume it; only "
            "connect one to the story if your sources actually do:\n" + lines + "\n")


def summarize(sb, chosen: dict) -> dict:
    """Research the pushed story and write the explainer the home screen shows.

    Best-effort by design: this runs AFTER the push has gone out, so a failure here must
    never look like a failed alert. A story with no summary just renders as the headline."""
    import anthropic

    from generate_briefing import extract_json

    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    kwargs = dict(
        model=SUMMARY_MODEL,
        max_tokens=1200,
        system=SUMMARY_SYSTEM,
        messages=[{"role": "user", "content":
                   f"Today is {date.today().isoformat()}.\n\n"
                   f'Headline: "{chosen["headline"]}"\n'
                   f'Source: {chosen.get("source_name") or "unknown"}\n'
                   f"{app_context(sb, chosen.get('sport_id'))}\n"
                   "Find out what happened and write the JSON."}],
        tools=[WEB_SEARCH_TOOL],
    )
    # Deliberately NOT _create_resilient here. Its pause_turn loop re-sends the whole
    # conversation on every resume, search results included, so input tokens compound: a
    # single summary came back at 384k input and cost $1.00. Bounded at two calls instead —
    # one that may search, then at most one tool-free call to write the JSON from what it
    # found. That keeps a summary near 20k input and a couple of cents.
    try:
        resp = client.messages.create(**kwargs)
        blocks = list(resp.content)
        searches = getattr(resp.usage, "server_tool_use", None)
        searches = getattr(searches, "web_search_requests", 0) or 0
        usage.log_raw(sb, "notify_news.summary", SUMMARY_MODEL, resp.usage, searches)

        if resp.stop_reason == "pause_turn":
            print("    (searching done — writing the summary)")
            follow = {k: v for k, v in kwargs.items() if k != "tools"}
            follow["messages"] = list(kwargs["messages"]) + [
                {"role": "assistant", "content": resp.content}]
            resp2 = client.messages.create(**follow)
            blocks += list(resp2.content)
            usage.log_raw(sb, "notify_news.summary", SUMMARY_MODEL, resp2.usage, 0)
    except Exception as e:
        print(f"  (summary failed, alert already sent: {str(e)[:120]})")
        return {}
    text = "".join(b.text for b in blocks if getattr(b, "type", "") == "text").strip()

    obj = extract_json(text) or {}
    summary = (obj.get("summary") or "").strip()
    if not summary:
        print("  (no summary returned)")
        return {}
    section = (obj.get("section") or "").strip().lower()
    if section not in ("movement", "roster", "scores"):
        section = ""
    # Empty is a valid answer meaning "I learned nothing the source headline didn't say" —
    # the card falls back to theirs rather than printing a worse paraphrase.
    headline = (obj.get("headline") or "").strip()[:90]
    if headline:
        print(f"  headline: {headline}")
    print(f"  summary ({searches} searches): {summary[:150]}")
    player = (obj.get("player") or "").strip()[:80]
    if player:
        # The name a teaser headline withheld. Printed for the log, but STORED because the
        # duplicate guard needs it: without it, "a player is no longer with the program" and
        # "Evans Barning Jr. exits WVU" are unrelated strings.
        print(f"  player named by search: {player}")
    return {"summary": summary, "summary_section": section or None,
            "summary_headline": headline or None, "summary_player": player or None}


def mark_notified(sb, chosen: dict, pool: list[dict], stamp: str) -> int:
    """Stamp the pushed item and every near-duplicate of it, so the same story cannot
    fire again tomorrow when another outlet reposts it."""
    toks = story_tokens(chosen["headline"])
    ids = [chosen["id"]] + [
        i["id"] for i in pool
        if i["id"] != chosen["id"] and near_duplicate(toks, story_tokens(i["headline"]))
    ]
    for nid in ids:
        sb.table("news_items").update({"notified_at": stamp}).eq("id", nid).execute()
    return len(ids)


def main() -> None:
    dry = "--dry-run" in sys.argv
    force = "--force" in sys.argv
    if not SB_URL or not SB_KEY:
        die("Missing SUPABASE_URL or SUPABASE_SECRET_KEY")
    if not ANTHROPIC_KEY:
        die("No ANTHROPIC_API_KEY")

    sb = create_client(SB_URL, SB_KEY)
    now_et = datetime.now(timezone.utc).astimezone(ET)

    if in_quiet_hours(now_et) and not force:
        print(f"Quiet hours ({now_et:%H:%M} ET) — not pushing. Nothing marked, so a real "
              "story stays eligible for the next run.")
        return

    already = pushed_today(sb, now_et)
    if already >= MAX_PER_DAY:
        print(f"Daily cap reached ({already}/{MAX_PER_DAY}) — not pushing.")
        return

    items = candidates(sb)
    if not items:
        print(f"No new headlines in the last {LOOKBACK_HOURS}h — nothing to consider.")
        return

    # Drop follow-ups to something we already alerted on before the model ever sees them.
    # Doing it here rather than trusting the prompt: a named follow-up to an unnamed scoop
    # reads like new information, and that is exactly how users got a second alert about
    # Evans Barning Jr. the morning after the first.
    prior = alerted_rows(sb)
    kept = []
    for i in items:
        who = blocked_by_prior_alert(i["headline"], prior)
        if who:
            print(f"  skipping (already alerted about {who}): {i['headline'][:70]}")
            # Stamp it, so it stops reappearing in every scan for the rest of the window.
            sb.table("news_items").update(
                {"notified_at": datetime.now(timezone.utc).isoformat()}).eq("id", i["id"]).execute()
        else:
            kept.append(i)
    items = kept
    if not items:
        print("Everything new is a follow-up to a story already pushed — nothing to consider.")
        return

    print(f"Considering {len(items)} headline(s) from the last {LOOKBACK_HOURS}h "
          f"({already}/{MAX_PER_DAY} pushed today)...")

    obj = decide(sb, items, prior)
    if not obj:
        return
    if not obj.get("notify"):
        print(f"  No alert: {str(obj.get('why', ''))[:160]}")
        return

    by_id = {i["id"]: i for i in items}
    chosen = by_id.get(str(obj.get("id", "")).strip())
    if not chosen:
        # The model must point at a real candidate; an unmatched id means it invented one.
        print(f"  Chose an id not in the candidate list ({obj.get('id')!r}) — skipping.")
        return

    title = (obj.get("title") or "Mountaineer Pulse").strip()[:MAX_TITLE]
    body = (obj.get("body") or chosen["headline"]).strip()[:MAX_BODY]
    print(f"  ALERT  {title}\n         {body}\n         from: {chosen['headline']}")
    print(f"         why: {str(obj.get('why', ''))[:160]}")

    if dry:
        print("\n[dry run] Nothing sent, nothing marked.")
        return

    # "breaking" lands on the home screen, where the story appears as a card with the summary
    # written below — not on the News tab, where a new user has to work out that the headline
    # is a link to somewhere else. newsId tells the card which story to open on.
    sent = send_push(title, body, data={"screen": "breaking", "newsId": chosen["id"]})
    stamp = datetime.now(timezone.utc).isoformat()
    n = mark_notified(sb, chosen, items, stamp)
    print(f"\n[OK] Pushed to {sent} device(s); marked {n} headline(s) as notified.")

    # Research the story only after the push is out. It costs a few cents and takes ~30s, and
    # nothing about the alert should wait on it — the card falls back to the headline alone.
    print("\nWriting the in-app summary...")
    extra = summarize(sb, chosen)
    if extra:
        sb.table("news_items").update(extra).eq("id", chosen["id"]).execute()
        print("[OK] Summary stored — the home screen will show it.")


if __name__ == "__main__":
    main()
