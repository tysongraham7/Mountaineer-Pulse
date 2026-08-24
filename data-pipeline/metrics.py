"""
Mountaineer Pulse - Analytics metrics
=====================================
Turns the raw `analytics_events` stream into every number the dashboard shows. Pure
computation: it takes a list of event rows and gives back a dict. Nothing here touches the
network except fetch_events(), so the maths can be checked against a handful of fake rows
without a database.

Two things are worth knowing before trusting any number below.

  1. Everything is bucketed in Eastern time, not UTC. A 9pm kickoff in Morgantown is the
     next calendar day in UTC, so UTC buckets would scatter one game night across two days
     and make every daily figure quietly wrong.

  2. An "install" is a random per-install id, not a person. Reinstalling, or clearing the
     app's data, mints a new one. So installs skew slightly high and retention slightly
     low -- the opposite of the direction that would flatter us, which is the safer way to
     be wrong.
"""

import os
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

# A stretch of activity with no gap longer than this is one session. 30 minutes is the
# common convention, and it matches the app's own app_open throttle, so the two agree on
# what "still the same visit" means.
SESSION_GAP = timedelta(minutes=30)

# Sessions longer than this are a phone left awake, not attention. The app already declines
# to report them; this is the same guard applied to sessions we infer here.
MAX_SESSION_MS = 4 * 60 * 60 * 1000

# Route path -> the tab name a human would use.
SCREEN_NAME = {
    "/": "Pulse", "/index": "Pulse", "/scores": "Scores", "/news": "News",
    "/team": "Team", "/you": "You",
}

# Feature key -> label. Keep in step with FEATURES in mobile/src/lib/analytics.ts.
FEATURE_NAME = {
    "game_sheet_open": "Opened a game sheet",
    "player_profile_open": "Opened a player profile",
    "pulse_detail_open": "Opened Pulse detail",
    "news_story_open": "Tapped through to a story",
    "roster_move_source_open": "Opened a roster-move source",
    "team_mode_switch": "Switched Team view",
    "favorite_toggle": "Favorited a sport",
    "report_open": "Opened the report form",
}


# --------------------------------------------------------------------------------------
# Fetching
# --------------------------------------------------------------------------------------

def fetch_events(sb, page: int = 1000) -> list[dict]:
    """Every analytics event, oldest first.

    Deliberately unbounded rather than windowed: "is this a new install" can only be
    answered against an install's whole history, so a 30-day fetch would relabel every
    long-time user as new the moment they opened the app again.

    PostgREST caps a response at 1000 rows, so this pages. At beta volume the whole table
    is a few seconds; if it ever gets slow, the fix is a server-side aggregate rather than
    a shorter window, which would break the definitions above.
    """
    out: list[dict] = []
    start = 0
    while True:
        rows = (sb.table("analytics_events")
                .select("anon_id,event,screen,platform,app_version,duration_ms,created_at")
                .order("created_at")
                .range(start, start + page - 1)
                .execute().data or [])
        out.extend(rows)
        if len(rows) < page:
            return out
        start += page


# --------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------

def _parse(iso: str) -> datetime | None:
    """Postgres timestamptz -> aware datetime in Eastern."""
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(ET)
    except ValueError:
        return None


def _pct(num: int, den: int) -> float | None:
    """Percentage, or None when there's nothing to divide by.

    None rather than 0.0 on purpose: the dashboard renders it as an em dash. "0% retention"
    and "nobody has been eligible for this bucket yet" are completely different facts and
    should never look the same.
    """
    return round(100 * num / den, 1) if den else None


def _day_span(start: date, end: date) -> list[date]:
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


# --------------------------------------------------------------------------------------
# Sessionization
# --------------------------------------------------------------------------------------

def _sessions(by_user: dict[str, list[dict]]) -> list[dict]:
    """Split each install's event stream into sessions on a 30-minute gap.

    Length comes from the app's own session_end measurement when it's there. When it isn't
    -- the OS killed the app, or the install is on a build from before session_end existed
    -- we fall back to the span from the session's first event to its last, and mark it
    estimated. That fallback reads a one-screen visit as zero seconds, which is why the
    two are counted separately everywhere they surface.
    """
    out: list[dict] = []
    for uid, evs in by_user.items():
        cur: list[dict] = []
        for e in evs:
            if cur and e["_at"] - cur[-1]["_at"] > SESSION_GAP:
                out.append(_close(uid, cur))
                cur = []
            cur.append(e)
        if cur:
            out.append(_close(uid, cur))
    return out


