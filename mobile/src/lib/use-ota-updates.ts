import * as Updates from 'expo-updates';
import { useEffect, useRef } from 'react';
import { AppState } from 'react-native';

/**
 * Applies over-the-air updates promptly instead of whenever iOS happens to cold-start the app.
 *
 * Expo's default (`fallbackToCacheTimeout: 0`) launches from the cached bundle and swaps the new
 * one in only on the NEXT cold start. On iOS, reopening from the app switcher is not a cold
 * start — so a user who never fully quits the app can sit on a stale bundle indefinitely. That
 * is exactly what happened after the 2026-08-18 update: the server was serving it correctly and
 * devices still showed the July 29 build.
 *
 * This checks on mount and on every foreground, downloads anything new, and reloads. The reload
 * is deliberately tied to the app coming to the FOREGROUND, where a brief relaunch is
 * indistinguishable from a normal app open — never mid-scroll while someone is reading.
 *
 * Every failure path is swallowed: no network, no update, an Expo Go/dev build where
 * `Updates.isEnabled` is false. A broken update check must never block the app from starting.
 */
export function useOtaUpdates(minGapMs = 60000): void {
  // Guards against overlapping checks — AppState can fire 'active' twice in quick succession,
  // and two concurrent fetches of the same update waste bandwidth on cellular.
  const busy = useRef(false);
  const last = useRef(0);

  useEffect(() => {
    if (!Updates.isEnabled) return; // dev client / Expo Go — nothing to update

    const run = async () => {
      if (busy.current || Date.now() - last.current < minGapMs) return;
      busy.current = true;
      last.current = Date.now();
      try {
        const check = await Updates.checkForUpdateAsync();
        if (check.isAvailable) {
          await Updates.fetchUpdateAsync();
          // Relaunches into the new bundle. Anything after this line does not run.
          await Updates.reloadAsync();
        }
      } catch {
        // Offline, rate-limited, or mid-rollout. Try again on the next foreground.
      } finally {
        busy.current = false;
      }
    };

    run(); // cover the launch that isn't preceded by a foreground event
    const sub = AppState.addEventListener('change', (s) => {
      if (s === 'active') run();
    });
    return () => sub.remove();
  }, [minGapMs]);
}
