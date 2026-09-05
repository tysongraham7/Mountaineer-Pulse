import { useCallback, useEffect, useRef, useState } from 'react';
import { AppState } from 'react-native';

import { GameSummary, parseSummary } from '@/lib/game-summary';

/**
 * The box score, play-by-play and team stats behind a game sheet.
 *
 * WHY NOT ON A FAST TIMER. The payload is ~178 KB. The live card's 20-second poll costs
 * 2.3 KB a time because the core API serves the score and the last play as their own tiny
 * resources; there is no equivalent for a box score. Refreshing this every twenty seconds
 * would be ~30 MB an hour of somebody's cellular data to keep a tackle count current.
 *
 * So it loads once when the sheet opens and, only while the game is actually in progress
 * and the sheet is actually on screen, refreshes on a slow tick. The live header above it
 * keeps updating every twenty seconds from the cheap feed, which is the part that has to
 * feel current — a box score that trails the score by a minute reads as correct, whereas a
 * score that does reads as broken.
 *
 * Every failure is silent and non-destructive: a refresh that fails leaves the last good
 * summary on screen rather than blanking a sheet somebody is reading.
 */

const SUMMARY =
  'https://site.api.espn.com/apis/site/v2/sports/football/college-football/summary';

/** ESPN 403s browser-impersonating agents; an honest one is allowed. See sync_espn.py. */
const UA = { 'User-Agent': 'MountaineerPulse/1.0 (+https://github.com/tysongraham7/Mountaineer-Pulse)' };

/** Slow on purpose — see the note above. A drive takes minutes; a box score can too. */
const REFRESH_LIVE_MS = 90_000;

export type SummaryState = {
  summary: GameSummary | null;
  /** True only for the first load, so a refresh doesn't flash a spinner over real content. */
  loading: boolean;
  /** True when the first load failed and there is nothing to show. */
  failed: boolean;
  refresh: () => void;
};

export function useGameSummary(
  eventId: number | null,
  wvuHome: boolean,
  /** Whether this sheet is open. Closed sheets must not poll. */
  active: boolean,
): SummaryState {
  const [summary, setSummary] = useState<GameSummary | null>(null);
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState(false);
  const [nonce, setNonce] = useState(0);

  // Read by the timer when choosing whether to schedule another tick, without making the
  // timer depend on it — that would tear down and rebuild the loop on every refresh.
  const liveRef = useRef(false);
  liveRef.current = summary?.state === 'in';

  const refresh = useCallback(() => setNonce((n) => n + 1), []);

  const load = useCallback(
    async (signal: AbortSignal, first: boolean) => {
      if (!eventId) return;
      if (first) setLoading(true);
      try {
        const r = await fetch(`${SUMMARY}?event=${eventId}`, { headers: UA, signal });
        if (!r.ok) throw new Error(String(r.status));
        const parsed = parseSummary(await r.json(), wvuHome);
        if (signal.aborted) return;
        // A parse that comes back null means ESPN reshaped something. Keep what we have.
        if (parsed) {
          setSummary(parsed);
          setFailed(false);
        } else if (first) {
          setFailed(true);
        }
      } catch {
        if (first && !signal.aborted) setFailed(true);
      } finally {
        if (!signal.aborted) setLoading(false);
      }
    },
    [eventId, wvuHome],
  );

  useEffect(() => {
    if (!active || !eventId) {
      // Closing the sheet drops the data. Reopening costs one request, and holding a
      // 178 KB parse per game the user glanced at is the wrong tradeoff on a phone.
      setSummary(null);
      setFailed(false);
      return;
    }

    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | null = null;
    let stopped = false;
    let first = true;

    const tick = async () => {
      if (AppState.currentState === 'active') {
        await load(controller.signal, first);
        first = false;
      }
      if (stopped) return;
      // Only a game in progress can change. A finished or unstarted one is fetched once.
      if (liveRef.current) timer = setTimeout(tick, REFRESH_LIVE_MS);
    };
    tick();

    const sub = AppState.addEventListener('change', (s) => {
      if (s === 'active' && !stopped && liveRef.current) {
        if (timer) clearTimeout(timer);
        tick();
      }
    });

    return () => {
      stopped = true;
      if (timer) clearTimeout(timer);
      controller.abort();
      sub.remove();
    };
  }, [active, eventId, load, nonce]);

  return { summary, loading, failed, refresh };
}
