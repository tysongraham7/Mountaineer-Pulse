"""
Mountaineer Pulse - Checks for metrics.py
=========================================
Builds a synthetic event stream with known answers and asserts the metrics come back
right. No database and no network: every definition in metrics.py -- what counts as a
session, who is eligible for a retention bucket, when a streak breaks -- is a judgement
call that is easy to change by accident, and this is what catches that.

Run:  python test_metrics.py
"""

import json
import os
import random
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import metrics
from metrics import ET

TODAY = datetime.now(ET).date()
random.seed(7)

def ev(uid, when, event, screen=None, dur=None):
    return {
        "anon_id": uid,
        "event": event,
        "screen": screen,
        "platform": "ios" if hash(uid) % 3 else "android",
        "app_version": "1.0.4",
        "duration_ms": dur,
        "created_at": when.astimezone(timezone.utc).isoformat(),
    }

rows = []

# --- Cohort A: 5 installs, 40 days ago, daily habit for 35 days (should retain hard) ---
for i in range(5):
    uid = f"loyal-{i}"
    first = datetime.now(ET) - timedelta(days=40)
    for day in range(36):
        t = (first + timedelta(days=day)).replace(hour=7, minute=30 + i)
        rows.append(ev(uid, t, "app_open"))
        rows.append(ev(uid, t + timedelta(seconds=2), "screen_view", "/"))
        rows.append(ev(uid, t + timedelta(seconds=40), "feature", "game_sheet_open"))
        rows.append(ev(uid, t + timedelta(seconds=95), "session_end", dur=95000))

# --- Cohort B: 8 installs, 35 days ago, one day only (pure churn) ---
for i in range(8):
    uid = f"bounce-{i}"
    t = (datetime.now(ET) - timedelta(days=35)).replace(hour=12, minute=i)
    rows.append(ev(uid, t, "app_open"))
    rows.append(ev(uid, t + timedelta(seconds=3), "screen_view", "/"))
    rows.append(ev(uid, t + timedelta(seconds=6), "session_end", dur=6000))

# --- Cohort C: 4 installs, 8 days ago, came back on day 1 and days 4-6 ---
for i in range(4):
    uid = f"mid-{i}"
    first = datetime.now(ET) - timedelta(days=8)
    for day in (0, 1, 4, 5, 6):
        t = (first + timedelta(days=day)).replace(hour=20, minute=10 + i)
        rows.append(ev(uid, t, "app_open"))
        rows.append(ev(uid, t + timedelta(seconds=1), "push_open"))
        rows.append(ev(uid, t + timedelta(seconds=5), "screen_view", "/news"))
        rows.append(ev(uid, t + timedelta(seconds=30), "feature", "news_story_open"))
        rows.append(ev(uid, t + timedelta(seconds=210), "session_end", dur=210000))

# --- Cohort D: 3 brand-new installs today ---
for i in range(3):
    uid = f"new-{i}"
    t = datetime.now(ET) - timedelta(minutes=20 + i)
    rows.append(ev(uid, t, "app_open"))
    rows.append(ev(uid, t + timedelta(seconds=2), "screen_view", "/"))
    # No session_end: simulates the app being killed. Should show up as "estimated".

# --- One visit containing two foreground spells 5 min apart: one session, summed length ---
t = (datetime.now(ET) - timedelta(days=2)).replace(hour=11, minute=0)
rows.append(ev("split-1", t, "app_open"))
rows.append(ev("split-1", t + timedelta(seconds=90), "session_end", dur=90000))
rows.append(ev("split-1", t + timedelta(minutes=5), "screen_view", "/"))
rows.append(ev("split-1", t + timedelta(minutes=6), "session_end", dur=60000))

# --- One install with two sessions in a day, separated by > 30 min ---
t = (datetime.now(ET) - timedelta(days=1)).replace(hour=9, minute=0)
rows.append(ev("twice-1", t, "app_open"))
rows.append(ev("twice-1", t + timedelta(seconds=60), "session_end", dur=60000))
rows.append(ev("twice-1", t + timedelta(hours=4), "app_open"))
rows.append(ev("twice-1", t + timedelta(hours=4, seconds=120), "session_end", dur=120000))

