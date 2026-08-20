import * as Notifications from 'expo-notifications';
import { router, useRootNavigationState } from 'expo-router';
import { useEffect, useRef } from 'react';

/**
 * Sends a notification tap to the screen the push is about.
 *
 * Before this, every alert dropped you on whatever tab you happened to have open last. You'd
 * read "WVU basketball player is no longer with the program" on the lock screen, tap, and land
 * on the Pulse tab with nothing on it about that — the alert and the app were disconnected.
 *
 * We deliberately do NOT open the source article. The tap would leave the app instantly, often
 * into a paywall, and the user would never see that we already have the story. Landing on News
 * with the story pinned at the top gives it context and keeps the article one tap away.
 *
 * Two entry points, because they are genuinely different situations:
 *   COLD START  the app was not running. getLastNotificationResponseAsync() replays the tap.
 *   WARM TAP    the app was already alive. The listener fires.
 *
 * Both are deduped by notification id. getLastNotificationResponseAsync keeps returning the
 * same response on every launch until another notification arrives, so without this the app
 * would re-navigate to a week-old story every time it opened.
 */

const TAB_FOR_SCREEN: Record<string, string> = {
  pulse: '/',
  index: '/',
  // Breaking news lands on the HOME screen, not the News tab. The News tab is a list of
  // outbound links — a new user has no way to know the story they were alerted about is
  // behind one of those headlines. Home shows the story itself, written out.
  breaking: '/',
  scores: '/scores',
  news: '/news',
  team: '/team',
  you: '/you',
};

type PushData = { screen?: string; newsId?: string };

export function usePushRouting(): void {
  // expo-router throws if you navigate before the root navigator has mounted. On a cold start
  // the replayed response is usually ready first, so hold it until navigation state exists.
  const navReady = !!useRootNavigationState()?.key;
  const handled = useRef<Set<string>>(new Set());
  const pending = useRef<Notifications.NotificationResponse | null>(null);

  useEffect(() => {
    function route(resp: Notifications.NotificationResponse | null): void {
      if (!resp) return;
      if (!navReady) {
        pending.current = resp; // replay once the navigator is up
        return;
      }
      const id = resp.notification.request.identifier;
      if (id && handled.current.has(id)) return;
      if (id) handled.current.add(id);

      const data = (resp.notification.request.content.data ?? {}) as PushData;
      const path = TAB_FOR_SCREEN[data.screen ?? ''];
      if (!path) return; // unknown or absent screen — just open the app, don't guess

      try {
        // newsId rides along so the News tab can pin and mark the exact story we alerted on.
        if (path === '/news' && data.newsId) {
          router.navigate({ pathname: '/news', params: { highlight: String(data.newsId) } });
        } else {
          router.navigate(path as '/');
        }
      } catch {
        // Navigation must never take the app down over a notification tap.
      }
    }

    if (pending.current && navReady) {
      const p = pending.current;
      pending.current = null;
      route(p);
    }

    Notifications.getLastNotificationResponseAsync().then(route).catch(() => {});
    const sub = Notifications.addNotificationResponseReceivedListener(route);
    return () => sub.remove();
  }, [navReady]);
}
