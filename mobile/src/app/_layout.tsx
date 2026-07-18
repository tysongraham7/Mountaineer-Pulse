import {
  Archivo_600SemiBold,
  Archivo_700Bold,
  Archivo_800ExtraBold,
  Archivo_900Black,
} from '@expo-google-fonts/archivo';
import {
  InstrumentSans_400Regular,
  InstrumentSans_500Medium,
  InstrumentSans_600SemiBold,
  InstrumentSans_700Bold,
  useFonts,
} from '@expo-google-fonts/instrument-sans';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { Ionicons } from '@expo/vector-icons';
import { DarkTheme, ThemeProvider } from '@react-navigation/native';
import * as Sentry from '@sentry/react-native';
import { Tabs } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { useCallback, useEffect, useState } from 'react';
import { Pressable, Text, View } from 'react-native';

import { Onboarding } from '@/components/onboarding';
import { RidgeMark } from '@/components/ui';
import { Brand, Font, surfaces } from '@/constants/brand';
import { FavoritesProvider } from '@/lib/favorites';
import { configureNotificationHandler } from '@/lib/notifications';

const c = surfaces(true);

// Crash + error monitoring. Initialized as early as possible so anything that throws
// during startup is still captured. The DSN is write-only and safe to ship (like the
// Supabase publishable key). Disabled in dev/Expo Go so the free-tier quota is spent on
// real user crashes, not our own noise; no PII/IP collected.
Sentry.init({
  dsn: 'https://e665d1050d42f0f2d7208aef7803984e@o4511758254080000.ingest.us.sentry.io/4511758281736192',
  enabled: !__DEV__,
  tracesSampleRate: 0, // crashes/errors only for now — keeps us well within the free tier
  sendDefaultPii: false,
});

// Shown instead of a white screen if a render error slips through. The error is already
// reported to Sentry by the boundary; this just gives the user a way out.
function CrashFallback({ onRetry }: { onRetry: () => void }) {
  return (
    <View style={{ flex: 1, backgroundColor: c.bg, alignItems: 'center', justifyContent: 'center', padding: 32, gap: 14 }}>
      <RidgeMark size={44} />
      <Text style={{ fontFamily: Font.display, fontSize: 20, color: c.text, textAlign: 'center' }}>
        Something went wrong
      </Text>
      <Text style={{ fontFamily: Font.body, fontSize: 14, color: c.textSecondary, textAlign: 'center', lineHeight: 20, maxWidth: 300 }}>
        The team's been notified and we're on it. Tap below to jump back in.
      </Text>
      <Pressable
        onPress={onRetry}
        style={{ marginTop: 8, backgroundColor: Brand.gold, borderRadius: 14, paddingVertical: 13, paddingHorizontal: 28 }}>
        <Text style={{ fontFamily: Font.display, fontSize: 15, color: Brand.onGold }}>Try again</Text>
      </Pressable>
    </View>
  );
}

function RootLayout() {
  const [loaded] = useFonts({
    Archivo_600SemiBold,
    Archivo_700Bold,
    Archivo_800ExtraBold,
    Archivo_900Black,
    InstrumentSans_400Regular,
    InstrumentSans_500Medium,
    InstrumentSans_600SemiBold,
    InstrumentSans_700Bold,
  });

  // Show notification banners even when the app is open. Set once, at the root.
  useEffect(() => {
    configureNotificationHandler();
  }, []);

  // First-run onboarding: show once, then remember it's done.
  const [showOnboarding, setShowOnboarding] = useState(false);
  useEffect(() => {
    AsyncStorage.getItem('mp-onboarded').then((v) => setShowOnboarding(!v));
  }, []);
  const finishOnboarding = useCallback(() => {
    AsyncStorage.setItem('mp-onboarded', '1').catch(() => {});
    setShowOnboarding(false);
  }, []);

  // Instrument Sans becomes the app-wide default; screens opt into Archivo for
  // display type. Applied once, here.
  const TextAny = Text as unknown as { defaultProps?: { style?: unknown } };
  TextAny.defaultProps = TextAny.defaultProps || {};
  TextAny.defaultProps.style = [{ fontFamily: Font.body, color: c.text }];

  if (!loaded) return <View style={{ flex: 1, backgroundColor: c.bg }} />;

  return (
    <Sentry.ErrorBoundary fallback={({ resetError }) => <CrashFallback onRetry={resetError} />}>
      <FavoritesProvider>
      <ThemeProvider value={DarkTheme}>
        <StatusBar style="light" />
        <Tabs
          screenOptions={{
            headerShown: false,
            tabBarActiveTintColor: Brand.gold,
            tabBarInactiveTintColor: c.textSecondary,
            tabBarStyle: {
              backgroundColor: c.card,
              borderTopColor: c.border,
              borderTopWidth: 1,
              height: 88,
              paddingTop: 8,
            },
            tabBarLabelStyle: { fontFamily: Font.bodySemi, fontSize: 10, marginTop: 2 },
            sceneStyle: { backgroundColor: c.bg },
          }}>
          <Tabs.Screen
            name="index"
            options={{
              title: 'Pulse',
              tabBarIcon: ({ color, size }) => <RidgeMark size={size + 3} color={color} boxed={false} />,
            }}
          />
          <Tabs.Screen
            name="scores"
            options={{
              title: 'Scores',
              tabBarIcon: ({ color, size }) => (
                <Ionicons name="american-football" size={size} color={color} />
              ),
            }}
          />
          <Tabs.Screen
            name="news"
            options={{
              title: 'News',
              tabBarIcon: ({ color, size }) => (
                <Ionicons name="newspaper" size={size} color={color} />
              ),
            }}
          />
          <Tabs.Screen
            name="team"
            options={{
              title: 'Team',
              tabBarIcon: ({ color, size }) => <Ionicons name="people" size={size} color={color} />,
            }}
          />
          <Tabs.Screen
            name="you"
            options={{
              title: 'You',
              tabBarIcon: ({ color, size }) => <Ionicons name="person" size={size} color={color} />,
            }}
          />
        </Tabs>
        <Onboarding visible={showOnboarding} onDone={finishOnboarding} />
      </ThemeProvider>
      </FavoritesProvider>
    </Sentry.ErrorBoundary>
  );
}

export default Sentry.wrap(RootLayout);
