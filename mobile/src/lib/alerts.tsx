import { createContext, useCallback, useContext, useEffect, useState } from 'react';
import { AppState } from 'react-native';

import { areAlertsEnabled, disableAlerts, enableAlerts } from '@/lib/notifications';

type AlertsContextValue = {
  /** true = on, false = off, null = still reading the OS/intent state */
  alertsOn: boolean | null;
  busy: boolean;
  /** Prompt (if needed), register the token, flip on. Returns whether alerts ended up on. */
  enable: () => Promise<boolean>;
  disable: () => Promise<void>;
};

const AlertsContext = createContext<AlertsContextValue | null>(null);

/**
 * One shared source of truth for the alerts on/off state, so enabling anywhere — onboarding, the
 * home-screen bell, or the You-tab switch — updates every one of them at once. Previously each spot
 * held its own state read once on mount, so enabling in onboarding left the bell showing "off."
 */
export function AlertsProvider({ children }: { children: React.ReactNode }) {
  const [alertsOn, setAlertsOn] = useState<boolean | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(() => {
    areAlertsEnabled().then(setAlertsOn);
  }, []);

  // Read on mount, and re-read when the app returns to the foreground (covers permission
  // being changed in iOS Settings while the app was backgrounded).
  useEffect(() => {
    refresh();
    const sub = AppState.addEventListener('change', (s) => {
      if (s === 'active') refresh();
    });
    return () => sub.remove();
  }, [refresh]);

  const enable = useCallback(async () => {
    setBusy(true);
    await enableAlerts();
    const on = await areAlertsEnabled();
    setAlertsOn(on);
    setBusy(false);
    return on;
  }, []);

  const disable = useCallback(async () => {
    setBusy(true);
    await disableAlerts();
    setAlertsOn(false);
    setBusy(false);
  }, []);

  return (
    <AlertsContext.Provider value={{ alertsOn, busy, enable, disable }}>
      {children}
    </AlertsContext.Provider>
  );
}

export function useAlerts(): AlertsContextValue {
  const v = useContext(AlertsContext);
  if (!v) throw new Error('useAlerts must be used within an AlertsProvider');
  return v;
}