def _close(uid: str, evs: list[dict]) -> dict:
    # Summed, not maxed. A visit can contain more than one measured stretch -- the user
    # steps out for two minutes and comes back inside the 30-minute window, which is still
    # one visit but two foreground spells. The honest length of that visit is the time
    # actually spent looking at the app, which is the sum.
    measured = [int(e["duration_ms"]) for e in evs
                if e["event"] == "session_end" and e.get("duration_ms")]
    if measured:
        ms, exact = sum(measured), True
    else:
        ms, exact = int((evs[-1]["_at"] - evs[0]["_at"]).total_seconds() * 1000), False
    return {
        "user": uid,
        "start": evs[0]["_at"],
        "ms": min(ms, MAX_SESSION_MS),
        "exact": exact,
        "events": len(evs),
        "from_push": any(e["event"] == "push_open" for e in evs),
        "day": evs[0]["_at"].date(),
    }


# --------------------------------------------------------------------------------------
# The main computation
# --------------------------------------------------------------------------------------

def compute(events: list[dict], days: int = 30, today: date | None = None) -> dict:
    """Every metric, from every event ever. `days` sets the reporting window only."""
    today = today or datetime.now(ET).date()
    window_start = today - timedelta(days=days - 1)

    rows = []
    for r in events:
        at = _parse(r.get("created_at") or "")
        if at:
            rows.append({**r, "_at": at})
    rows.sort(key=lambda r: r["_at"])

    if not rows:
        return {"empty": True, "days": days,
                "generated_at": datetime.now(ET).isoformat()}

    by_user: dict[str, list[dict]] = defaultdict(list)
    active_days: dict[str, set[date]] = defaultdict(set)
    first_seen: dict[str, date] = {}
    last_seen: dict[str, date] = {}
    for r in rows:
        uid, d = r["anon_id"], r["_at"].date()
        by_user[uid].append(r)
        active_days[uid].add(d)
        first_seen.setdefault(uid, d)
        last_seen[uid] = d

    sessions = _sessions(by_user)
    win_rows = [r for r in rows if r["_at"].date() >= window_start]
    win_sessions = [s for s in sessions if s["day"] >= window_start]

    def actives(start: date, end: date) -> set[str]:
        return {u for u, ds in active_days.items() if any(start <= d <= end for d in ds)}

    dau = actives(today, today)
    wau = actives(today - timedelta(days=6), today)
    mau = actives(today - timedelta(days=29), today)
    win_actives = actives(window_start, today)

    return {
        "empty": False,
        "days": days,
        "generated_at": datetime.now(ET).isoformat(),
        "window": {"start": window_start.isoformat(), "end": today.isoformat()},
        "headline": _headline(dau, wau, mau, first_seen, today, win_sessions, sessions, rows),
        "daily": _daily(window_start, today, active_days, first_seen, rows, sessions),
        "retention": _retention(first_seen, active_days, today),
        "cohorts": _cohorts(first_seen, active_days, today),
        "churn": _churn(first_seen, last_seen, active_days, today),
        "sessions": _session_stats(win_sessions),
        "peak": _peak(win_sessions),
        "features": _features(win_rows, len(win_actives)),
        "tabs": _tabs(win_rows),
        "streaks": _streaks(active_days, today),
        "push": _push(win_rows, win_sessions, win_actives),
        "engagement": _engagement(dau, mau, win_rows, active_days, window_start, today),
        "platforms": _split(rows, "platform"),
        "versions": _split(rows, "app_version"),
        "downloads": _downloads(first_seen, window_start, today),
        "hourly": _hourly(rows, sessions, first_seen),
        "arrivals": _arrivals(rows, by_user, first_seen, active_days, sessions),
    }


