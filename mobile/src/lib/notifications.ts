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

async function currentToken(): Promise<string | null> {
  const projectId = easProjectId();
  if (!projectId) return null;
  try {
    const { data } = await Notifications.getExpoPushTokenAsync({ projectId });
    return data;
  } catch {
    return null;
  }
}

/** True if the OS has granted notification permission. */
export async function areAlertsEnabled(): Promise<boolean> {
  const { status } = await Notifications.getPermissionsAsync();
  return status === 'granted';
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

  const nowIso = new Date().toISOString();
  // NOTE: don't use upsert() here. PostgREST upsert emits INSERT ... ON CONFLICT, which
  // needs a SELECT policy to identify the conflicting row — and push_tokens has none by
  // design (a readable token table is a spam vector), so any ON CONFLICT write fails RLS.
  // Instead: plain insert, and on a duplicate-key error (token already registered) fall
  // back to an update. Both paths use only the insert/update policies we do grant.
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
      return null;
    }
  }
  return token;
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
