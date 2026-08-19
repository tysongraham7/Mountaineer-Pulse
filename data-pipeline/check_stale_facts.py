"""
Mountaineer Pulse - Stale-fact detector
=======================================
Facts don't just get typed wrong — true facts ROT. "Has until Jul 27 to decide" was correct
in July and false a week later. This scans the curated data for facts that have likely gone
stale and (optionally) emails you a short "review these" list, so nothing quietly rots.

What it flags:
  * roster_moves still marked 'draft-pending' more than a few days after the move date
    (the decision has probably been made — confirm it),
  * any roster_moves / depth_chart alert or note that mentions a date now in the PAST
    (e.g. "deadline Jul 27" once Jul 27 has passed).

Costs nothing to run: pure date checks on data you already have, no AI calls. Prints findings
always; emails a digest only when the email secrets are set and there's something to report.

  python check_stale_facts.py

Env: SUPABASE_URL, SUPABASE_SECRET_KEY (required); RESEND_API_KEY, REPORT_ALERT_TO
(optional, to email the digest — see emailer.py).
"""

import os
import re
import sys
from datetime import date

from dotenv import load_dotenv
from supabase import create_client

from emailer import email_configured, send_email

load_dotenv()

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

SB_URL = os.getenv("SUPABASE_URL")
SB_KEY = os.getenv("SUPABASE_SECRET_KEY")

PENDING_GRACE_DAYS = 4  # a 'draft-pending' older than this has probably been decided

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def die(msg: str) -> None:
    print(f"\n[X] {msg}")
    sys.exit(1)


# A passed date only matters if it was a DEADLINE. Notes legitimately reference past events
# ("the July 31 injunction restored eligibility", "signed on June 26") and flagging those
# produced pure noise — Brenen Lorient's note was reported stale on 2026-08-19 for correctly
# describing a ruling that happened. Requiring deadline language keeps what the check is
# actually for: a decision that was pending by some date and now silently isn't.
DEADLINE_CUES = (
    "until", "deadline", "by ", "decide", "decision", "pending", "awaiting", "expected",
    "must ", "has to ", "window", "no later", "ahead of", "before ",
)


def _is_deadline(text: str, start: int, end: int) -> bool:
    """True if a deadline cue sits right next to this date.

    Proximity matters, not mere presence: Lorient's note says "the July 31 injunction ..."
    AND, two sentences later, "the appeal is still pending". A whole-text search sees
    'pending' and flags a date that is plainly historical. Only the words immediately
    around the date tell you which kind of date it is.
    """
    window = f"{text[max(0, start - 55):start]} {text[end:end + 30]}".lower()
    return any(cue in window for cue in DEADLINE_CUES)


def past_dates_in(text: str, today: date) -> list[date]:
    """Calendar dates in `text` that are already in the past AND read as a deadline —
    'YYYY-MM-DD' or 'Mon DD' / 'Month DD'. A month-name date is read as this year (a deadline
    is about the current cycle). A date with no deadline cue beside it is history, not staleness."""
    out: list[date] = []
    t = text or ""
    for m in re.finditer(r"\b(20\d\d)-(\d{2})-(\d{2})\b", t):
        try:
            d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            if d < today and _is_deadline(t, m.start(), m.end()):
                out.append(d)
        except ValueError:
            pass
    for m in re.finditer(r"\b([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?\b", t):
        mon = MONTHS.get(m.group(1)[:3].lower())
        day = int(m.group(2))
        if not mon or not (1 <= day <= 31):
            continue
        try:
            d = date(today.year, mon, day)
        except ValueError:
            continue
        if d < today and _is_deadline(t, m.start(), m.end()):
            out.append(d)
    return out


def days_since(iso: str, today: date) -> int | None:
    try:
        return (today - date.fromisoformat((iso or "")[:10])).days
    except ValueError:
        return None


def main() -> None:
    if not SB_URL or not SB_KEY:
        die("Missing SUPABASE_URL or SUPABASE_SECRET_KEY")
    sb = create_client(SB_URL, SB_KEY)
    today = date.today()
    findings: list[str] = []

    moves = sb.table("roster_moves").select(
        "player_name,sport_id,category,move_date,alert,notes").execute().data or []
    for m in moves:
        who = f"{m.get('player_name', '?')} ({m.get('sport_id', '?')})"
        # 1) A decision that should be resolved by now.
        if m.get("category") == "draft-pending":
            age = days_since(m.get("move_date"), today)
            if age is not None and age > PENDING_GRACE_DAYS:
                findings.append(f"PENDING {age}d — {who}: still 'draft-pending' — did they decide? "
                                f"| {(m.get('alert') or m.get('notes') or '').strip()}")
        # 2) A time-sensitive line whose date has passed.
        for field in ("alert", "notes"):
            for d in past_dates_in(m.get(field) or "", today):
                findings.append(f"PAST DATE {d.isoformat()} — {who}: {field} says "
                                f"\"{(m.get(field) or '').strip()}\"")

    depth = sb.table("depth_chart").select("player_name,sport_id,alert,note").execute().data or []
    for e in depth:
        who = f"{e.get('player_name', '?')} ({e.get('sport_id', '?')}, depth)"
        for field in ("alert", "note"):
            for d in past_dates_in(e.get(field) or "", today):
                findings.append(f"PAST DATE {d.isoformat()} — {who}: {field} says "
                                f"\"{(e.get(field) or '').strip()}\"")

    # de-dupe while preserving order
    findings = list(dict.fromkeys(findings))

    if not findings:
        print("No stale facts found. ✓")
        return

    print(f"\n{len(findings)} possible stale fact(s) to review:\n" + "-" * 60)
    for f in findings:
        print(f"  • {f}")
    print("-" * 60)

    if not email_configured():
        print("(email not configured — RESEND_API_KEY / REPORT_ALERT_TO — printed only, no email sent.)")
        return

    body = (f"{len(findings)} Mountaineer Pulse fact(s) may have gone stale — worth a look:\n\n"
            + "\n\n".join(f"• {f}" for f in findings)
            + "\n\n----\nFix in the data-pipeline JSON (roster_moves.json / depth_chart.json), "
            "then re-run sync_moves.py / sync_depth.py.\n")
    subject = f"[Mountaineer Pulse] {len(findings)} fact(s) to review (possible stale data)"
    try:
        send_email(subject, body)
        print("[OK] Emailed the review list.")
    except Exception as e:
        die(f"Email send failed: {str(e)[:160]}")


if __name__ == "__main__":
    main()
