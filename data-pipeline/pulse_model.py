"""
Mountaineer Pulse - Shared Scoring Model
========================================
ONE formula, used by both compute_pulse.py (today's number) and backfill_pulse.py
(the chart history), so the number and the line always agree and every change is
tied to something tangible (a game, a ranking, or a roster move).

Score = anchor (national standing) + form (recent games) + roster (moves) + surge.

  * anchor  - a ranked team is anchored to its national rank (#1~81, #25~61), kept
              below the cap so form/roster/surge have room to move it (an elite team
              lands in the 90s, not pinned at 99). The ranking's weight grows over the
              season. Unranked -> record-based.
  * form    - recent regular-season form vs season average (+/-6). Reactive to games.
  * roster  - portal/recruiting/eligibility moves, weighted & capped (+/-24).
  * surge   - NET postseason result (wins - losses), so a deep run that ends in a
              loss pulls the score back instead of only ratcheting up.
  * news    - a SIGNED, HELD move from notable news. AI daily notes nudge -2..+2;
              curated big events carry an exact hand-set number (e.g. -4). No fade,
              so the line reacts BOTH ways and stays there until later news offsets it.
"""

import requests

ESPN_PATH = {
    "football": "football/college-football",
    "mbb": "basketball/mens-college-basketball",
    "baseball": "baseball/college-baseball",
}
FULL_SEASON = {"football": 12, "mbb": 31, "baseball": 56}  # ~games in a full season
UA = {"User-Agent": "Mozilla/5.0"}


def is_postseason(sport: str, d) -> bool:
    """True if a game on date `d` is postseason. Handled per sport because the
    basketball season WRAPS the calendar year (Nov-Apr), so a naive month cutoff
    would flag November/December (early season) as postseason."""
    if sport == "football":
        return d.month in (12, 1)                                   # Dec-Jan bowls/playoff
    if sport == "mbb":
        return (d.month == 3 and d.day >= 12) or d.month == 4       # mid-March + early April
    if sport == "baseball":
        return (d.month == 5 and d.day >= 20) or d.month in (6, 7)  # late May onward
    return False

# Roster-move weight by (category, direction). Additions weigh MORE than losses
# (a new commit is a bigger positive signal than a departure is negative), and
# expected attrition (graduation/eligibility/draft) is lightest. Weights are kept
# modest and the cap generous so a high-volume offseason keeps moving the line
# (each move nudges it) instead of saturating and going flat.
CAT_WEIGHT = {
    ("transfer", "in"): 1.0, ("transfer", "out"): -0.4,
    ("juco", "in"): 0.8,
    ("recruit", "in"): 0.7, ("hs", "in"): 0.7,
    # Losing a PROVEN player (a graduating/eligibility-exhausted starter, or an
    # underclassman leaving early for the pro draft) is a real subtraction — heavier
    # than a portal-out (often depth). Draft-outs weigh most: you only lose your best
    # players that way. Transfer-out stays modest so a high-portal-churn football
    # roster isn't over-penalized (its departures are almost all transfers).
    ("graduation", "out"): -0.6, ("eligibility", "out"): -0.6, ("draft", "out"): -1.0,
}
ROSTER_CAP = 24.0  # max +/- the roster component can swing the score
IMPACT_MULT = 1.7  # a marquee move (impact="high") weighs more — a 5-star add OR a drafted/star loss

# Per-sport roster-move weighting. Basketball (~13-15 players, 5 starters) weighs
# each move MORE than football (85). Baseball reloads a huge chunk of its roster
# every year (JUCO + portal + HS), so each move is weighted lighter — the class
# still shows on the graph, but a full reload doesn't pin an elite team at 99.
SPORT_ROSTER_MULT = {"football": 1.0, "mbb": 1.8, "baseball": 0.7}


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def wvu_won(g: dict) -> bool:
    wvu = g["home_points"] if g["is_wvu_home"] else g["away_points"]
    opp = g["away_points"] if g["is_wvu_home"] else g["home_points"]
    return (wvu or 0) > (opp or 0)


