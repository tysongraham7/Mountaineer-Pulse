/**
 * Storage keys for the one-time in-app coaching.
 *
 * Shared rather than repeated at each site: the home screen writes them, the You tab's help
 * sheet clears them to re-arm the tips, and the Pulse sheet owns the scrub demo. Three files
 * holding the same string literal is exactly how "show tips again" quietly stops working.
 *
 * Versioned. Bumping a key re-runs that piece of coaching for everyone, including installs
 * that already dismissed the previous version — which is the only way to reach users who are
 * already here, since they all cleared `mp-onboarded` long ago.
 */

/** Home screen: scroll nudge + tap callout on the Program Pulse rows. */
export const COACH_PULSE_KEY = 'mp-coach-pulse-v1';

/** Pulse sheet: the auto-playing scrub demo across the chart. */
export const COACH_SCRUB_KEY = 'mp-scrub-demo-seen';

export const ALL_COACH_KEYS = [COACH_PULSE_KEY, COACH_SCRUB_KEY];
