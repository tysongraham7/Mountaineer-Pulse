"""
Mountaineer Pulse - Unlanded-alert detector
===========================================
Catches the gap where a push went out but the app never caught up.

On 2026-08-19 the afternoon scan pushed "SOURCE: WVU Basketball player is no longer with
the program" (247Sports). The alert was correct. But that headline never names anyone —
it's a paywall teaser — so extract_moves.py had nothing to extract, and a user who tapped
the notification found a roster and a Movement tab that still listed the departed player.
The push and the app disagreed, and nothing in the pipeline noticed.

Guessing the name is not the fix. A vague headline is vague on purpose, and inventing a
player to fill the gap is exactly the failure that put four phantom transfers in the app
during fall camp. So this script does the honest thing: it notices the alert implied a
roster change, checks whether the app actually changed, and if not it emails so the move
can be curated by hand into roster_moves.json.

Runs alongside the bug-report alerts (every 4 hours), which gives the news feed time to
publish a named follow-up and extract_moves.py time to catch it on its own. Only when the
feed never names the player does this reach you.

Each alert is nagged about ONCE. The reminder is a prompt to go look, not a recurring alarm.

Run:  python check_unlanded_alerts.py [--dry-run]
"""

import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from supabase import create_client

import usage
from emailer import email_configured, send_email

load_dotenv()

SB_URL = os.getenv("SUPABASE_URL")
SB_KEY = os.getenv("SUPABASE_SECRET_KEY")
ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY")

MODEL = "claude-haiku-4-5"

# How far back to look at pushed alerts. Wide enough that a story pushed last night is still
# checked this morning, narrow enough that it never re-litigates old news.
WINDOW_DAYS = 3
# Don't nag the instant the push lands — the follow-up headline naming the player often
# arrives within the hour, and extract_moves.py runs twice a day. Give the pipeline a chance
# to handle it before asking a human to.
GRACE_HOURS = 6

SYSTEM = """You read a WVU sports headline that was pushed to fans as a breaking-news alert,
and decide ONE thing: does it announce a change to the roster — a player joining, leaving,
being dismissed, retiring, going pro, or having eligibility restored or lost?

Answer yes even when the headline does not name the player ("a player is no longer with the
program", "Mountaineers lose a starter"). Vague phrasing is the case that matters most here.

Answer NO for: game results, analysis, previews, rankings, injuries that don't end a career,
recruiting interest or visits without a commitment, coaching changes, sponsorships,
facilities, scheduling, and anything about former players or other teams.

Reply with ONLY a JSON object:
{"roster_change": true|false, "sport": "football"|"mbb"|"baseball"|"", "why": "<a few words>"}"""


def die(msg: str) -> None:
    print(f"\n[X] {msg}")
    sys.exit(1)


def classify(sb, headline: str) -> dict:
    import anthropic

    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    resp = client.messages.create(
        model=MODEL, max_tokens=150, system=SYSTEM,
        messages=[{"role": "user", "content": f"Headline: {headline}\n\nDecide."}],
    )
    usage.log(sb, "check_unlanded_alerts", MODEL, resp)
    raw = "".join(b.text for b in resp.content if b.type == "text")
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except ValueError:
        return {}


def landed(sb, sport: str | None, since: str) -> list[dict]:
    """Roster moves recorded on or after the day the alert fired. Matched on DATE rather than
    on the player's name for the obvious reason: the headline may not contain a name. A move
    logged the same day for the same sport is the change we were looking for."""
    q = sb.table("roster_moves").select("player_name,direction,move_date,sport_id")
    if sport:
        q = q.eq("sport_id", sport)
    return q.gte("move_date", since[:10]).execute().data or []


def mark_reviewed(sb, alerts: list[dict], stamp: str) -> None:
    """Stamp every alert this run looked at, flagged or not, so each produces at most one
    email rather than one every four hours."""
    for a in alerts:
        sb.table("news_items").update({"unlanded_flagged_at": stamp}).eq("id", a["id"]).execute()