def _headline(dau, wau, mau, first_seen, today, win_sessions, sessions, rows) -> dict:
    exact = [s["ms"] for s in win_sessions if s["exact"]]
    return {
        "dau": len(dau),
        "wau": len(wau),
        "mau": len(mau),
        "installs_total": len(first_seen),
        "new_today": sum(1 for d in first_seen.values() if d == today),
        "new_7d": sum(1 for d in first_seen.values() if d > today - timedelta(days=7)),
        "sessions_today": sum(1 for s in sessions if s["day"] == today),
        # The headline number only ever uses measured sessions. An average that silently
        # blended real durations with first-to-last-event guesses would drift as the mix
        # of app versions changes, which looks like a behaviour change and isn't one.
        "avg_session_sec": round(sum(exact) / len(exact) / 1000) if exact else None,
        "avg_session_basis": len(exact),
        "events_total": len(rows),
        "stickiness": _pct(len(dau), len(mau)),
    }


def _daily(start, end, active_days, first_seen, rows, sessions) -> list[dict]:
    """One row per day in the window, including zero days -- a gap in usage is a finding."""
    per_day_users: dict[date, set[str]] = defaultdict(set)
    for u, ds in active_days.items():
        for d in ds:
            per_day_users[d].add(u)

    opens = Counter(r["_at"].date() for r in rows if r["event"] == "app_open")
    pushes = Counter(r["_at"].date() for r in rows if r["event"] == "push_open")
    new = Counter(first_seen.values())
    sess = Counter(s["day"] for s in sessions)
    dur: dict[date, list[int]] = defaultdict(list)
    for s in sessions:
        if s["exact"]:
            dur[s["day"]].append(s["ms"])

    out = []
    for d in _day_span(start, end):
        ms = dur.get(d, [])
        out.append({
            "date": d.isoformat(),
            "dau": len(per_day_users.get(d, ())),
            "new": new.get(d, 0),
            "opens": opens.get(d, 0),
            "sessions": sess.get(d, 0),
            "push_opens": pushes.get(d, 0),
            "avg_session_sec": round(sum(ms) / len(ms) / 1000) if ms else None,
        })
    return out


def _retention(first_seen, active_days, today) -> dict:
    """Day-1 / Day-7 / Day-30 retention, bracketed rather than exact-day.

    Exact-day retention ("came back on precisely day 7") is the stricter definition and is
    the wrong tool at this scale: with a few dozen installs it reads 0% most weeks whether
    the app is loved or ignored. Bracketed retention -- came back at all within the window
    -- moves with reality at small n.

    Only cohorts whose window has fully elapsed are counted, and "elapsed" means the last
    day of the bracket is itself over -- hence `> hi`, not `>= hi`. Someone who installed
    yesterday is still living their day 1; counting them now would put them in the
    denominator while they still have most of the window left to come back in, which reads
    as churn that hasn't happened. That is not hypothetical here: a launch spike lands
    dozens of installs in one day, and at `>= hi` the whole spike would enter the D1
    denominator the next morning and halve the number overnight.
    """
    buckets = {"d1": (1, 1), "d7": (2, 7), "d30": (8, 30)}
    out: dict = {}
    for key, (lo, hi) in buckets.items():
        eligible = [u for u, f in first_seen.items() if (today - f).days > hi]
        kept = 0
        for u in eligible:
            f = first_seen[u]
            if any(lo <= (d - f).days <= hi for d in active_days[u]):
                kept += 1
        out[key] = {"kept": kept, "eligible": len(eligible),
                    "pct": _pct(kept, len(eligible))}
    out["basis"] = "bracketed: D1 = day 1, D7 = days 2-7, D30 = days 8-30 after install"
    return out


def _cohorts(first_seen, active_days, today, weeks: int = 8) -> list[dict]:
    """Weekly install cohorts and what share of each was still active N weeks later.

    The single most useful table here: it separates "retention is improving" from "we just
    got a burst of new installs", which every headline number confuses.
    """
    def monday(d: date) -> date:
        return d - timedelta(days=d.weekday())

    this_week = monday(today)
    starts = [this_week - timedelta(weeks=i) for i in range(weeks - 1, -1, -1)]
    members: dict[date, list[str]] = defaultdict(list)
    for u, f in first_seen.items():
        m = monday(f)
        if m >= starts[0]:
            members[m].append(u)

    out = []
    for wk in starts:
        users = members.get(wk, [])
        row: dict = {"week": wk.isoformat(), "size": len(users), "cells": []}
        for i in range(weeks):
            lo, hi = wk + timedelta(weeks=i), wk + timedelta(weeks=i, days=6)
            if lo > today:
                break
            kept = sum(1 for u in users if any(lo <= d <= hi for d in active_days[u]))
            row["cells"].append({
                "week_index": i,
                "kept": kept,
                "pct": _pct(kept, len(users)),
                # A week still in progress can only go up, so the dashboard greys it rather
                # than letting a Monday reading look like a collapse.
                "partial": hi > today,
            })
        out.append(row)
    return out


