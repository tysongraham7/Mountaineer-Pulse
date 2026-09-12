"""
Mountaineer Pulse - Checks for watch_game.py
============================================
Feeds the detector hand-built readings with known answers. No network: the cases here
are the ways ESPN's live feed has actually misbehaved, written down so the next change to
the detector can't quietly bring one back.

Every case is from a real game. The big one is WVU–UT Martin, 12 Sep 2026, the first
live run: a ghost UT Martin touchdown that poisoned the rest of the game's scores, and a
quarter end ESPN never flagged. --replay can't reproduce either, because a finished
game's play list has the corrections baked in.

Run:  python test_watch_game.py
"""

import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from watch_game import CONFIRM_POLLS, SCORE_HOLD, Detector, Snapshot

T0 = datetime(2026, 9, 12, 17, 0, tzinfo=timezone.utc)
POLL = timedelta(seconds=20)


class Feed:
    """Readings 20 seconds apart, like the live loop, with the score as (wvu, opp)."""

    def __init__(self, wvu_home=True):
        self.t = T0
        self.det = Detector(wvu_home=wvu_home)
        self.wvu_home = wvu_home
        self.events = []

    def read(self, state="in", name="STATUS_IN_PROGRESS", q=1, clock="15:00",
             wvu=None, opp=None, scoring=False, text="", stype="", secs=20):
        self.t += timedelta(seconds=secs)
        home, away = (wvu, opp) if self.wvu_home else (opp, wvu)
        snap = Snapshot(self.t, state, name, q, clock, home, away,
                        play_text=text, scoring=scoring, scoring_type=stype)
        self.events += self.det.feed(snap)
        return self

    def idle(self, n=1, **kw):
        """Same reading again n times — the game between plays."""
        for _ in range(n):
            self.read(**kw)
        return self

    def kinds(self):
        return [(e.kind, e.home, e.away) if e.kind != "score" else
                (e.kind, "WVU" if e.wvu_scored else "OPP", e.home, e.away)
                for e in self.events]


def check(name, got, want):
    ok = got == want
    print(("  ok   " if ok else "  FAIL ") + name)
    if not ok:
        print("       got: ", got)
        print("       want:", want)
    return ok


