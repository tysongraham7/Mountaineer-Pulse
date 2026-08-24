import AsyncStorage from '@react-native-async-storage/async-storage';
import Constants from 'expo-constants';
import { Platform } from 'react-native';

import { supabase } from '@/lib/supabase';

/**
 * Anonymous, privacy-first usage analytics.
 *
 * We store a RANDOM per-install id (not a device identifier, no name/email/IP) so we can answer
 * the questions that matter during the beta: are people coming back (daily-active users), does
 * the morning push pull them in (push opens), how long do they stay (session_end), and what do
 * they actually use (screen_view for tabs, feature for individual actions). Events are
 * insert-only — the app can send them but never read them back; the founder reads aggregates
 * server-side (read_analytics.py, dashboard.py).
 *
 * Every call is fire-and-forget and error-swallowed: analytics must NEVER affect the app.
 */

const ANON_KEY = 'mp-anon-id';
// One app_open per 30 min of activity, so quickly switching in and out of the app doesn't
// inflate the count. A cold start or a notification tap always counts.
const OPEN_THROTTLE_MS = 30 * 60 * 1000;

let cachedAnonId: string | null = null;
let lastOpenAt = 0;

/** RN-safe random UUID (v4-ish). Enough to count distinct installs anonymously — it is NOT a
 *  device id and isn't derived from anything on the device. */
function uuid(): string {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (ch) => {
    const r = (Math.random() * 16) | 0;
    const v = ch === 'x' ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

async function anonId(): Promise<string> {
  if (cachedAnonId) return cachedAnonId;
  let id = await AsyncStorage.getItem(ANON_KEY);
  if (!id) {
    id = uuid();
    await AsyncStorage.setItem(ANON_KEY, id);
  }
  cachedAnonId = id;
  return id;
}

async function track(event: string, screen?: string, durationMs?: number): Promise<void> {
  try {
    const anon_id = await anonId();
    await supabase.from('analytics_events').insert({
      anon_id,
      event,
      screen: screen ?? null,
      duration_ms: durationMs ?? null,
      platform: Platform.OS,
      app_version: Constants.expoConfig?.version ?? null,
    });
  } catch {
    // Analytics is best-effort — never let it surface an error to the user.
  }
}

/** App came to the foreground (cold start or return). Throttled so an app-switch doesn't
 *  double-count; a notification tap (`fromPush`) always counts and also logs a push open. */
export function trackAppOpen(fromPush = false): void {
  const now = Date.now();
  if (!fromPush && now - lastOpenAt < OPEN_THROTTLE_MS) return;
  lastOpenAt = now;
  void track('app_open');
  if (fromPush) void track('push_open');
}

/** A notification was tapped while the app was already running/backgrounded. */
export function trackPushOpen(): void {
  void track('push_open');
}

/** The user navigated to a tab/route. */
export function trackScreen(screen: string): void {
  void track('screen_view', screen);
}

/**
 * A specific thing the user did, beyond just landing on a tab — opening a game sheet, a player
 * profile, tapping through to a news story. Tab views tell us where people go; these tell us
 * whether they actually do anything once they're there.
 *
 * Names are a small fixed vocabulary (see FEATURES below) rather than free text, so the
 * dashboard's feature table doesn't fragment into near-duplicates the first time a label is
 * typed slightly differently at a new call site.
 */
export function trackFeature(name: Feature): void {
  void track('feature', name);
}

/** The vocabulary of trackable actions. Add here first, then use — that's the point. */
export const FEATURES = [
  'game_sheet_open',
  'player_profile_open',
  'pulse_detail_open',
  'news_story_open',
  'roster_move_source_open',
  'team_mode_switch',
  'favorite_toggle',
  'report_open',
  // Onboarding / comprehension. The beta shipped with the Pulse detail opened by only ~4% of
  // sessions, so these measure the funnel into it rather than just the destination:
  // was the home-screen coachmark seen, did it get tapped through, and does anyone go
  // looking for the explainer on their own.
  'coach_pulse_shown',
  'coach_pulse_tapped',
  'coach_pulse_dismissed',
  'pulse_explainer_open',
  'help_open',
] as const;
export type Feature = (typeof FEATURES)[number];

// --- Session length -------------------------------------------------------------------
// A "session" is one uninterrupted stretch in the foreground. We stamp the start when the app
// becomes active and emit the measured duration when it leaves, which is the only way to get a
// real number -- an event stream alone can't tell a 5-second glance from a 5-minute read,
// because both look like one timestamp.
//
// Sessions that end because the OS killed the app never send this. That's unavoidable, so the
// dashboard treats session_end as the accurate source and falls back to inferring a session
// from event gaps where one is missing, rather than dropping those sessions entirely.

// Anything under a second is a bounce through the app switcher, not a session.
const MIN_SESSION_MS = 1000;
// A phone left awake on the Pulse tab overnight would otherwise drag the average up on its own.
// Past this we know the number is a stuck foreground, not attention, so we don't report it.
const MAX_SESSION_MS = 4 * 60 * 60 * 1000;

let sessionStartedAt = 0;

/** Foreground began. Safe to call repeatedly; only the first call starts the clock. */
export function startSession(): void {
  if (!sessionStartedAt) sessionStartedAt = Date.now();
}

/** Foreground ended — emit how long it lasted, then reset for the next one. */
export function endSession(): void {
  if (!sessionStartedAt) return;
  const ms = Date.now() - sessionStartedAt;
  sessionStartedAt = 0;
  if (ms < MIN_SESSION_MS || ms > MAX_SESSION_MS) return;
  void track('session_end', undefined, ms);
}
