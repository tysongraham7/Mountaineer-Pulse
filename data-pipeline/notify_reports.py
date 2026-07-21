"""
Mountaineer Pulse - Email me when a new bug/feedback report arrives
===================================================================
Finds in-app reports that haven't been emailed yet (and aren't already resolved) and sends
you one email listing them, so you don't have to run read_reports.py to notice. Each report is
emailed exactly once (marked `notified` after a successful send).

Runs on a schedule from GitHub Actions (.github/workflows/report-alerts.yml) and can also be run
locally. Sends via Gmail SMTP.

Env (GitHub secrets, or your local .env):
  SUPABASE_URL, SUPABASE_SECRET_KEY   - already used by the rest of the pipeline
  GMAIL_USER                          - the Gmail address that SENDS the alert
  GMAIL_APP_PASSWORD                  - a Google App Password (NOT your normal password)
  REPORT_ALERT_TO                     - who to email (optional; defaults to GMAIL_USER)

Run:  python notify_reports.py
"""

import os
import smtplib
import ssl
import sys
from email.message import EmailMessage

from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

SB_URL = os.getenv("SUPABASE_URL")
SB_KEY = os.getenv("SUPABASE_SECRET_KEY")
GMAIL_USER = os.getenv("GMAIL_USER")
GMAIL_PW = os.getenv("GMAIL_APP_PASSWORD")
TO = os.getenv("REPORT_ALERT_TO") or GMAIL_USER

CATEGORY_LABEL = {
    "data": "Wrong data / stat",
    "bug": "Something's broken",
    "idea": "Feature idea",
    "other": "Other",
}


def die(msg: str) -> None:
    print(f"\n[X] {msg}")
    sys.exit(1)


def format_report(r: dict) -> str:
    cat = CATEGORY_LABEL.get(r.get("category"), r.get("category") or "—")
    when = (r.get("created_at") or "")[:16].replace("T", " ")
    meta = " · ".join(
        x for x in (r.get("platform"), f"v{r['app_version']}" if r.get("app_version") else None) if x
    )
    out = [f"[{cat}]  {when}   {meta}".rstrip()]
    ctx = r.get("context")
    if isinstance(ctx, dict) and ctx:
        where = " · ".join(f"{k}={v}" for k, v in ctx.items() if v)
        if where:
            out.append(f"  where: {where}")
    out.append(f"  {(r.get('message') or '').strip()}")
    out.append(f"  id: {r.get('id')}")
    return "\n".join(out)


def main() -> None:
    if not SB_URL or not SB_KEY:
        die("Missing SUPABASE_URL or SUPABASE_SECRET_KEY")
    sb = create_client(SB_URL, SB_KEY)

    # New = never emailed AND not already resolved (so clearing something before the next run
    # doesn't email it, and old reports from before this feature don't get re-sent).
    reports = (sb.table("error_reports").select("*")
               .eq("notified", False).eq("resolved", False)
               .order("created_at").execute().data or [])
    if not reports:
        print("No new reports to email.")
        return

    if not GMAIL_USER or not GMAIL_PW:
        # Graceful no-op so the scheduled workflow doesn't fail (and spam you) before you've
        # added the Gmail secrets. Nothing is marked notified, so it'll send once configured.
        print(f"[!] {len(reports)} new report(s), but GMAIL_USER / GMAIL_APP_PASSWORD aren't set — "
              "skipping email. Add the secrets and they'll send on the next run.")
        return

    n = len(reports)
    body = (
        f"{n} new Mountaineer Pulse report{'s' if n > 1 else ''} came in:\n\n"
        + "\n\n".join(format_report(r) for r in reports)
        + "\n\n----\nSee all: python read_reports.py"
        + "\nResolve one: python read_reports.py --resolve <id>\n"
    )
    msg = EmailMessage()
    msg["Subject"] = f"[Mountaineer Pulse] {n} new report{'s' if n > 1 else ''}"
    msg["From"] = GMAIL_USER
    msg["To"] = TO
    msg.set_content(body)

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context()) as s:
            s.login(GMAIL_USER, GMAIL_PW)
            s.send_message(msg)
    except Exception as e:
        # Don't mark notified if the send failed — retry next run.
        die(f"Email send failed: {str(e)[:160]}")

    print(f"[OK] Emailed {n} report(s) to {TO}.")
    for r in reports:
        sb.table("error_reports").update({"notified": True}).eq("id", r["id"]).execute()
    print("[OK] Marked them notified so they won't email again.")


if __name__ == "__main__":
    main()