def run() -> bool:
    good = True
    hold_polls = int(SCORE_HOLD / POLL) + 1

    # ---- A touchdown, then its kick, is one push with the kicked score.
    f = Feed().read(state="pre", name="STATUS_SCHEDULED", q=0, clock="0:00")
    f.read(wvu=0, opp=0)
    f.read(wvu=6, opp=0, scoring=True, text="Hawkins pass to Epps for 53 yds", stype="touchdown", clock="12:08")
    f.idle(3, wvu=6, opp=0, scoring=True, text="Hawkins pass to Epps for 53 yds", stype="touchdown", clock="12:08")
    f.read(wvu=7, opp=0, scoring=True, text="Hawkins pass to Epps for 53 yds", stype="touchdown", clock="12:08")
    f.idle(hold_polls, wvu=7, opp=0, scoring=True, text="...", stype="touchdown")
    good &= check("touchdown + kick is one push, 7-0",
                  f.kinds(), [("kickoff", 0, 0), ("score", "WVU", 7, 0)])
    good &= check("kept the touchdown's sentence, not the kick's",
                  f.events[1].play_text, "Hawkins pass to Epps for 53 yds")

    # ---- The UT Martin ghost. A scoring play posts 21-6, is pulled 42s later, and the real
    #      scores that follow must all come through with the right team on them.
    f = Feed().read(wvu=21, opp=0, q=2)                              # joins at 21-0
    f.read(wvu=21, opp=6, scoring=True, text="Surber pass to Sherrard for 54 yds", stype="touchdown", q=2, clock="14:01")
    f.read(wvu=21, opp=6, q=2, clock="14:01")                        # +40s, still there
    f.read(wvu=21, opp=0, q=2, clock="14:01")                        # +60s: gone
    f.idle(hold_polls, wvu=21, opp=0, q=2)
    good &= check("ghost touchdown pulled inside the hold is never sent", f.kinds(), [])
    good &= check("accepted score rolled back to 21-0", f.det.accepted, (21, 0))
    f.read(wvu=27, opp=0, scoring=True, text="Hawkins run for 5 yds", stype="touchdown", q=2, clock="11:30")
    f.read(wvu=28, opp=0, scoring=True, text="Hawkins run for 5 yds", stype="touchdown", q=2, clock="11:30")
    f.idle(hold_polls, wvu=28, opp=0, q=2)
    good &= check("the next real WVU touchdown comes through as WVU, 28-0",
                  f.kinds(), [("score", "WVU", 28, 0)])
    # ... and the opponent's fumble-return touchdown late is theirs, with its kick folded in.
    f.read(wvu=52, opp=0, scoring=True, text="Latimer run", stype="touchdown", q=4, clock="5:00")
    f.idle(hold_polls, wvu=52, opp=0, q=4)
    n = len(f.events)
    f.read(wvu=52, opp=6, scoring=True, text="Betts returned for a TD", stype="touchdown", q=4, clock="3:25")
    f.read(wvu=52, opp=7, scoring=True, text="(B. Sims KICK)", q=4, clock="3:25")
    f.idle(hold_polls, wvu=52, opp=7, q=4)
    good &= check("opponent's defensive touchdown is theirs, 52-7, one push",
                  f.kinds()[n:], [("score", "OPP", 52, 7)])
    good &= check("...with the return's sentence", f.events[-1].play_text, "Betts returned for a TD")

    # ---- Quarter ends when ESPN never says END_PERIOD: Q1 0:00 straight to Q2 15:00.
    f = Feed().read(wvu=21, opp=0, q=1, clock="0:00")
    f.read(wvu=21, opp=0, q=2, clock="15:00")
    f.read(wvu=21, opp=0, q=2, clock="14:57")
    good &= check("end of 1st from the period ticking over", f.kinds(), [("quarter", 21, 0)])
    good &= check("...labelled as the 1st", f.events[0].period, 1)
    # Halftime via the status name, then the period flips to 3 — once, not twice.
    f.read(wvu=28, opp=0, scoring=True, text="Hawkins run", stype="touchdown", q=2, clock="11:30")
    f.idle(hold_polls, wvu=28, opp=0, q=2)
    f.read(wvu=28, opp=0, q=2, clock="0:00", name="STATUS_HALFTIME")
    f.read(wvu=28, opp=0, q=2, clock="0:00", name="STATUS_HALFTIME")
    f.read(wvu=28, opp=0, q=3, clock="15:00", name="STATUS_HALFTIME")   # ESPN flapped this way
    f.read(wvu=28, opp=0, q=2, clock="0:00", name="STATUS_HALFTIME")
    f.read(wvu=28, opp=0, q=3, clock="15:00")
    good &= check("halftime once, at 28-0",
                  [k for k in f.kinds() if k[0] == "half"], [("half", 28, 0)])
    f.read(wvu=42, opp=0, q=3, clock="0:00")
    f.read(wvu=42, opp=0, q=4, clock="15:00")
    good &= check("end of 3rd from the period ticking over",
                  [k for k in f.kinds() if k[0] == "quarter"], [("quarter", 21, 0), ("quarter", 28, 0)])

    # ---- A touchdown at 0:00 of the 1st: the quarter waits for the hold, then reports 14-0.
    f = Feed().read(wvu=7, opp=0, q=1, clock="0:13")
    f.read(wvu=13, opp=0, scoring=True, text="Douglas 19 Yd pass", stype="touchdown", q=1, clock="0:00")
    f.read(wvu=14, opp=0, scoring=True, text="Douglas 19 Yd pass", stype="touchdown", q=2, clock="15:00")
    good &= check("quarter end is held back while a score is on hold", f.kinds(), [])
    f.idle(hold_polls, wvu=14, opp=0, q=2)
    good &= check("...then the score, then the quarter at the settled 14-0",
                  f.kinds(), [("score", "WVU", 14, 0), ("quarter", 14, 0)])
    # The same, but the touchdown comes back: no score, and the quarter says 7-0.
    f = Feed().read(wvu=7, opp=0, q=1, clock="0:13")
    f.read(wvu=13, opp=0, scoring=True, text="ghost", stype="touchdown", q=1, clock="0:00")
    f.read(wvu=13, opp=0, q=2, clock="15:00")
    f.read(wvu=7, opp=0, q=2, clock="15:00")
    f.idle(hold_polls, wvu=7, opp=0, q=2)
    good &= check("...and a ghost at 0:00 gives just the quarter, at 7-0", f.kinds(), [("quarter", 7, 0)])

    # ---- Coastal Carolina: a bogus score on a non-scoring play that lasts one reading.
    f = Feed().read(wvu=24, opp=14, q=4)
    f.read(wvu=27, opp=14, q=4, clock="3:47")     # kickoff penalty carrying 27-14
    f.read(wvu=24, opp=14, q=4, clock="3:07")     # back to the truth
    f.read(wvu=31, opp=14, scoring=True, text="Hawkins 11 Yd Run", stype="touchdown", q=4, clock="2:58")
    f.idle(hold_polls, wvu=31, opp=14, q=4)
    good &= check("one-reading phantom on a penalty play is ignored", f.kinds(), [("score", "WVU", 31, 14)])

    # ---- A final drops a held score and carries ESPN's number.
    f = Feed().read(wvu=31, opp=21, q=4)
    f.read(wvu=31, opp=24, scoring=True, text="32 Yd Field Goal", stype="field-goal", q=4, clock="0:27")
    f.read(state="post", name="STATUS_FINAL", wvu=31, opp=24, q=4, clock="0:00")
    good &= check("last-second field goal folds into the final", f.kinds(), [("final", 31, 24)])

    # ---- Joining mid-game announces nothing.
    f = Feed().read(wvu=28, opp=0, q=3, clock="7:00")
    f.idle(5, wvu=28, opp=0, q=3)
    good &= check("joining at 28-0 in the 3rd says nothing", f.kinds(), [])

    return good


if __name__ == "__main__":
    ok = run()
    print("\nALL OK" if ok else "\nFAILURES")
    sys.exit(0 if ok else 1)
