import AsyncStorage from '@react-native-async-storage/async-storage';
import Constants from 'expo-constants';
import { Platform } from 'react-native';

import { supabase } from '@/lib/supabase';

export type ReportCategory = 'data' | 'bug' | 'idea' | 'other';

/** Optional breadcrumbs about where the user was when they reported. */
export type ReportContext = {
  sport?: string;
  screen?: string;
  player?: string;
};

export type SubmitResult =
  | { ok: true }
  | { ok: false; reason: 'empty' | 'rate-limited' | 'failed'; retryAfterMin?: number };

/**
 * Rate limits. These exist to stop double-taps and one frustrated person flooding the
 * inbox — they are NOT the real defense. The publishable key ships inside the app, so
 * anyone can POST to `error_reports` directly without ever opening this screen. The
 * enforcing limit lives in the RLS policy (see migrate.py: error_reports_allowed).
 *
 * Deliberately generous: a real user reporting several genuine bugs in a session should
 * never see a limit message.
 */
const MIN_GAP_MS = 45 * 1000; // no rapid-fire resubmits
const HOUR_MS = 60 * 60 * 1000;
const DAY_MS = 24 * HOUR_MS;
const MAX_PER_HOUR = 5;
const MAX_PER_DAY = 15;

/** Separate from the analytics install id on purpose: a bug report shouldn't be joinable
 *  to someone's browsing history, even inside our own database. */
const REPORTER_KEY = 'mp-reporter-id';
const LOG_KEY = 'mp-report-log';

let cachedReporterId: string | null = null;

function uuid(): string {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (ch) => {
    const r = (Math.random() * 16) | 0;
    const v = ch === 'x' ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

async function reporterId(): Promise<string | null> {
  if (cachedReporterId) return cachedReporterId;
  try {
    let id = await AsyncStorage.getItem(REPORTER_KEY);
    if (!id) {
      id = uuid();
      await AsyncStorage.setItem(REPORTER_KEY, id);
    }
    cachedReporterId = id;
    return id;
  } catch {
    return null; // storage unavailable — the server-side global cap still applies
  }
}

/** Send timestamps from the last 24h, oldest-first. Anything older is dropped. */
async function readLog(now: number): Promise<number[]> {
  try {
    const raw = await AsyncStorage.getItem(LOG_KEY);
    const arr: unknown = raw ? JSON.parse(raw) : [];
    if (!Array.isArray(arr)) return [];
    return arr
      .filter((t): t is number => typeof t === 'number' && t > now - DAY_MS && t <= now)
      .sort((a, b) => a - b);
  } catch {
    return [];
  }
}

function minutesUntil(at: number, now: number): number {
  return Math.max(1, Math.ceil((at - now) / 60000));
}

/** null = allowed. Otherwise the rejection to hand back to the UI. */
function checkLimits(log: number[], now: number): SubmitResult | null {
  const last = log.length ? log[log.length - 1] : 0;
  if (now - last < MIN_GAP_MS) {
    return { ok: false, reason: 'rate-limited', retryAfterMin: 1 };
  }
  const hour = log.filter((t) => t > now - HOUR_MS);
  if (hour.length >= MAX_PER_HOUR) {
    return { ok: false, reason: 'rate-limited', retryAfterMin: minutesUntil(hour[0] + HOUR_MS, now) };
  }
  if (log.length >= MAX_PER_DAY) {
    return { ok: false, reason: 'rate-limited', retryAfterMin: minutesUntil(log[0] + DAY_MS, now) };
  }
  return null;
}

/**
 * Submit an in-app error / feedback report. Writes to the `error_reports` table, which is
 * insert-only for the publishable key — the app can send but never read reports back (the
 * founder reads them server-side via read_reports.py).
 */
export async function submitErrorReport(
  category: ReportCategory,
  message: string,
  context?: ReportContext,
): Promise<SubmitResult> {
  const body = message.trim();
  if (!body) return { ok: false, reason: 'empty' };

  const now = Date.now();
  const log = await readLog(now);
  const limited = checkLimits(log, now);
  if (limited) return limited;

  const { error } = await supabase.from('error_reports').insert({
    category,
    message: body.slice(0, 2000),
    context: context && Object.keys(context).length ? context : null,
    app_version: Constants.expoConfig?.version ?? null,
    platform: Platform.OS,
    anon_id: await reporterId(),
  });

  // A rejected insert is most likely the server-side cap (RLS returns 42501), which we
  // report as rate-limited so the user gets a truthful message instead of "try again".
  if (error) {
    const limitedByServer = error.code === '42501' || /row-level security/i.test(error.message);
    return limitedByServer
      ? { ok: false, reason: 'rate-limited', retryAfterMin: 60 }
      : { ok: false, reason: 'failed' };
  }

  try {
    await AsyncStorage.setItem(LOG_KEY, JSON.stringify([...log, now]));
  } catch {
    // Losing the log only weakens the local cooldown; the server cap still holds.
  }
  return { ok: true };
}
