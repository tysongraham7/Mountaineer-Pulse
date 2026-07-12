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
import { Ionicons } from '@expo/vector-icons';
import { DarkTheme, ThemeProvider } from '@react-navigation/native';
import { Tabs } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { Text, View } from 'react-native';

import { Brand, Font, surfaces } from '@/constants/brand';
import { FavoritesProvider } from '@/lib/favorites';

const c = surfaces(true);

export default function RootLayout() {
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

  // Instrument Sans becomes the app-wide default; screens opt into Archivo for
  // display type. Applied once, here.
  const TextAny = Text as unknown as { defaultProps?: { style?: unknown } };
  TextAny.defaultProps = TextAny.defaultProps || {};
  TextAny.defaultProps.style = [{ fontFamily: Font.body, color: c.text }];

  if (!loaded) return <View style={{ flex: 1, backgroundColor: c.bg }} />;

  return (
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
              tabBarIcon: ({ color, size }) => <Ionicons name="pulse" size={size} color={color} />,
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
      </ThemeProvider>
    </FavoritesProvider>
  );
}