random.shuffle(rows)  # order must not matter
d = metrics.compute(rows, days=30)

fails = []
def check(name, got, want):
    ok = got == want
    print(f"  {'OK ' if ok else 'BAD'}  {name:38} got={got!r} want={want!r}")
    if not ok:
        fails.append(name)

print(f"\nSynthetic set: {len(rows)} events, {len({r['anon_id'] for r in rows})} installs\n")

h, s, r, p = d["headline"], d["sessions"], d["retention"], d["push"]

check("installs total", h["installs_total"], 5 + 8 + 4 + 3 + 1 + 1)
check("new today", h["new_today"], 3)
check("DAU (loyal 5 stopped at day 36 = 4d ago)", h["dau"], 3)
check("MAU", h["mau"], 5 + 4 + 3 + 1 + 1)

# Sessions: twice-1 has a 4-hour gap, so it must be TWO sessions, not one.
twice = [x for x in metrics._sessions({"twice-1": sorted(
    ({**e, "_at": metrics._parse(e["created_at"])} for e in rows if e["anon_id"] == "twice-1"),
    key=lambda e: e["_at"])}) ]
check("30-min gap splits sessions", len(twice), 2)
check("measured duration wins over inferred", twice[1]["ms"], 120000)
split = metrics._sessions({"split-1": sorted(
    ({**e, "_at": metrics._parse(e["created_at"])} for e in rows if e["anon_id"] == "split-1"),
    key=lambda e: e["_at"])})
check("spells inside one visit stay one session", len(split), 1)
check("measured spells are summed, not maxed", split[0]["ms"], 150000)

check("new installs w/o session_end are estimated", all(not x["exact"] for x in
      metrics._sessions({"new-0": sorted(
          ({**e, "_at": metrics._parse(e["created_at"])} for e in rows if e["anon_id"] == "new-0"),
          key=lambda e: e["_at"])})), True)

# Retention. Cohort B (bounce) installed 35d ago and never returned -> 0 kept.
# Cohort A (loyal) installed 40d ago and returned every day -> kept in all three.
check("D1 kept", r["d1"]["kept"], 5 + 4)          # loyal + mid (mid came back on day 1)
# twice-1 installed yesterday, so its day 1 (today) is still running -> not yet eligible.
check("D1 eligible excludes unfinished windows", r["d1"]["eligible"], 5 + 8 + 4 + 1)
check("D7 kept", r["d7"]["kept"], 5 + 4)
check("D30 kept (only loyal are 30d old AND returned)", r["d30"]["kept"], 5)
check("D30 eligible = installs past day 30", r["d30"]["eligible"], 5 + 8)

# Churn: bounce-* went quiet 35 days ago; loyal-* stopped 4 days ago (not lapsed).
check("lapsed = the 8 bouncers", d["churn"]["lapsed"], 8)

# Push: only cohort C fires push_open, 5 days each within the window.
check("push installs", p["users"], 4)
check("push sessions", p["sessions_from_push"], 4 * 5)

# Features
feat = {f["key"]: f["count"] for f in d["features"]}
check("news_story_open counted", feat.get("news_story_open"), 4 * 5)

# Streaks: loyal ran 36 consecutive days.
check("longest streak ever", d["streaks"]["longest_ever"], 36)

# Peak hour: loyal open at 07:30 every day for 36 days -> hour 7 dominates the 30d window.
check("peak hour", d["peak"]["peak_hour"], 7)

# Daily rows must cover every day in the window, including zeroes.
check("daily rows = window length", len(d["daily"]), 30)
check("daily rows sorted", d["daily"] == sorted(d["daily"], key=lambda x: x["date"]), True)

# JSON-serializable — the server does exactly this.
try:
    json.dumps(d)
    check("json serializable", True, True)
except TypeError as e:
    check("json serializable", f"TypeError: {e}", True)

# An empty table must not explode.
check("empty input handled", metrics.compute([], days=30)["empty"], True)

print(f"\n{'ALL CHECKS PASSED' if not fails else 'FAILED: ' + ', '.join(fails)}\n")
sys.exit(1 if fails else 0)
