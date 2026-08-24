"""
Mountaineer Pulse - Approve or discard a queued breaking alert
=============================================================
The only thing in the pipeline that sends a breaking-news notification.

notify_news.py used to send directly. Two of the first three alerts it sent were wrong — a
duplicate about a player who had already been covered, then a SOCCER result announced as a
basketball win — and a push cannot be recalled. The model turned out to be good at writing an
alert and unreliable at deciding one should exist, so it now does the first job and a person
does the second.

The queue is `pending_alerts`. notify_news writes a row and emails what it wants to say; this
sends it, or bins it.

Run:  python approve_alert.py --send      send the newest pending alert
      python approve_alert.py --discard   bin it
      python approve_alert.py             just show what's waiting

Nothing is stamped until the moment it actually sends, so a discarded story stays eligible if
a better-worded version of it turns up tomorrow.
"""

import os
import sys
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from supabase import create_client

from notify_news import PENDING_TTL_HOURS, mark_notified, summarize
from send_push import send_push

load_dotenv()

SB_URL = os.getenv("SUPABASE_URL")
SB_KEY = os.getenv("SUPABASE_SECRET_KEY")


def die(msg: str) -> None:
    print(f"\n[X] {msg}")
    sys.exit(1)


def newest_pending(sb) -> dict | None:
    rows = (sb.table("pending_alerts").select("*").eq("status", "pending")
            .order("created_at", desc=True).limit(1).execute().data or [])
    return rows[0] if rows else None


def expire_stale(sb) -> int:
    """Anything past the TTL stops being sendable. Approving a six-hour-old 'breaking' alert
    would push news everyone has already read, so letting one sit is a safe way to say no."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=PENDING_TTL_HOURS)).isoformat()
    stale = (sb.table("pending_alerts").select("id")
             .eq("status", "pending").lt("created_at", cutoff).execute().data or [])
    for r in stale:
        sb.table("pending_alerts").update(
            {"status": "expired", "decided_at": datetime.now(timezone.utc).isoformat()}
        ).eq("id", r["id"]).execute()
    return len(stale)


def show(p: dict) -> None:
    age = ""
    try:
        made = datetime.fromisoformat(p["created_at"].replace("Z", "+00:00"))
        age = f"  ({int((datetime.now(timezone.utc) - made).total_seconds() // 60)} min old)"
    except (ValueError, KeyError):
        pass
    print(f"\nPending alert #{p['id']}{age}")
    print("-" * 60)
    print(f"  {p['title']}")
    print(f"  {p['body']}")
    print("-" * 60)
    print(f"  from   : {p.get('headline')}")
    print(f"  source : {p.get('source_name')}")
    print(f"  why    : {(p.get('why') or '')[:200]}")


def main() -> None:
    send = "--send" in sys.argv
    discard = "--discard" in sys.argv
    if send and discard:
        die("Pick one: --send or --discard")
    if not SB_URL or not SB_KEY:
        die("Missing SUPABASE_URL or SUPABASE_SECRET_KEY")

    sb = create_client(SB_URL, SB_KEY)
    n = expire_stale(sb)
    if n:
        print(f"({n} alert(s) expired unsent — older than {PENDING_TTL_HOURS}h)")

    p = newest_pending(sb)
    if not p:
        print("Nothing waiting for approval.")
        return
    show(p)

    if not (send or discard):
        print("\nNothing done. Pass --send or --discard.")
        return

    now = datetime.now(timezone.utc).isoformat()
    if discard:
        sb.table("pending_alerts").update({"status": "discarded", "decided_at": now}).eq("id", p["id"]).execute()
        print("\n[OK] Discarded. Nothing was sent.")
        return

    news_id = p.get("news_id")
    chosen = None
    if news_id:
        rows = sb.table("news_items").select("*").eq("id", news_id).execute().data or []
        chosen = rows[0] if rows else None
    if not chosen:
        die("The story behind this alert has gone from news_items — refusing to send.")

    sent = send_push(p["title"], p["body"], data={"screen": "breaking", "newsId": news_id})
    if sent == 0:
        # send_push returns 0 when the global kill switch is on, when there are no devices, or
        # when Expo rejected everything. None of those should read as success.
        print("\n[!] Nothing was delivered — leaving this pending so it can be retried.")
        return

    # Stamped only now, at the moment it really went out.
    marked = mark_notified(sb, chosen, [chosen], now)
    sb.table("pending_alerts").update({"status": "sent", "decided_at": now}).eq("id", p["id"]).execute()
    print(f"\n[OK] Sent to {sent} device(s); marked {marked} headline(s) notified.")

    # The home-screen card wants a summary written in our own words. Only worth the few cents
    # once the alert has actually gone out.
    print("\nWriting the in-app summary...")
    extra = summarize(sb, chosen)
    if extra:
        sb.table("news_items").update(extra).eq("id", news_id).execute()
        print("[OK] Summary stored — the home screen will show it.")


if __name__ == "__main__":
    main()
