import { Ionicons } from '@expo/vector-icons';
import { DarkTheme, DefaultTheme, ThemeProvider } from '@react-navigation/native';
import { Tabs } from 'expo-router';
import { useColorScheme } from 'react-native';

import { Brand } from '@/constants/brand';
import { FavoritesProvider } from '@/lib/favorites';

export default function RootLayout() {
  const scheme = useColorScheme();
  const dark = scheme === 'dark';

  return (
    <FavoritesProvider>
    <ThemeProvider value={dark ? DarkTheme : DefaultTheme}>
      <Tabs
        screenOptions={{
          tabBarActiveTintColor: Brand.gold,
          tabBarInactiveTintColor: '#8a9099',
          tabBarStyle: { backgroundColor: dark ? '#0b0d10' : '#ffffff' },
          headerStyle: { backgroundColor: Brand.blue },
          headerTintColor: '#ffffff',
          headerTitleStyle: { fontWeight: '800', letterSpacing: 0.3 },
        }}>
        <Tabs.Screen
          name="index"
          options={{
            title: 'Pulse',
            headerTitle: 'Mountaineer Pulse',
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
            tabBarIcon: ({ color, size }) => <Ionicons name="newspaper" size={size} color={color} />,
          }}
        />
        <Tabs.Screen
          name="team"
          options={{
            title: 'Team',
            tabBarIcon: ({ color, size }) => (
              <Ionicons name="people" size={size} color={color} />
            ),
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