def _churn(first_seen, last_seen, active_days, today) -> dict:
    """Two readings, because "churn" means different things at different scales.

    `lapsed` is the plain-language one: installs that have gone quiet for 14+ days. At beta
    size it's the number to watch, because it counts actual people you could name.

    `window` is the textbook one: of the installs active in the 30 days before last, what
    share didn't come back in the last 30. It needs 60 days of history to say anything, so
    it stays null until there is that much.
    """
    total = len(first_seen)
    lapsed = sum(1 for d in last_seen.values() if (today - d).days >= 14)
    # Never counted as lapsed: someone who installed 3 days ago can't have been quiet 14.
    fresh = sum(1 for f in first_seen.values() if (today - f).days < 14)

    prev_lo, prev_hi = today - timedelta(days=59), today - timedelta(days=30)
    cur_lo = today - timedelta(days=29)
    prior = {u for u, ds in active_days.items() if any(prev_lo <= d <= prev_hi for d in ds)}
    still = {u for u in prior if any(d >= cur_lo for d in active_days[u])}
    have_history = (today - min(first_seen.values())).days >= 60

    return {
        "lapsed": lapsed,
        "lapsed_pct": _pct(lapsed, total - fresh),
        "eligible": total - fresh,
        "window_pct": (_pct(len(prior) - len(still), len(prior))
                       if have_history and prior else None),
        "window_prior": len(prior),
    }


def _session_stats(sessions) -> dict:
    exact = sorted(s["ms"] for s in sessions if s["exact"])
    est = [s for s in sessions if not s["exact"]]
    users = {s["user"] for s in sessions}

    def median(xs):
        if not xs:
            return None
        mid = len(xs) // 2
        return xs[mid] if len(xs) % 2 else (xs[mid - 1] + xs[mid]) // 2

    return {
        "total": len(sessions),
        "users": len(users),
        "per_user": round(len(sessions) / len(users), 2) if users else None,
        "measured": len(exact),
        "estimated": len(est),
        "avg_sec": round(sum(exact) / len(exact) / 1000) if exact else None,
        "median_sec": round(median(exact) / 1000) if exact else None,
        "longest_sec": round(exact[-1] / 1000) if exact else None,
        # How the visits split by depth. Averages hide a bimodal app -- a glance at the
        # score and a real read are different products, and this is where that shows.
        "buckets": _session_buckets(exact),
    }


def _session_buckets(ms_list) -> list[dict]:
    edges = [(0, 10, "under 10s"), (10, 30, "10-30s"), (30, 60, "30-60s"),
             (60, 180, "1-3 min"), (180, 600, "3-10 min"), (600, None, "10 min+")]
    out = []
    for lo, hi, label in edges:
        n = sum(1 for ms in ms_list
                if ms / 1000 >= lo and (hi is None or ms / 1000 < hi))
        out.append({"label": label, "count": n, "pct": _pct(n, len(ms_list))})
    return out


def _peak(sessions) -> dict:
    """When people actually open the app, in Eastern time.

    Counted per session start, not per event: a long visit that fires forty screen_views
    would otherwise outvote forty separate people opening the app once.
    """
    hours = [0] * 24
    grid = [[0] * 24 for _ in range(7)]  # Monday-first, matching weekday()
    for s in sessions:
        h, wd = s["start"].hour, s["start"].weekday()
        hours[h] += 1
        grid[wd][h] += 1
    best = max(range(24), key=lambda h: hours[h]) if any(hours) else None
    return {
        "hours": hours,
        "grid": grid,
        "peak_hour": best,
        "peak_count": hours[best] if best is not None else 0,
        "dow": [sum(row) for row in grid],
    }


