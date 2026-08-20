import AsyncStorage from '@react-native-async-storage/async-storage';
import Constants from 'expo-constants';
import * as Device from 'expo-device';
import * as Notifications from 'expo-notifications';
import { Platform } from 'react-native';

import { supabase } from '@/lib/supabase';

// Persisted user intent — separate from OS permission. Turning alerts OFF must stick even
// though iOS keeps the permission granted, and the foreground token-sync must not silently
// re-enable a token the user chose to turn off.
const ALERTS_PREF = 'mp-alerts-enabled';

// "<token>|<iso>" for the last registration that succeeded. syncPushRegistration runs on every
// launch and every foreground, which meant a database write every time someone glanced at the
// app. Keyed on the TOKEN rather than a timer, so a token that actually changes re-registers
// immediately instead of waiting out a cooldown — the whole point of the self-heal.
const REGISTERED = 'mp-push-registered';
// Re-register anyway once a week, so a row lost server-side can't leave a device silently
// unreachable forever just because its token never changed.
const REREGISTER_AFTER_MS = 7 * 24 * 60 * 60 * 1000;

async function permissionGranted(): Promise<boolean> {
  const { status } = await Notifications.getPermissionsAsync();
  return status === 'granted';
}

// How notifications behave when the app is in the FOREGROUND (show the banner anyway).
export function configureNotificationHandler(): void {
  Notifications.setNotificationHandler({
    handleNotification: async () => ({
      shouldShowBanner: true,
      shouldShowList: true,
      shouldPlaySound: true,
      shouldSetBadge: false,
    }),
  });
}

/**
 * Android delivers nothing without a channel: a push whose channel doesn't exist is dropped
 * by the OS, silently. Creating it only inside enableAlerts() covers the device that opted in
 * on this install, but not the one restored from a backup or reinstalled with permission
 * already granted — there, the first briefing would simply never arrive. So it runs at every
 * startup as well. setNotificationChannelAsync is idempotent, and a no-op off Android.
 */
export async function ensureAndroidChannel(): Promise<void> {
  if (Platform.OS !== 'android') return;
  await Notifications.setNotificationChannelAsync('default', {
    name: 'Mountaineer Pulse',
    importance: Notifications.AndroidImportance.DEFAULT,
    lightColor: '#EAA000',
  });
}

function easProjectId(): string | undefined {
  const extra = Constants.expoConfig?.extra as { eas?: { projectId?: string } } | undefined;
  return extra?.eas?.projectId ?? Constants.easConfig?.projectId;
}

async function currentToken(retries = 2): Promise<string | null> {
  const projectId = easProjectId();
  if (!projectId) return null;
  // On the FIRST permission grant, iOS may not have finished APNs registration yet, so the
  // first getExpoPushTokenAsync can fail. Retry a couple times so the token reliably lands.
  for (let attempt = 0; attempt <= retries; attempt += 1) {
    try {
      const { data } = await Notifications.getExpoPushTokenAsync({ projectId });
      if (data) return data;
    } catch {
      // fall through to retry
    }
    if (attempt < retries) await new Promise((r) => setTimeout(r, 1200));
  }
  return null;
}

/** Register/enable this device's token in Supabase (idempotent). Returns success. */
async function saveToken(token: string): Promise<boolean> {
  // One RPC, no failure expected. This used to be a plain insert with an update fallback,
  // because PostgREST's upsert emits INSERT ... ON CONFLICT and that needs a SELECT policy to
  // identify the conflicting row — which push_tokens deliberately doesn't have (a readable
  // token table lets anyone notify any device). The catch was that the insert was *expected*
  // to fail for every already-registered device, so every app open logged a duplicate-key
  // error in Postgres. Nobody saw it, but the log filled with them.
  //
  // register_push_token does the same upsert server-side as security definer, so it bypasses
  // the missing SELECT policy without exposing the table.
  const { error } = await supabase.rpc('register_push_token', {
    p_token: token,
    p_platform: Platform.OS,
  });
  if (error) {
    console.warn('push token registration failed:', error.message);
    return false;
  }
  await AsyncStorage.setItem(REGISTERED, `${token}|${new Date().toISOString()}`);
  return true;
}

/** Effective alerts state: OS permission granted AND the user hasn't turned alerts off in-app. */
export async function areAlertsEnabled(): Promise<boolean> {
  if (!(await permissionGranted())) return false;
  return (await AsyncStorage.getItem(ALERTS_PREF)) !== 'false';
}

/**
 * Self-healing registration: if the OS has granted permission AND the user hasn't turned alerts
 * off, make sure this device's token is registered and enabled. Safe to call on every app
 * launch/foreground — it never prompts and the write is idempotent. Covers the case where the
 * first token fetch right after granting raced with iOS APNs registration and didn't save.
 */
export async function syncPushRegistration(): Promise<void> {
  if (!Device.isDevice) return;
  if (!(await permissionGranted())) return;
  if ((await AsyncStorage.getItem(ALERTS_PREF)) === 'false') return; // user turned alerts off
  const token = await currentToken();
  if (!token) return;
  // Nothing to do if this exact token registered successfully and recently. A changed token
  // falls straight through and re-registers, which is the case this function exists for.
  const [lastToken, lastAt] = ((await AsyncStorage.getItem(REGISTERED)) ?? '').split('|');
  const at = lastAt ? new Date(lastAt).getTime() : 0;
  if (lastToken === token && at && Date.now() - at < REREGISTER_AFTER_MS) return;
  await saveToken(token);
}

/**
 * Ask permission (if needed), fetch this device's Expo push token, and register it
 * in Supabase. Returns the token on success, or null if unavailable/denied.
 * Note: push tokens only exist on physical devices — not simulators or Expo Go.
 */
export async function enableAlerts(): Promise<string | null> {
  if (!Device.isDevice) return null;

  const existing = await Notifications.getPermissionsAsync();
  let status = existing.status;
  if (status !== 'granted') {
    status = (await Notifications.requestPermissionsAsync()).status;
  }
  if (status !== 'granted') return null;

  // Permission is granted — record the user's intent up front so the bell/switch reflect ON
  // immediately, even if the token fetch below momentarily races APNs (the sync self-heals it).
  await AsyncStorage.setItem(ALERTS_PREF, 'true');

  await ensureAndroidChannel();

  const token = await currentToken();
  if (!token) return null;
  return (await saveToken(token)) ? token : null;
}

/** Mark this device's token disabled (best-effort) when the user turns alerts off. */
export async function disableAlerts(): Promise<void> {
  await AsyncStorage.setItem(ALERTS_PREF, 'false'); // persist intent so it survives restarts
  // Drop the cache too, so the invariant stays "cached => the server has this token enabled".
  // Turning alerts back on re-registers unconditionally anyway; this just keeps the two honest.
  await AsyncStorage.removeItem(REGISTERED);
  const token = await currentToken();
  if (!token) return;
  await supabase
    .from('push_tokens')
    .update({ enabled: false, updated_at: new Date().toISOString() })
    .eq('token', token);
}
