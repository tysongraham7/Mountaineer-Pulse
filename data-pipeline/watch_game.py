"""
Mountaineer Pulse - In-game watcher
===================================
Follows one WVU football game from kickoff to the final and turns what changes into
alerts: every score, the end of each quarter, halftime, and the final.

WHY THIS IS NOT ANOTHER CRON. notify_games.py runs every 30 minutes, and it runs that
slowly because asking GitHub for every 10 got the whole repository throttled to 3% of its
scheduled runs. A touchdown push that lands twenty minutes after the play is worse than no
push — everyone saw it on TV and in three group chats already. So this is one long job:
the game-watch workflow starts it, it polls ESPN every 20 seconds for the length of the
game, and it exits at the final. Fifteen or so times a season, on a public repo where the
minutes are free.

WHAT IT POLLS. The same two tiny core-API resources the app's live card reads (see
mobile/src/lib/use-live-game.ts): the status, and the situation's last play, which carries
the score AFTER that play. ~2.3 KB a poll, ~1 MB a game.

WHO GETS WHAT. Each event has a tier, and each device has an alert level on its
push_tokens row (the picker on the You tab writes it; rows without one are 'basic'):
    basic     final only                       (the default — two pushes a game with the
                                                kickoff reminder notify_games.py sends)
    quarters  + kickoff, end of quarters, halftime
    scores    + every score, either team
Plus `wvu_only`, which drops the other team's scores for people on 'scores'. Nobody is
promoted: someone who never chose gets 'basic', which is what they get today.

SHADOW MODE. With no --send, nothing is pushed and nothing is stamped; every event is
printed exactly as it would have gone out. This is how it runs until it has followed a
real game correctly — the Actions log of a Saturday is the review.

REHEARSAL. A game happens once a week and can't be replayed, so --replay walks a finished
game's real play-by-play through the same detector and prints every alert it would have
produced. Same idea as notify_games.py --at and scripts/rehearse-live.mts.

Usage:
    python watch_game.py                       # today's game, shadow mode
    python watch_game.py --send                # push for real, honouring alert levels
    python watch_game.py --replay 401756968    # rehearse against a finished game
    python watch_game.py --replay              # ... the last completed WVU game
    python watch_game.py --event 401856791     # watch a specific event id (shadow)
"""

import os
import re
import sys
import time
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Iterable

import requests
from dotenv import load_dotenv
from supabase import create_client

from notify_games import ET, final_alert, opponent_of
from send_push import send_push

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

load_dotenv()

SB_URL = os.getenv("SUPABASE_URL")
SB_KEY = os.getenv("SUPABASE_SECRET_KEY")

CORE = "https://sports.core.api.espn.com/v2/sports/football/leagues/college-football"
SITE = "https://site.api.espn.com/apis/site/v2/sports/football/college-football"
UA = {"User-Agent": "MountaineerPulse/1.0 (+https://github.com/tysongraham/mountaineer-pulse)"}
WVU_TEAM_ID = "277"

# Same cadence as the phone: fast enough to feel current, slow enough to be ~1 MB a game.
POLL_LIVE_S = 20
POLL_PRE_S = 60
# Start watching this early; games start late, they don't start early.
PRE_WINDOW = timedelta(minutes=20)
# A game that never reports a final can't hold the job open all night. Under the workflow's
# timeout so the exit is ours and gets logged.
MAX_WATCH = timedelta(hours=5)
# A touchdown is worth 6 for the few seconds until the kick, and ESPN posts the two as a
# score of 6 and then 7 on the same play. Hold a score for this long and send the latest, so
# nobody gets "WVU touchdown, 6–0" and then "7–0" forty seconds later.
SCORE_HOLD = timedelta(seconds=45)
# A score change on a play ESPN does NOT flag as scoring has to be seen this many polls
# running before it's believed. See Detector.
CONFIRM_POLLS = 3

