import Constants from 'expo-constants';
import * as Device from 'expo-device';
import * as Notifications from 'expo-notifications';
import { Platform } from 'react-native';

import { supabase } from '@/lib/supabase';

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
  const nowIso = new Date().toISOString();
  // NOTE: don't use upsert() here. PostgREST upsert emits INSERT ... ON CONFLICT, which needs a
  // SELECT policy to identify the conflicting row — and push_tokens has none by design (a readable
  // token table is a spam vector), so any ON CONFLICT write fails RLS. Instead: plain insert, and
  // on a duplicate-key error (token already registered) fall back to an update.
  const ins = await supabase
    .from('push_tokens')
    .insert({ token, platform: Platform.OS, enabled: true, updated_at: nowIso });
  if (ins.error) {
    const upd = await supabase
      .from('push_tokens')
      .update({ enabled: true, platform: Platform.OS, updated_at: nowIso })
      .eq('token', token);
    if (upd.error) {
      console.warn('push token registration failed:', upd.error.message);
      return false;
    }
  }
  return true;
}

/** True if the OS has granted notification permission. */
export async function areAlertsEnabled(): Promise<boolean> {
  const { status } = await Notifications.getPermissionsAsync();
  return status === 'granted';
}

/**
 * Self-healing registration: if the OS has ALREADY granted permission, make sure this device's
 * token is registered and enabled. Safe to call on every app launch/foreground — it never prompts
 * and the write is idempotent. This covers the case where the very first token fetch (right after
 * granting) raced with iOS APNs registration and didn't save, so alerts no longer depend on the
 * user re-visiting any particular screen.
 */
export async function syncPushRegistration(): Promise<void> {
  if (!Device.isDevice) return;
  const { status } = await Notifications.getPermissionsAsync();
  if (status !== 'granted') return;
  const token = await currentToken();
  if (token) await saveToken(token);
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

  if (Platform.OS === 'android') {
    await Notifications.setNotificationChannelAsync('default', {
      name: 'Mountaineer Pulse',
      importance: Notifications.AndroidImportance.DEFAULT,
      lightColor: '#EAA000',
    });
  }

  const token = await currentToken();
  if (!token) return null;
  return (await saveToken(token)) ? token : null;
}

/** Mark this device's token disabled (best-effort) when the user turns alerts off. */
export async function disableAlerts(): Promise<void> {
  const token = await currentToken();
  if (!token) return;
  await supabase
    .from('push_tokens')
    .update({ enabled: false, updated_at: new Date().toISOString() })
    .eq('token', token);
}
