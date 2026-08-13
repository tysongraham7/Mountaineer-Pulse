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
from sync_news import near_duplicate, story_tokens

load_dotenv()

SB_URL = os.getenv("SUPABASE_URL")
SB_KEY = os.getenv("SUPABASE_SECRET_KEY")
ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY")

MODEL = "claude-haiku-4-5"
ET = ZoneInfo("America/New_York")

# The gap between the 11:00 UTC morning run and the 21:00 UTC afternoon run. Anything
# older than this was already in today's briefing, so it isn't "breaking" to anyone.
LOOKBACK_HOURS = 10
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


def recently_alerted(sb, days: int = 4) -> str:
    """Headlines already pushed in the last few days, so the model can recognise a
    follow-up as the SAME event and decline it.

    Token overlap alone is not enough here: "BREAKING: Brenen Lorient plans to return to
    WVU" and "Lorient to return to WVU for fifth season of eligibility" share only two
    distinctive words and score well under the near-duplicate threshold, yet they are
    plainly one story. Judging sameness is the model's job; near_duplicate stays as a
    cheap backstop for verbatim syndication.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    rows = (sb.table("news_items").select("headline,notified_at")
            .gte("notified_at", cutoff).order("notified_at", desc=True)
            .limit(20).execute().data or [])
    if not rows:
        return ""
    lines = "\n".join(f'- [{(r["notified_at"] or "")[:10]}] {r["headline"]}' for r in rows)
    return f"\n\nALREADY ALERTED (do NOT alert the same event again):\n{lines}"


def decide(sb, items: list[dict]) -> dict | None:
    import anthropic

    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    listing = "\n".join(
        f'- id={i["id"]} | {i["headline"]} ({i.get("source_name") or "source"})' for i in items
    )
    resp = client.messages.create(
        model=MODEL, max_tokens=400, system=SYSTEM,
        messages=[{"role": "user", "content":
                   f"Today is {date.today().isoformat()}. New WVU headlines since the "
                   f"morning briefing:\n\n{listing}{recently_alerted(sb)}\n\nDecide."}],
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
    print(f"Considering {len(items)} headline(s) from the last {LOOKBACK_HOURS}h "
          f"({already}/{MAX_PER_DAY} pushed today)...")

    obj = decide(sb, items)
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

    sent = send_push(title, body, data={"screen": "news"})
    stamp = datetime.now(timezone.utc).isoformat()
    n = mark_notified(sb, chosen, items, stamp)
    print(f"\n[OK] Pushed to {sent} device(s); marked {n} headline(s) as notified.")


if __name__ == "__main__":
    main()