def _features(rows, active_users: int) -> list[dict]:
    counts: Counter = Counter()
    users: dict[str, set[str]] = defaultdict(set)
    for r in rows:
        if r["event"] != "feature":
            continue
        key = r.get("screen") or "?"
        counts[key] += 1
        users[key].add(r["anon_id"])
    return [{
        "key": k,
        "label": FEATURE_NAME.get(k, k),
        "count": n,
        "users": len(users[k]),
        "reach": _pct(len(users[k]), active_users),
    } for k, n in counts.most_common()]


def _tabs(rows) -> list[dict]:
    views: Counter = Counter()
    users: dict[str, set[str]] = defaultdict(set)
    for r in rows:
        if r["event"] != "screen_view":
            continue
        name = SCREEN_NAME.get(r.get("screen") or "", r.get("screen") or "?")
        views[name] += 1
        users[name].add(r["anon_id"])
    return [{"tab": k, "views": n, "users": len(users[k])} for k, n in views.most_common()]


def _streaks(active_days, today) -> dict:
    """Consecutive-day runs per install.

    A current streak may end today or yesterday. Requiring it to include today would zero
    out everyone who simply hasn't opened the app yet this morning, and the dashboard is
    most often read in the morning.
    """
    current: dict[str, int] = {}
    longest_all = 0
    for u, ds in active_days.items():
        days_sorted = sorted(ds)
        run = best = 1
        for a, b in zip(days_sorted, days_sorted[1:]):
            run = run + 1 if (b - a).days == 1 else 1
            best = max(best, run)
        longest_all = max(longest_all, best)

        anchor = days_sorted[-1]
        if (today - anchor).days <= 1:
            n, d = 0, anchor
            while d in ds:
                n += 1
                d -= timedelta(days=1)
            current[u] = n

    top = sorted(current.items(), key=lambda kv: -kv[1])[:10]
    return {
        "longest_ever": longest_all,
        "on_streak_3": sum(1 for n in current.values() if n >= 3),
        "on_streak_7": sum(1 for n in current.values() if n >= 7),
        "active_streaks": len(current),
        "top": [{"user": u[:8], "days": n} for u, n in top if n > 1],
    }


def _push(rows, sessions, active_users: set[str]) -> dict:
    """Did the notification actually bring anyone back?

    `sessions_from_push` is the honest version of that question: not how many taps there
    were, but how many visits a notification started.
    """
    opens = [r for r in rows if r["event"] == "push_open"]
    users = {r["anon_id"] for r in opens}
    from_push = [s for s in sessions if s["from_push"]]
    exact = [s["ms"] for s in from_push if s["exact"]]
    other = [s["ms"] for s in sessions if not s["from_push"] and s["exact"]]
    return {
        "opens": len(opens),
        "users": len(users),
        "reach": _pct(len(users), len(active_users)),
        "sessions_from_push": len(from_push),
        "share_of_sessions": _pct(len(from_push), len(sessions)),
        # Whether a notification-driven visit is a real visit or a bounce. If push sessions
        # are consistently shorter, the alerts are pulling people in for nothing.
        "avg_push_session_sec": round(sum(exact) / len(exact) / 1000) if exact else None,
        "avg_other_session_sec": round(sum(other) / len(other) / 1000) if other else None,
    }


