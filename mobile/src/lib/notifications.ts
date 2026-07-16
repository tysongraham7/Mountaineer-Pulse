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

  await supabase
    .from('push_tokens')
    .upsert(
      { token, platform: Platform.OS, enabled: true, updated_at: new Date().toISOString() },
      { onConflict: 'token' },
    );
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