# Event kinds and the alert level that receives them. Ranked, so 'scores' gets everything.
LEVEL_RANK = {"basic": 0, "quarters": 1, "scores": 2}
TIER = {"final": "basic", "kickoff": "quarters", "quarter": "quarters", "half": "quarters",
        "score": "scores"}
DEFAULT_LEVEL = "basic"

ORDINAL = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th"}
SCORE_WORD = {"touchdown": "touchdown", "field-goal": "field goal", "safety": "safety"}


def die(msg: str) -> None:
    print(f"ERROR: {msg}")
    sys.exit(1)


def get_json(url: str) -> dict | None:
    """One ESPN read. None on any failure — the loop keeps its last snapshot, as the phone does."""
    try:
        r = requests.get(url.replace("http://", "https://", 1), headers=UA, timeout=15)
        if r.status_code != 200:
            return None
        return r.json()
    except Exception:
        return None


def team_id_from(ref) -> str | None:
    if isinstance(ref, dict):
        ref = ref.get("$ref")
    if not isinstance(ref, str):
        return None
    m = re.search(r"/teams/(\d+)", ref)
    return m.group(1) if m else (ref if ref.isdigit() else None)


# ---------------------------------------------------------------- what ESPN said, once

@dataclass(frozen=True)
class Snapshot:
    """One reading of the game, from either the live feed or a replayed play."""
    at: datetime
    state: str            # pre | in | post
    status_name: str      # STATUS_IN_PROGRESS, STATUS_END_PERIOD, STATUS_HALFTIME, ...
    period: int
    clock: str
    home: int | None
    away: int | None
    play_id: str | None = None
    play_text: str = ""
    scoring: bool = False
    scoring_type: str = ""    # touchdown | field-goal | safety | ...
    play_team: str | None = None


def read_live(event_id: int, now: datetime) -> Snapshot | None:
    base = f"{CORE}/events/{event_id}/competitions/{event_id}"
    status = get_json(f"{base}/status")
    if not status:
        return None
    t = status.get("type") or {}
    state = t.get("state", "pre")
    period = int(status.get("period") or 0)
    clock = str(status.get("displayClock") or "")
    if state == "pre":
        return Snapshot(now, "pre", t.get("name", ""), period, clock, None, None)
    situation = get_json(f"{base}/situation") or {}
    play_ref = (situation.get("lastPlay") or {}).get("$ref")
    play = get_json(play_ref) if play_ref else None
    return snapshot_from_play(now, state, t.get("name", ""), period, clock, play)


def snapshot_from_play(now, state, status_name, period, clock, play: dict | None) -> Snapshot:
    play = play or {}
    return Snapshot(
        at=now, state=state, status_name=status_name, period=period, clock=clock,
        home=play.get("homeScore"), away=play.get("awayScore"),
        play_id=str(play.get("id")) if play.get("id") else None,
        # shortText is the scoreboard sentence — "Jacob Rodriguez 1 Yd Run (Stone Harrington
        # Kick)". `text` is the stat crew's, with formations and jersey numbers, and is the
        # fallback only.
        play_text=" ".join(str(play.get("shortText") or clean_play(play.get("text") or "")).split()),
        scoring=bool(play.get("scoringPlay")),
        scoring_type=str((play.get("scoringType") or {}).get("name") or ""),
        play_team=team_id_from(play.get("team")),
    )


# ---------------------------------------------------------------- what changed

@dataclass
class Event:
    kind: str             # kickoff | score | quarter | half | final
    at: datetime
    home: int | None
    away: int | None
    period: int = 0
    clock: str = ""
    wvu_scored: bool | None = None
    scoring_type: str = ""
    play_text: str = ""