def _engagement(dau, mau, rows, active_days, start, end) -> dict:
    users = {r["anon_id"] for r in rows}
    span = (end - start).days + 1
    days_each = [len([d for d in active_days[u] if start <= d <= end]) for u in users]
    return {
        "stickiness": _pct(len(dau), len(mau)),
        "events_per_user": round(len(rows) / len(users), 1) if users else None,
        "active_days_avg": round(sum(days_each) / len(days_each), 1) if days_each else None,
        "active_days_span": span,
        # Power users: active on a third or more of the days in the window.
        "power_users": sum(1 for n in days_each if n >= max(2, span // 3)),
    }


def _split(rows, field: str) -> list[dict]:
    users: dict[str, set[str]] = defaultdict(set)
    for r in rows:
        users[r.get(field) or "unknown"].add(r["anon_id"])
    return sorted(
        ({"name": k, "users": len(v)} for k, v in users.items()),
        key=lambda x: -x["users"],
    )


def _hourly(rows, sessions, first_seen, hours: int = 24) -> list[dict]:
    """The last 24 hours, hour by hour.

    A day-resolution chart can't answer "when did that install land" -- at day granularity
    every arrival today is one bar. This is the same data at the resolution the question
    is actually asked at. Rolling from the current hour rather than from midnight, because
    at 6am a midnight-anchored "today" is six empty bars and yesterday evening -- the part
    you'd actually want to see -- has fallen off the end.
    """
    now = datetime.now(ET).replace(minute=0, second=0, microsecond=0)
    starts = [now - timedelta(hours=i) for i in range(hours - 1, -1, -1)]
    cutoff = starts[0]

    first_at: dict[str, datetime] = {}
    for r in rows:
        first_at.setdefault(r["anon_id"], r["_at"])

    def bucket(dt: datetime) -> datetime:
        return dt.replace(minute=0, second=0, microsecond=0)

    installs: Counter = Counter(bucket(t) for t in first_at.values() if t >= cutoff)
    sess: Counter = Counter(bucket(x["start"]) for x in sessions if x["start"] >= cutoff)
    users: dict[datetime, set[str]] = defaultdict(set)
    events: Counter = Counter()
    for r in rows:
        if r["_at"] < cutoff:
            continue
        b = bucket(r["_at"])
        users[b].add(r["anon_id"])
        events[b] += 1

    return [{
        "hour": h.isoformat(),
        "label": h.strftime("%-I%p").lower() if os.name != "nt" else h.strftime("%#I%p").lower(),
        "installs": installs.get(h, 0),
        "sessions": sess.get(h, 0),
        "actives": len(users.get(h, ())),
        "events": events.get(h, 0),
    } for h in starts]


def _arrivals(rows, by_user, first_seen, active_days, sessions, limit: int = 200) -> list[dict]:
    """Every new install of the last 30 days, newest first, with the moment it arrived.

    This is the arrival of an install, not of a download: it's stamped when the app is first
    opened. Nobody can give you the download itself -- App Store Connect and Play Console
    both report daily totals with no per-download time -- so first-open is the finest
    resolution that exists, and unlike the store figures it's live.

    `returned` is the column worth reading. An arrival that never came back on a later day
    is a download that didn't land, and at beta scale you can still do something about each
    one individually.
    """
    cutoff = datetime.now(ET).date() - timedelta(days=30)
    first_at: dict[str, datetime] = {}
    for r in rows:
        first_at.setdefault(r["anon_id"], r["_at"])

    sess_by_user: dict[str, list[dict]] = defaultdict(list)
    for x in sessions:
        sess_by_user[x["user"]].append(x)

    out = []
    for uid, day in first_seen.items():
        if day < cutoff:
            continue
        evs = by_user[uid]
        at = first_at[uid]
        first_session = min(sess_by_user[uid], key=lambda x: x["start"], default=None)
        # The first screen they landed on, which for a push-driven install is the story
        # they were sent to rather than the home tab.
        opening = next((SCREEN_NAME.get(e.get("screen") or "", e.get("screen"))
                        for e in evs if e["event"] == "screen_view"), None)
        out.append({
            "at": at.isoformat(),
            "platform": evs[0].get("platform") or "?",
            "version": evs[0].get("app_version") or "?",
            "events": len(evs),
            "sessions": len(sess_by_user[uid]),
            "days_active": len(active_days[uid]),
            "returned": len(active_days[uid]) > 1,
            "first_screen": opening,
            "from_push": any(e["event"] == "push_open" for e in evs),
            "first_session_sec": (round(first_session["ms"] / 1000)
                                  if first_session and first_session["exact"] else None),
            "last_at": evs[-1]["_at"].isoformat(),
        })
    out.sort(key=lambda x: x["at"], reverse=True)
    return out[:limit]


def _downloads(first_seen, start, end) -> dict:
    """Installs that opened the app -- a proxy for downloads, not the real figure.

    The real one lives in App Store Connect and Play Console and lags a day or two, so it
    could never drive a live panel anyway. `store` stays None until those APIs are wired up;
    the dashboard shows the gap rather than pretending this number is the same thing.
    """
    per_day = Counter(first_seen.values())
    return {
        "proxy_total": len(first_seen),
        "proxy_window": sum(n for d, n in per_day.items() if start <= d <= end),
        "store": None,
        "note": "Installs that opened the app at least once. Real download counts "
                "(including downloads that never opened) need the App Store Connect "
                "and Play Console APIs.",
    }
