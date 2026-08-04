import { useEffect, useState } from 'react';

import { formatCountdown, kickoffAt } from '@/lib/eastern';

/**
 * How close kickoff has to be before the card counts seconds instead of days.
 * A ticking clock 32 days out is noise; inside a day it's the point.
 */
const LIVE_WINDOW_MS = 24 * 60 * 60 * 1000;

/**
 * How long after kickoff the card may still say "Underway".
 *
 * Bounded on purpose. Game status only flips to final on the nightly pipeline run, so
 * an unbounded window would leave "Underway" on screen at 11pm for a game that ended
 * at three — asserting something live that we haven't confirmed is live. After this it
 * falls back to "Today", which stays true either way.
 */
const UNDERWAY_WINDOW_MS = 4 * 60 * 60 * 1000;

export type KickoffState = {
  /** "3:42:15" while the clock is worth running, else null. */
  live: string | null;
  /** Kickoff has passed but the game is presumably still on. */
  underway: boolean;
};

/**
 * A once-per-second countdown, but only inside the last day before kickoff.
 *
 * The interval is created only when it's actually counting, so the home screen
 * isn't waking every second for a game five weeks out — which is what it would
 * do for all but a handful of days a year.
 */
export function useKickoffCountdown(iso: string | null): KickoffState {
  const [now, setNow] = useState(() => Date.now());

  const at = iso ? kickoffAt(iso) : null;
  const remaining = at === null ? null : at - now;
  const counting = remaining !== null && remaining > 0 && remaining <= LIVE_WINDOW_MS;

  useEffect(() => {
    if (!counting) return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [counting]);

  // Re-sync on mount so a screen that has been open for hours doesn't start from a
  // stale `now` for the first second after the game enters the live window.
  useEffect(() => {
    setNow(Date.now());
  }, [iso]);

  return {
    live: counting ? formatCountdown(remaining as number) : null,
    underway: remaining !== null && remaining <= 0 && remaining > -UNDERWAY_WINDOW_MS,
  };
}
