import { useCallback, useEffect, useRef, useState } from 'react';
import { AppState } from 'react-native';

import { LiveGame, ParseOpts, Situation, parseLive, statusState } from '@/lib/live-game-parse';

/**
 * Live scoring for a game in progress, polled straight from ESPN by the phone.
 *
 * WHY NOT THROUGH THE PIPELINE. Everything else in this app reads Supabase, written by a
 * cron job. That cannot drive a scoreboard: the game-day workflow runs every 30 minutes,
 * and it runs that slowly for a reason — asking GitHub for every 10 minutes got the whole
 * repository throttled to 3% of its scheduled runs (see .github/workflows/game-day.yml).
 * A score that updates twice an hour is not a live score, and buying a faster one would
 * mean paying for infrastructure to relay a number the phone can fetch itself.
 *
 * WHY THE CORE API. The obvious endpoint, the one the pipeline already uses, is the site
 * scoreboard — but it returns every FBS game that day, 819 KB, which at a 20-second poll
 * is roughly 400 MB of somebody's cellular data over one afternoon. ESPN's core API serves
 * the same facts as separate small resources: 0.4 KB for the situation and 1.9 KB for the
 * play it points at. Two requests, ~2.3 KB, about 1 MB across a full game.
 *
 * WHAT THIS IS NOT. ESPN trails the broadcast by roughly half a minute, and the broadcast
 * trails the stadium. Anyone watching on TV will see it here second. The card says so for
 * that reason — this is a play-by-play tracker, and calling it live would be promising
 * something the feed cannot deliver.
 *
 * Every failure here is silent. An unreachable or reshaped feed leaves the last good state
 * on screen, or `null`, and the card falls back to the countdown it showed before.
 *
 * The parsing itself lives in live-game-parse.ts so it can be rehearsed against a finished
 * game before kickoff — see scripts/rehearse-live.ts.
 */

const CORE = 'https://sports.core.api.espn.com/v2/sports/football/leagues/college-football';

/** ESPN 403s browser-impersonating agents; an honest one is allowed. See sync_espn.py. */
const UA = { 'User-Agent': 'MountaineerPulse/1.0 (+https://github.com/tysongraham/mountaineer-pulse)' };

/** While the ball is live. Fast enough to feel current, slow enough to be ~1 MB a game. */
const POLL_LIVE_MS = 20_000;
/** Before kickoff, only to catch the moment it starts. */
const POLL_PRE_MS = 60_000;
/** How early to start watching for kickoff. Games start late; they rarely start early. */
const PRE_WINDOW_MS = 20 * 60 * 1000;
/** How long after kickoff to keep polling a game that never reports a final. */
const MAX_WATCH_MS = 7 * 60 * 60 * 1000;

async function getJson(url: string, signal: AbortSignal): Promise<Record<string, unknown> | null> {
  try {
    const r = await fetch(url, { headers: UA, signal });
    if (!r.ok) return null; // a 404 before the first snap is normal, not an error
    return (await r.json()) as Record<string, unknown>;
  } catch {
    return null; // offline, timeout, ESPN reshaping its JSON — all the same to the card
  }
}

/**
 * @param eventId  ESPN event id from games.espn_event_id, or null when we have none.
 * @param kickoff  ISO kickoff, used only to decide when to start and stop polling.
 * @param wvuHome  Which side of ESPN's home/away scores is WVU.
 * @param wvuAbbr  Short name for WVU in the field-position label.
 * @param oppAbbr  Short name for the opponent in the field-position label.
 */
export function useLiveGame(
  eventId: number | null,
  kickoff: string | null,
  wvuHome: boolean,
  wvuAbbr: string,
  oppAbbr: string,
): LiveGame | null {
  const [live, setLive] = useState<LiveGame | null>(null);

  // Mirrored in a ref so the polling loop can read the current state when choosing its next
  // delay without depending on it, which would tear down and rebuild the timer every tick.
  const stateRef = useRef<LiveGame['state'] | null>(null);
  stateRef.current = live?.state ?? null;

  const poll = useCallback(
    async (signal: AbortSignal) => {
      if (!eventId) return;
      const opts: ParseOpts = { wvuHome, wvuAbbr, oppAbbr };
      const base = `${CORE}/events/${eventId}/competitions/${eventId}`;

      const status = await getJson(`${base}/status`, signal);
      if (!status) return; // keep whatever we last showed rather than blanking the card

      // Nothing else exists yet before the first snap, and asking would cost a round trip
      // that 404s for every one of the twenty minutes spent watching for kickoff.
      if (statusState(status) === 'pre') {
        setLive(parseLive(status, null, null, opts));
        return;
      }

      const situation = ((await getJson(`${base}/situation`, signal)) ?? {}) as Situation;
      const playRef = situation.lastPlay?.$ref;
      // The feed hands back http:// refs; Android blocks cleartext by default.
      const play = playRef ? await getJson(playRef.replace(/^http:/, 'https:'), signal) : null;

      setLive(parseLive(status, situation, play, opts));
    },
    [eventId, wvuHome, wvuAbbr, oppAbbr],
  );

  useEffect(() => {
    if (!eventId || !kickoff) {
      setLive(null);
      return;
    }
    const start = new Date(kickoff).getTime();
    if (!Number.isFinite(start)) return;

    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | null = null;
    let stopped = false;

    const tick = async () => {
      const sinceKick = Date.now() - start;
      // Outside the window there is nothing to ask about. Bounded on the far side so a game
      // ESPN never marks final cannot leave a phone polling all night.
      const watching =
        sinceKick > -PRE_WINDOW_MS &&
        sinceKick < MAX_WATCH_MS &&
        stateRef.current !== 'post' &&
        AppState.currentState === 'active';
      if (watching) await poll(controller.signal);
      if (stopped) return;
      // A finished game still schedules a slow tick rather than stopping outright: the final
      // score should stay on screen, and a cheap 60s no-op beats tearing the loop down.
      timer = setTimeout(tick, stateRef.current === 'in' ? POLL_LIVE_MS : POLL_PRE_MS);
    };
    tick();

    // Foreground only — a backgrounded phone showing a stale score costs nothing, but a
    // backgrounded phone hitting ESPN every 20 seconds costs battery.
    const sub = AppState.addEventListener('change', (s) => {
      if (s === 'active' && !stopped) {
        if (timer) clearTimeout(timer);
        tick(); // refresh on return rather than showing up to 20s of stale score
      }
    });

    return () => {
      stopped = true;
      if (timer) clearTimeout(timer);
      controller.abort();
      sub.remove();
    };
  }, [eventId, kickoff, poll]);

  return live;
}
