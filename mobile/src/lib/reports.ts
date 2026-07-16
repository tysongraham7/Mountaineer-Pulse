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

/**
 * Submit an in-app error / feedback report. Writes to the `error_reports`
 * table, which is insert-only for the anon key — the app can send but never
 * read reports back (the founder reads them server-side via read_reports.py).
 * Returns true on success.
 */
export async function submitErrorReport(
  category: ReportCategory,
  message: string,
  context?: ReportContext,
): Promise<boolean> {
  const body = message.trim();
  if (!body) return false;
  const { error } = await supabase.from('error_reports').insert({
    category,
    message: body.slice(0, 2000),
    context: context && Object.keys(context).length ? context : null,
    app_version: Constants.expoConfig?.version ?? null,
    platform: Platform.OS,
  });
  return !error;
}
