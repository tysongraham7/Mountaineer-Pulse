"""
Mountaineer Pulse - Did the morning pipeline actually run?
=========================================================
GitHub runs scheduled workflows on a best-effort queue, and this repo's morning job has
drifted badly: 33-43 minutes late through most of August, ten HOURS late on the 27th and
28th, and simply absent on the 23rd, 31st and Sept 1. Nothing announced any of it. The
briefing quietly didn't appear, and the only reason anyone noticed was a user asking why
"Good morning" was arriving at dinner time.

That matters more than a missing briefing. The same job writes the game-day scouting
report, so a silent skip on a Saturday means no report on the one day it is read.

This asks the only question that matters -- is there a briefing dated today -- and emails
if there isn't. Runs a few hours after the pipeline is due, so a merely-late run has time
to land before anyone is bothered.

Run:  python check_pipeline_ran.py [--dry-run]
"""

import os
import sys
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from supabase import create_client

from emailer import email_configured, send_email

load_dotenv()

SB_URL = os.getenv("SUPABASE_URL")
SB_KEY = os.getenv("SUPABASE_SECRET_KEY")
ET = ZoneInfo("America/New_York")


def die(msg: str) -> None:
    print(f"\n[X] {msg}")
    sys.exit(1)


def main() -> None:
    dry = "--dry-run" in sys.argv
    if not SB_URL or not SB_KEY:
        die("Missing SUPABASE_URL or SUPABASE_SECRET_KEY")

    sb = create_client(SB_URL, SB_KEY)
    today = date.today().isoformat()
    now_et = datetime.now(timezone.utc).astimezone(ET)

    rows = (sb.table("daily_briefings").select("date,generated_at")
            .eq("date", today).execute().data or [])
    if rows:
        made = (rows[0].get("generated_at") or "")[:16].replace("T", " ")
        print(f"[OK] Briefing for {today} exists (written {made} UTC).")
        return

    # No briefing today. Say when the last one was, so the mail distinguishes "late this
    # morning" from "this has been broken for three days".
    prev = (sb.table("daily_briefings").select("date")
            .lt("date", today).order("date", desc=True).limit(1).execute().data or [])
    last = prev[0]["date"] if prev else "never"
    gap = ""
    if prev:
        try:
            gap = f" ({(date.fromisoformat(today) - date.fromisoformat(last)).days} day(s) ago)"
        except ValueError:
            pass

    body = "\n".join([
        f"No daily briefing for {today}. It is {now_et:%H:%M} ET and the pipeline is due at 06:37.",
        "",
        f"Last briefing: {last}{gap}",
        "",
        "The morning job also writes the game-day scouting report and refreshes rosters,",
        "schedules and scores — so a missed run is not only a missing briefing.",
        "",
        "Almost always this is GitHub dropping the scheduled run rather than a code failure.",
        "To fix it now: Actions -> Daily WVU Data Pipeline -> Run workflow.",
    ])
    print(body)

    if dry:
        print("\n[dry run] Nothing emailed.")
        return
    if not email_configured():
        print("\n[!] Email not configured — nobody was told.")
        return
    send_email(f"Mountaineer Pulse: no briefing for {today}", body)
    print("\n[OK] Emailed.")


if __name__ == "__main__":
    main()