def national_rank(sport: str):
    """WVU's current national rank from ESPN (media poll), or None."""
    try:
        j = requests.get(
            f"https://site.api.espn.com/apis/site/v2/sports/{ESPN_PATH[sport]}/rankings",
            headers=UA, timeout=20,
        ).json()
        for poll in j.get("rankings", []):
            if "seed" in poll.get("name", "").lower():
                continue  # prefer a media poll over tournament seedings
            for r in poll.get("ranks", []):
                team = r.get("team", {}) or {}
                blob = f"{team.get('name','')} {team.get('location','')} {team.get('displayName','')}".lower()
                if "west virginia" in blob:
                    return r.get("current")
    except Exception:
        pass
    return None


def anchor_score(sport: str, w: int, l: int, rank) -> float:
    total = w + l
    winpct = (w / total) if total else 0.5
    record = 32.0 + winpct * 46.0  # 0% -> 32, 50% -> 55, 100% -> 78
    if not rank:
        return record
    # #1 -> 81, #25 -> 61. Kept well below the cap so form/roster/surge have headroom
    # to move the score — a ranked team lands in the 90s with room to rise AND fall,
    # instead of pinning at 99 for months where losses/outbound transfers can't show.
    ranked = 81.0 - (rank - 1) * (20.0 / 24.0)
    # Blend toward the ranking as the season fills in (p: 0 early -> 1 by season end).
    p = clamp(total / FULL_SEASON.get(sport, 20), 0.0, 1.0)
    return record * (1 - p) + ranked * p


def form_adj(reg: list) -> float:
    """reg: ordered 1/0 regular-season results. Recent-5 vs season average."""
    if len(reg) < 3:
        return 0.0
    season = sum(reg) / len(reg)
    recent = sum(reg[-5:]) / len(reg[-5:])
    return clamp((recent - season) * 24.0, -6.0, 6.0)


def roster_delta(moves: list, sport: str = "football") -> float:
    """moves: dicts with 'direction'/'category' (+ optional 'impact'). Weighted by
    category, boosted for marquee additions, sport-scaled & capped."""
    total = 0.0
    for m in moves:
        w = CAT_WEIGHT.get((m.get("category") or "transfer", m.get("direction")), 0.0)
        if m.get("impact") == "high":
            w *= IMPACT_MULT  # a marquee add OR a marquee/drafted loss moves the needle more
        total += w
    total *= SPORT_ROSTER_MULT.get(sport, 1.0)
    return clamp(total, -ROSTER_CAP, ROSTER_CAP)


def surge(post_wins: int, post_losses: int) -> float:
    """NET postseason result. A loss — even deep in a run (regionals, CWS) — pulls
    the score back; the CWS *appearance* is already reflected in the ranking anchor."""
    return clamp((post_wins - post_losses) * 1.5, -10.0, 12.0)


# News delta: each notable news day carries a SIGNED, non-decaying Pulse move so
# the line feels alive and reacts BOTH ways. AI daily notes contribute small nudges
# (-2..+2 for genuine good/bad news); curated big events (e.g. a vital signee getting
# drafted) carry an exact hand-set number (e.g. -4). It HOLDS — no fade — so a drop
# stays until a later note offsets it (e.g. a +4 the day the player returns). The
# cap is asymmetric: everyday good news stays modest, but bad news can bite harder.
NEWS_DELTA_CAP_UP = 8.0
NEWS_DELTA_CAP_DOWN = -16.0


def news_delta(note_deltas: list, as_of) -> float:
    """Signed, NON-decaying sum of note pulse-deltas dated on/before `as_of`.
    note_deltas: list of (date, delta) pairs. Bounded so news never fully dominates
    the tangible factors (record, ranking, roster)."""
    total = sum(dl for (nd, dl) in note_deltas if nd is not None and nd <= as_of)
    return clamp(total, NEWS_DELTA_CAP_DOWN, NEWS_DELTA_CAP_UP)


def trend_of(reg: list) -> str:
    """Trend arrow from REGULAR-season form only (recent-5 vs season)."""
    if len(reg) < 3:
        return "neutral"
    season = sum(reg) / len(reg)
    recent = sum(reg[-5:]) / len(reg[-5:])
    diff = recent - season
    return "up" if diff > 0.12 else ("down" if diff < -0.12 else "neutral")


def pulse_score(sport, w, l, rank, reg, moves, post_wins=0, post_losses=0, news=0.0) -> int:
    raw = (anchor_score(sport, w, l, rank) + form_adj(reg)
           + roster_delta(moves, sport) + surge(post_wins, post_losses) + news)
    return int(round(clamp(raw, 5, 99)))
