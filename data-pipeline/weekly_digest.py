"""
Mountaineer Pulse - Weekly Digest Email
=======================================
The numbers you'd otherwise have to remember to go look at, pushed to you every Monday.

Deliberately week-over-week rather than a snapshot: "10 daily actives" means nothing on its
own, "10, up from 6" is the whole point. Every figure here is paired with the prior seven
days so a change is visible without doing arithmetic in your head.

Covers usage (installs, actives, opens, tabs, push), anything needing attention (unresolved
bug reports), what it all cost, and what's coming (next game + whether its scouting report
has been written yet).

Reuses the Resend setup already behind the bug-report alerts.

Env: SUPABASE_URL, SUPABASE_SECRET_KEY, RESEND_API_KEY, REPORT_ALERT_TO
Run:  python weekly_digest.py [--dry-run]      (--dry-run prints instead of sending)
"""

import os
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from supabase import create_client

from emailer import email_configured, send_email

load_dotenv()

SB_URL = os.getenv("SUPABASE_URL")
SB_KEY = os.getenv("SUPABASE_SECRET_KEY")

SCREEN_NAME = {"/": "Pulse", "/team": "Team", "/scores": "Scores", "/news": "News", "/you": "You"}
WINDOW_DAYS = 7


def die(msg: str) -> None:
    print(f"\n[X] {msg}")
    sys.exit(1)


def delta(now: float, before: float, unit: str = "") -> str:
    """'12 (+6)' / '3 (-2)' / '5 (=)'. The comparison is the reason this email exists, so
    it is never omitted — a flat week should read as flat, not as an unqualified number."""
    d = now - before
    if before == 0 and now == 0:
        return f"0{unit}"
    if d == 0:
        return f"{now:g}{unit} (=)"
    return f"{now:g}{unit} ({'+' if d > 0 else ''}{d:g})"


def main() -> None:
    dry = "--dry-run" in sys.argv
    if not SB_URL or not SB_KEY:
        die("Missing SUPABASE_URL or SUPABASE_SECRET_KEY")

    sb = create_client(SB_URL, SB_KEY)
    now = datetime.now(timezone.utc)
    this_start = now - timedelta(days=WINDOW_DAYS)
    prev_start = now - timedelta(days=WINDOW_DAYS * 2)

    ev = (sb.table("analytics_events").select("anon_id,event,screen,created_at")
          .gte("created_at", prev_start.isoformat()).execute().data or [])
    cur = [e for e in ev if e["created_at"] >= this_start.isoformat()]
    prev = [e for e in ev if e["created_at"] < this_start.isoformat()]

    def stats(rows):
        users = {r["anon_id"] for r in rows}
        opens = [r for r in rows if r["event"] == "app_open"]
        pushes = [r for r in rows if r["event"] == "push_open"]
        days = {r["created_at"][:10] for r in opens}
        # Average daily actives, not total uniques — total grows forever and stops meaning
        # anything; the daily average is what actually tracks whether people keep coming back.
        dau = (sum(len({r["anon_id"] for r in opens if r["created_at"][:10] == d}) for d in days)
               / len(days)) if days else 0
        return users, len(opens), len(pushes), round(dau, 1)

    u_cur, o_cur, p_cur, d_cur = stats(cur)
    u_prev, o_prev, p_prev, d_prev = stats(prev)

    all_ids = {r["anon_id"] for r in (sb.table("analytics_events").select("anon_id")
                                      .execute().data or [])}
    new_ids = u_cur - {r["anon_id"] for r in prev}

    L = [f"Mountaineer Pulse — week ending {now.date().isoformat()}", "=" * 46, "", "USAGE"]
    L.append(f"  Installs (all time)   {len(all_ids)}")
    L.append(f"  New this week         {len(new_ids)}")
    L.append(f"  Active users          {delta(len(u_cur), len(u_prev))}")
    L.append(f"  Avg daily actives     {delta(d_cur, d_prev)}")
    L.append(f"  App opens             {delta(o_cur, o_prev)}")
    L.append(f"  Push opens            {delta(p_cur, p_prev)}")

    views = Counter(SCREEN_NAME.get(r.get("screen") or "", r.get("screen") or "?")
                    for r in cur if r["event"] == "screen_view")
    if views:
        L += ["", "TABS (views this week)"]
        for name, n in views.most_common():
            L.append(f"  {name:<10} {n}")

    reports = (sb.table("error_reports").select("category,message,created_at,resolved")
               .gte("created_at", this_start.isoformat()).order("created_at", desc=True)
               .execute().data or [])
    open_all = (sb.table("error_reports").select("id").eq("resolved", False).execute().data or [])
    L += ["", f"BUG REPORTS — {len(reports)} this week, {len(open_all)} unresolved total"]
    for r in reports[:6]:
        msg = " ".join((r.get("message") or "").split())[:90]
        L.append(f"  [{r.get('category') or '?'}] {r['created_at'][:10]}  {msg}")
    if not reports:
        L.append("  (none)")

    def spend(since, until=None):
        q = sb.table("api_usage").select("cost_usd,created_at").gte("created_at", since.isoformat())
        rows = q.execute().data or []
        if until:
            rows = [r for r in rows if r["created_at"] < until.isoformat()]
        return sum(float(r["cost_usd"] or 0) for r in rows)

    c_now, c_prev = spend(this_start), spend(prev_start, this_start)
    L += ["", "CLAUDE SPEND",
          f"  This week             ${c_now:.2f}",
          f"  Prior week            ${c_prev:.2f}",
          f"  Per day               ${c_now / WINDOW_DAYS:.2f}"]

    nxt = (sb.table("games").select("id,start_date,home_team,away_team,is_wvu_home,sport_id,venue")
           .neq("status", "final").gte("start_date", now.isoformat())
           .order("start_date").limit(1).execute().data or [])
    if nxt:
        g = nxt[0]
        opp = g["away_team"] if g.get("is_wvu_home") else g["home_team"]
        days = (datetime.fromisoformat(g["start_date"]) - now).days
        L += ["", "NEXT GAME",
              f"  {'vs' if g.get('is_wvu_home') else 'at'} {opp} — {g['start_date'][:10]} ({days}d)"]
        rep = (sb.table("matchups").select("generated_at")
               .eq("game_id", g["id"]).execute().data or [])
        written = f"written {rep[0]['generated_at'][:10]}" if rep else "not yet (writes ~10d out)"
        L.append(f"  Scouting report       {written}")

    body = "\n".join(L)
    print(body)

    if dry:
        print("\n[dry run] Not sent.")
        return
    if not email_configured():
        print("\n(email not configured — set RESEND_API_KEY and REPORT_ALERT_TO)")
        return
    send_email(f"Mountaineer Pulse weekly — {len(u_cur)} active, {len(new_ids)} new", body)
    print("\n[OK] Weekly digest sent.")


if __name__ == "__main__":
    main()
