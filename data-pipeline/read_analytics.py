"""
Mountaineer Pulse - Read anonymous usage analytics
==================================================
The app logs privacy-first, anonymous events (a random per-install id, no PII) to the
`analytics_events` table, which the app itself cannot read back. This reads them with the
secret key and prints the numbers that matter during the beta:

  * Daily-active users (are people coming back?)
  * New vs. returning installs (is anything sticky?)
  * Push opens (does the morning briefing pull people in?)
  * Which tabs get used

  python read_analytics.py          # last 14 days
  python read_analytics.py 30       # last 30 days

Needs SUPABASE_URL + SUPABASE_SECRET_KEY in .env.
"""

import os
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

SB_URL = os.getenv("SUPABASE_URL")
SB_KEY = os.getenv("SUPABASE_SECRET_KEY")

# Route path -> friendly tab name.
SCREEN_NAME = {
    "/": "Pulse", "/index": "Pulse", "/scores": "Scores", "/news": "News",
    "/team": "Team", "/you": "You",
}


def die(msg: str) -> None:
    print(f"\n[X] {msg}")
    sys.exit(1)


def day_of(iso: str) -> str:
    return (iso or "")[:10]


def main() -> None:
    if not SB_URL or not SB_KEY:
        die("Missing SUPABASE_URL or SUPABASE_SECRET_KEY in .env")
    days = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 14
    sb = create_client(SB_URL, SB_KEY)

    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    rows = (sb.table("analytics_events")
            .select("anon_id,event,screen,platform,created_at")
            .gte("created_at", since).order("created_at").execute().data or [])

    if not rows:
        print(f"No events in the last {days} days yet. "
              "Once a build with analytics is out and someone opens it, numbers show up here.")
        return

    opens = [r for r in rows if r["event"] == "app_open"]
    push_opens = [r for r in rows if r["event"] == "push_open"]
    screens = [r for r in rows if r["event"] == "screen_view"]

    # Distinct installs, and which days each was active (for new/returning + retention).
    days_active: dict[str, set[str]] = defaultdict(set)
    first_seen: dict[str, str] = {}
    for r in opens:
        d = day_of(r["created_at"])
        days_active[r["anon_id"]].add(d)
        first_seen[r["anon_id"]] = min(first_seen.get(r["anon_id"], d), d)

    total_users = len(days_active)
    returning = sum(1 for u, ds in days_active.items() if len(ds) >= 2)

    print(f"\nMountaineer Pulse — usage, last {days} days")
    print("=" * 56)
    print(f"  Installs seen        {total_users}")
    print(f"  Returning (2+ days)  {returning}"
          f"  ({round(100 * returning / total_users)}% of seen)" if total_users else "")
    print(f"  App opens            {len(opens)}")

    # Daily-active users + opens per day.
    by_day_users: dict[str, set[str]] = defaultdict(set)
    by_day_opens: dict[str, int] = defaultdict(int)
    for r in opens:
        d = day_of(r["created_at"])
        by_day_users[d].add(r["anon_id"])
        by_day_opens[d] += 1
    new_by_day: dict[str, int] = defaultdict(int)
    for u, fd in first_seen.items():
        new_by_day[fd] += 1

    print("\n  Daily active users")
    print("  " + "-" * 46)
    print(f"  {'date':<12}{'users':>7}{'opens':>7}{'new':>6}")
    end = date.today()
    start = end - timedelta(days=days - 1)
    d = start
    while d <= end:
        k = d.isoformat()
        u = len(by_day_users.get(k, set()))
        if u or by_day_opens.get(k):
            print(f"  {k:<12}{u:>7}{by_day_opens.get(k, 0):>7}{new_by_day.get(k, 0):>6}")
        d += timedelta(days=1)

    # Push opens.
    push_users = {r["anon_id"] for r in push_opens}
    print(f"\n  Push opens           {len(push_opens)}  (from {len(push_users)} install(s))")
    if opens:
        pushday: dict[str, int] = defaultdict(int)
        for r in push_opens:
            pushday[day_of(r["created_at"])] += 1
        if pushday:
            recent = sorted(pushday.items())[-5:]
            print("    recent: " + ", ".join(f"{k[5:]}: {v}" for k, v in recent))

    # Tab usage.
    tab_views: dict[str, int] = defaultdict(int)
    tab_users: dict[str, set[str]] = defaultdict(set)
    for r in screens:
        name = SCREEN_NAME.get(r.get("screen") or "", r.get("screen") or "?")
        tab_views[name] += 1
        tab_users[name].add(r["anon_id"])
    if tab_views:
        print("\n  Tab usage")
        print("  " + "-" * 46)
        print(f"  {'tab':<12}{'views':>7}{'users':>7}")
        for name, v in sorted(tab_views.items(), key=lambda x: -x[1]):
            print(f"  {name:<12}{v:>7}{len(tab_users[name]):>7}")

    # Platform split.
    plats: dict[str, set[str]] = defaultdict(set)
    for r in opens:
        plats[r.get("platform") or "?"].add(r["anon_id"])
    if plats:
        print("\n  Platform: " + ", ".join(f"{k} {len(v)}" for k, v in plats.items()))
    print("=" * 56)


if __name__ == "__main__":
    main()