def main() -> None:
    dry = "--dry-run" in sys.argv
    if not SB_URL or not SB_KEY:
        die("Missing SUPABASE_URL or SUPABASE_SECRET_KEY")
    if not ANTHROPIC_KEY:
        die("No ANTHROPIC_API_KEY")

    sb = create_client(SB_URL, SB_KEY)
    now = datetime.now(timezone.utc)
    start = (now - timedelta(days=WINDOW_DAYS)).isoformat()
    cutoff = (now - timedelta(hours=GRACE_HOURS)).isoformat()

    alerts = (sb.table("news_items")
              .select("id,headline,source_name,sport_id,notified_at,unlanded_flagged_at")
              .gte("notified_at", start).lte("notified_at", cutoff)
              .is_("unlanded_flagged_at", "null")
              .order("notified_at", desc=True).limit(20).execute().data or [])
    if not alerts:
        print(f"No un-reviewed alerts in the last {WINDOW_DAYS}d (past the {GRACE_HOURS}h grace).")
        return

    print(f"Reviewing {len(alerts)} pushed alert(s)...")
    gaps: list[dict] = []
    for a in alerts:
        verdict = classify(sb, a["headline"])
        if not verdict.get("roster_change"):
            print(f"  ok    {a['headline'][:70]}  ({verdict.get('why', 'not a roster change')})")
            continue
        sport = a.get("sport_id") or verdict.get("sport") or None
        moves = landed(sb, sport, a["notified_at"])
        if moves:
            names = ", ".join(f'{m["player_name"]} ({m["direction"]})' for m in moves[:4])
            print(f"  ok    {a['headline'][:70]}  -> landed: {names}")
            continue
        print(f"  GAP   {a['headline'][:70]}  -> no roster move recorded")
        gaps.append({**a, "sport": sport})

    if not gaps:
        print("\n[OK] Every pushed alert is reflected in the app.")
        if dry:
            print("[dry run] Nothing marked.")
            return
        # Nothing flagged: these were all fine, so mark them reviewed and never look again.
        mark_reviewed(sb, alerts, now.isoformat())
        return

    lines = [
        "A push went out about a roster change, but the app never changed to match.",
        "",
        "Usually this means the headline never named the player (a paywalled 'SOURCE:' scoop),",
        "so extract_moves.py had nothing to extract. Add the move by hand:",
        "",
        "  data-pipeline/roster_moves.json   the move itself (Movement tab + roster)",
        "  data-pipeline/curated_notes.json  a Pulse note, if the score should move",
        "  data-pipeline/depth_chart.json    if they were on the projected two-deep",
        "  data-pipeline/roster_removals.json  if wvusports.com still lists a departed player",
        "",
        "Then: python sync_moves.py && python sync_depth.py && python compute_pulse.py",
        "",
        "-" * 60,
    ]
    for g in gaps:
        lines += [
            "",
            g["headline"],
            f'  source: {g.get("source_name") or "unknown"}',
            f'  sport:  {g.get("sport") or "unclear"}',
            f'  pushed: {(g.get("notified_at") or "")[:16].replace("T", " ")} UTC',
        ]
    body = "\n".join(lines)
    print("\n" + body)

    if dry:
        print("\n[dry run] Nothing emailed, nothing marked.")
        return
    if not email_configured():
        print("\n[!] Email not configured (RESEND_API_KEY / REPORT_ALERT_TO) — not sending.")
        return

    n = len(gaps)
    send_email(f"Mountaineer Pulse: {n} alert{'s' if n > 1 else ''} not reflected in the app", body)
    mark_reviewed(sb, alerts, now.isoformat())
    print(f"\n[OK] Emailed {n} gap(s); marked {len(alerts)} alert(s) reviewed.")


if __name__ == "__main__":
    main()
