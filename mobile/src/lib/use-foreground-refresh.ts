import { useEffect, useRef } from 'react';
import { AppState } from 'react-native';

/**
 * Runs `onForeground` whenever the app comes back to the foreground — so opening the app (e.g. by
 * tapping the morning-briefing notification) shows fresh data instead of whatever was loaded last
 * time. Throttled so rapid app-switching doesn't refetch repeatedly.
 */
export function useForegroundRefresh(onForeground: () => void, minGapMs = 15000): void {
  const cb = useRef(onForeground);
  cb.current = onForeground;
  const last = useRef(Date.now()); // screen just mounted+loaded — don't immediately refetch

  useEffect(() => {
    const sub = AppState.addEventListener('change', (s) => {
      if (s === 'active' && Date.now() - last.current > minGapMs) {
        last.current = Date.now();
        cb.current();
      }
    });
    return () => sub.remove();
  }, [minGapMs]);
}