@dataclass
class Detector:
    """
    Turns a stream of snapshots into events. Pure — no network, no clock of its own — so
    --replay can drive it with a finished game and the live loop with the real one.

    THE SCORE IS NOT TRUSTED ON SIGHT. In WVU–Coastal Carolina (ESPN 401856780) a kickoff
    penalty at 3:47 of the 4th carried 27–14 when the score was 24–14, the next play went
    back to 24–14, and a timeout at 1:51 carried a touchdown that the play after it scored.
    Read naively that is three phantom pushes in four minutes. So: a change on a play ESPN
    flags as a scoring play is real; a change on any other play has to survive
    CONFIRM_POLLS consecutive readings; and a score that goes DOWN is never a score.
    """
    wvu_home: bool
    prev: Snapshot | None = None
    accepted: tuple[int, int] | None = None   # the score we believe (home, away)
    cand: tuple[int, int] | None = None       # an unconfirmed change on a non-scoring play
    cand_n: int = 0
    pending: Event | None = None              # a score being held for its extra point
    pending_since: datetime | None = None
    started: bool = False
    done: bool = False

    def feed(self, s: Snapshot) -> list[Event]:
        out: list[Event] = []
        p = self.prev
        self.prev = s

        if s.state == "in" and not self.started:
            self.started = True
            # Only announce a kickoff we actually watched happen. A job that starts at
            # halftime (GitHub skipped the earlier ticks) must not say "under way".
            if p is not None and p.state == "pre":
                out.append(Event("kickoff", s.at, 0, 0, s.period, s.clock))

        if s.state == "pre":
            return out

        if s.home is not None and s.away is not None:
            raw = (s.home, s.away)
            if self.accepted is None:
                # First reading. A job that joins mid-game inherits the score silently.
                self.accepted = raw
            elif raw != self.accepted:
                acc = self.accepted
                up = raw[0] >= acc[0] and raw[1] >= acc[1]
                if not up:
                    self.cand, self.cand_n = None, 0
                elif s.scoring:
                    out += self._score(raw, s, s.play_text)
                else:
                    self.cand, self.cand_n = (raw, self.cand_n + 1) if raw == self.cand else (raw, 1)
                    if self.cand_n >= CONFIRM_POLLS:
                        out += self._score(raw, s, "")
            else:
                self.cand, self.cand_n = None, 0

        # Breaks. Matched on the status name, as the phone does — ESPN keeps state 'in'
        # through all of them. Only on the transition INTO the break, so a 15-minute
        # halftime is one push, not forty-five. Scores from `accepted`, not the feed.
        prev_name = p.status_name if p else ""
        if s.status_name != prev_name:
            home, away = self.accepted or (0, 0)
            if "HALFTIME" in s.status_name:
                out += self.flush(force=True)
                out.append(Event("half", s.at, home, away, s.period, s.clock))
            elif "END_PERIOD" in s.status_name and s.period in (1, 3):
                out += self.flush(force=True)
                out.append(Event("quarter", s.at, home, away, s.period, s.clock))

        if s.state == "post" and not self.done:
            self.done = True
            # The final carries the score; a held last-second field goal would only
            # duplicate it. ESPN's final reading is trusted unless it goes backwards.
            self.pending = None
            home, away = self.accepted or (0, 0)
            if s.home is not None and s.away is not None and s.home >= home and s.away >= away:
                home, away = s.home, s.away
            out.append(Event("final", s.at, home, away, s.period, s.clock))

        return out + self.flush(now=s.at)

    def _score(self, raw: tuple[int, int], s: Snapshot, text: str) -> list[Event]:
        """Accept a new score. Held rather than sent — see SCORE_HOLD."""
        acc = self.accepted or (0, 0)
        self.accepted, self.cand, self.cand_n = raw, None, 0
        scored_home = raw[0] > acc[0]
        wvu_scored = scored_home if self.wvu_home else not scored_home
        if self.pending and self.pending.wvu_scored == wvu_scored:
            # The kick after the touchdown: same team, keep the touchdown's sentence,
            # take the new score.
            self.pending = replace(self.pending, home=raw[0], away=raw[1])
            return []
        out = [self.pending] if self.pending else []
        self.pending = Event("score", s.at, raw[0], raw[1], s.period, s.clock, wvu_scored,
                             s.scoring_type if text else "", text)
        self.pending_since = s.at
        return out

    def flush(self, now: datetime | None = None, force: bool = False) -> list[Event]:
        """Release the held score once its hold has expired (or on demand)."""
        if not self.pending:
            return []
        if force or (now is not None and now - self.pending_since >= SCORE_HOLD):
            ev, self.pending, self.pending_since = self.pending, None, None
            return [ev]
        return []


