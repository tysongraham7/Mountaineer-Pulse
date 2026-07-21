import AsyncStorage from '@react-native-async-storage/async-storage';
import Constants from 'expo-constants';
import { Platform } from 'react-native';

import { supabase } from '@/lib/supabase';

/**
 * Anonymous, privacy-first usage analytics.
 *
 * We store a RANDOM per-install id (not a device identifier, no name/email/IP) so we can answer
 * three beta questions: are people coming back (daily-active users), does the morning push pull
 * them in (push opens), and which tabs get used. Events are insert-only — the app can send them
 * but never read them back; the founder reads aggregates server-side (read_analytics.py).
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

async function track(event: string, screen?: string): Promise<void> {
  try {
    const anon_id = await anonId();
    await supabase.from('analytics_events').insert({
      anon_id,
      event,
      screen: screen ?? null,
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