# ---------------------------------------------------------------- what to say

def clean_play(text: str) -> str:
    """ESPN's play sentence minus the parts a push doesn't need: the clock in brackets,
    the formation, the jersey numbers. "(11:17) No Huddle-Shotgun #10 J.Rodriguez rush
    middle for 1 yard gain" -> "J.Rodriguez rush middle for 1 yard gain"."""
    t = re.sub(r"^\(\d+:\d+\)\s*", "", text or "")
    t = re.sub(r"^(No Huddle-)?(Shotgun|Under Center|Pistol|Wildcat)\s+", "", t)
    t = re.sub(r"#\d+\s*", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t[:140]


def alert_text(ev: Event, g: dict) -> tuple[str, str]:
    """Title and body for one event, in the same voice as notify_games.py."""
    opp = opponent_of(g)
    home = bool(g.get("is_wvu_home"))
    wvu, opp_pts = (ev.home, ev.away) if home else (ev.away, ev.home)
    wvu, opp_pts = wvu or 0, opp_pts or 0
    line = f"WVU {wvu}, {opp} {opp_pts}"
    where = "in Morgantown" if home else f"at {opp}"

    if ev.kind == "kickoff":
        return (f"WVU {'vs' if home else 'at'} {opp} is under way",
                f"Kickoff {where}. Tap for the live score and play-by-play.")
    if ev.kind == "score":
        who = "WVU" if ev.wvu_scored else opp
        word = SCORE_WORD.get(ev.scoring_type, "scores")
        title = f"{who} {word} — {line}" if word != "scores" else f"{who} scores — {line}"
        when = f"{ORDINAL.get(ev.period, str(ev.period) + 'th')}, {ev.clock}" if ev.clock else ""
        body = " · ".join(x for x in (ev.play_text, when) if x) or f"{line} {where}."
        return title, body
    if ev.kind in ("quarter", "half"):
        head = "Halftime" if ev.kind == "half" else f"End of {ORDINAL.get(ev.period, '')} quarter"
        if wvu > opp_pts:
            body = f"WVU leads {opp} {wvu}–{opp_pts} {where}."
        elif wvu < opp_pts:
            body = f"{opp} leads WVU {opp_pts}–{wvu} {where}."
        else:
            body = f"Tied {wvu}–{opp_pts} {where}."
        return f"{head} — {line}", body
    if ev.kind == "final":
        # notify_games.py's own words, so a final reads the same whichever job sent it.
        return final_alert({**g, "home_points": ev.home, "away_points": ev.away})
    return line, ""


# ---------------------------------------------------------------- who gets it

def recipients(sb, ev: Event) -> list[str]:
    """Tokens whose alert level asks for this event. Rows with no level are 'basic'."""
    need = LEVEL_RANK[TIER[ev.kind]]
    rows = sb.table("push_tokens").select("*").eq("enabled", True).execute().data or []
    out = []
    for r in rows:
        tok = r.get("token") or ""
        if not tok.startswith("ExponentPushToken"):
            continue
        level = LEVEL_RANK.get(r.get("alert_level") or DEFAULT_LEVEL, 0)
        if level < need:
            continue
        # wvu_only defaults ON: the other team's field goals are the pushes people turn
        # notifications off over.
        if ev.kind == "score" and ev.wvu_scored is False and r.get("wvu_only", True):
            continue
        out.append(tok)
    return out


# ---------------------------------------------------------------- the game to watch

def find_game(sb, now: datetime) -> dict | None:
    """Today's football game with an ESPN id: kicking off within PRE_WINDOW, or in progress."""
    lo = (now - MAX_WATCH).isoformat()
    hi = (now + PRE_WINDOW).isoformat()
    rows = (sb.table("games")
            .select("id,sport_id,start_date,home_team,away_team,is_wvu_home,status,"
                    "espn_event_id,notified_final_at")
            .eq("sport_id", "football").neq("status", "final")
            .gte("start_date", lo).lte("start_date", hi)
            .not_.is_("espn_event_id", "null")
            .order("start_date").execute().data or [])
    return rows[0] if rows else None


def game_from_espn(event_id: int) -> dict:
    """A games-shaped row built from ESPN, for --replay and --event without the table."""
    ev = get_json(f"{SITE}/summary?event={event_id}") or {}
    comp = ((ev.get("header") or {}).get("competitions") or [{}])[0]
    home = away = None
    for c in comp.get("competitors") or []:
        name = (c.get("team") or {}).get("location") or (c.get("team") or {}).get("displayName")
        if c.get("homeAway") == "home":
            home = (name, c.get("id"))
        else:
            away = (name, c.get("id"))
    if not home or not away:
        die(f"ESPN has no competitors for event {event_id}")
    return {"id": event_id, "sport_id": "football", "espn_event_id": event_id,
            "home_team": home[0], "away_team": away[0],
            "is_wvu_home": str(home[1]) == WVU_TEAM_ID,
            "start_date": comp.get("date")}


def last_completed_event() -> int:
    for season in (datetime.now().year, datetime.now().year - 1):
        data = get_json(f"{SITE}/teams/{WVU_TEAM_ID}/schedule?season={season}") or {}
        done = [e for e in data.get("events") or []
                if ((e.get("competitions") or [{}])[0].get("status") or {}).get("type", {}).get("completed")]
        if done:
            return int(done[-1]["id"])
    die("No completed WVU game found on ESPN")


# ---------------------------------------------------------------- replay

def replay_snapshots(event_id: int) -> Iterable[Snapshot]:
    """A finished game's plays, in order, as the snapshots the live loop would have seen."""
    data = get_json(f"{CORE}/events/{event_id}/competitions/{event_id}/plays?limit=500") or {}
    plays = data.get("items") or []
    if not plays:
        die(f"ESPN has no plays for event {event_id}")
    # Not every play carries a wallclock, so time is synthesised: one play every 40
    # seconds. Close enough to a real game's pace for the score hold to behave as it would.
    t0 = datetime.now(timezone.utc)
    yield Snapshot(t0, "pre", "STATUS_SCHEDULED", 0, "", None, None)
    for i, p in enumerate(plays):
        at = t0 + timedelta(seconds=40 * (i + 1))
        ptype = ((p.get("type") or {}).get("text") or "").lower()
        period = int((p.get("period") or {}).get("number") or 0)
        clock = str((p.get("clock") or {}).get("displayValue") or "")
        if ptype == "end of game":
            state, name = "post", "STATUS_FINAL"
        elif ptype == "end period":
            state = "in"
            name = "STATUS_HALFTIME" if period == 2 else "STATUS_END_PERIOD"
        else:
            state, name = "in", "STATUS_IN_PROGRESS"
        yield snapshot_from_play(at, state, name, period, clock, p)


# ---------------------------------------------------------------- main

def announce(ev: Event, g: dict, sb, send: bool) -> None:
    title, body = alert_text(ev, g)
    stamp = ev.at.astimezone(ET).strftime("%I:%M:%S %p")
    tier = TIER[ev.kind]
    print(f"[{stamp}] {ev.kind.upper():<8} ({tier:<8}) {title}\n{'':>32}{body}", flush=True)
    if not send or sb is None:
        return
    if ev.kind == "final":
        # notify_games.py sends finals too, from CFBD, up to 30 minutes later. Whoever is
        # first stamps the row; the other sees the stamp and stays quiet.
        row = sb.table("games").select("notified_final_at").eq("id", g["id"]).execute().data
        if row and row[0].get("notified_final_at"):
            print("           (final already sent by notify_games.py — skipping)")
            return
    tokens = recipients(sb, ev)
    if not tokens:
        print(f"           (nobody at level '{tier}' or above — not sent)")
        return
    send_push(title, body, data={"screen": "scores", "gameId": str(g["id"])}, tokens=tokens)
    if ev.kind == "final":
        sb.table("games").update({"notified_final_at": ev.at.isoformat()}).eq("id", g["id"]).execute()


def label(g: dict) -> str:
    return f"WVU {'vs' if g.get('is_wvu_home') else 'at'} {opponent_of(g)}"


def main() -> None:
    args = sys.argv[1:]
    send = "--send" in args

    def arg_after(flag: str) -> str | None:
        if flag in args:
            i = args.index(flag)
            return args[i + 1] if i + 1 < len(args) and not args[i + 1].startswith("--") else ""
        return None

    replay = arg_after("--replay")
    if replay is not None:
        event_id = int(replay) if replay else last_completed_event()
        g = game_from_espn(event_id)
        print(f"[replay] {label(g)} — ESPN event {event_id}. Nothing is sent.\n")
        det = Detector(wvu_home=bool(g["is_wvu_home"]))
        n = 0
        for snap in replay_snapshots(event_id):
            for ev in det.feed(snap):
                announce(ev, g, None, False)
                n += 1
        print(f"\n[replay] {n} alert(s) over the game.")
        return

    sb = None
    if SB_URL and SB_KEY:
        sb = create_client(SB_URL, SB_KEY)
    elif send:
        die("Missing SUPABASE_URL or SUPABASE_SECRET_KEY")

    now = datetime.now(timezone.utc)
    explicit = arg_after("--event")
    if explicit:
        g = game_from_espn(int(explicit))
    else:
        if sb is None:
            die("Missing SUPABASE_URL or SUPABASE_SECRET_KEY (or pass --event <id>)")
        g = find_game(sb, now)
        if not g:
            print(f"No football game to watch ({now.astimezone(ET):%H:%M} ET): nothing kicking "
                  f"off within {int(PRE_WINDOW.total_seconds() // 60)}m and nothing in progress.")
            return

    event_id = int(g["espn_event_id"])
    kick = datetime.fromisoformat(str(g["start_date"]).replace("Z", "+00:00"))
    mode = "SENDING" if send else "shadow mode — nothing will be sent"
    print(f"Watching {label(g)} — ESPN event {event_id}, kickoff {kick.astimezone(ET):%I:%M %p} ET. "
          f"{mode}.", flush=True)

    det = Detector(wvu_home=bool(g["is_wvu_home"]))
    deadline = max(kick, now) + MAX_WATCH
    last_line = ""
    while True:
        now = datetime.now(timezone.utc)
        if now > deadline:
            print("Gave up: no final reported within the watch window.")
            break
        snap = read_live(event_id, now)
        if snap:
            for ev in det.feed(snap):
                announce(ev, g, sb, send)
            line = f"{snap.state} {snap.status_name} Q{snap.period} {snap.clock} {snap.home}-{snap.away}"
            if line != last_line:
                print(f"  {now.astimezone(ET):%H:%M:%S}  {line}", flush=True)
                last_line = line
            if det.done:
                break
        # Between polls, a held score may come due with no new snapshot to trigger it.
        for ev in det.flush(now=datetime.now(timezone.utc)):
            announce(ev, g, sb, send)
        state = snap.state if snap else (det.prev.state if det.prev else "pre")
        time.sleep(POLL_LIVE_S if state == "in" else POLL_PRE_S)

    print("Done.")


if __name__ == "__main__":
    main()
