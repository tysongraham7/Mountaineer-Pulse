import { Ionicons } from '@expo/vector-icons';
import Constants from 'expo-constants';
import { Pressable, ScrollView, StyleSheet, Text, View, useColorScheme } from 'react-native';

import { Brand, surfaces } from '@/constants/brand';
import { useFavorites } from '@/lib/favorites';

const SPORTS = [
  { id: 'football', name: 'Football', icon: 'american-football' },
  { id: 'mbb', name: "Men's Basketball", icon: 'basketball' },
  { id: 'baseball', name: 'Baseball', icon: 'baseball' },
] as const;

export default function YouScreen() {
  const dark = useColorScheme() === 'dark';
  const c = surfaces(dark);
  const { favorites, toggle } = useFavorites();
  const version = Constants.expoConfig?.version ?? '1.0.0';

  return (
    <ScrollView style={{ backgroundColor: c.bg }} contentContainerStyle={styles.content}>
      {/* Favorite sports */}
      <SectionTitle text="Favorite Sports" color={c.text} />
      <Text style={[styles.hint, { color: c.textSecondary }]}>
        Star the teams you follow — they move to the top of your Pulse.
      </Text>
      <View style={[styles.card, { backgroundColor: c.card, borderColor: c.border }]}>
        {SPORTS.map((s, i) => {
          const on = favorites.includes(s.id);
          return (
            <Pressable
              key={s.id}
              onPress={() => toggle(s.id)}
              style={[
                styles.row,
                { borderBottomColor: c.border, borderBottomWidth: i === SPORTS.length - 1 ? 0 : 1 },
              ]}>
              <Ionicons name={s.icon} size={20} color={c.textSecondary} style={{ width: 26 }} />
              <Text style={[styles.rowLabel, { color: c.text }]}>{s.name}</Text>
              <Ionicons
                name={on ? 'star' : 'star-outline'}
                size={22}
                color={on ? Brand.gold : c.textSecondary}
              />
            </Pressable>
          );
        })}
      </View>

      {/* Appearance */}
      <SectionTitle text="Appearance" color={c.text} />
      <View style={[styles.card, { backgroundColor: c.card, borderColor: c.border }]}>
        <View style={styles.row}>
          <Ionicons name="contrast" size={20} color={c.textSecondary} style={{ width: 26 }} />
          <Text style={[styles.rowLabel, { color: c.text }]}>Theme</Text>
          <Text style={{ color: c.textSecondary }}>Follows device ({dark ? 'Dark' : 'Light'})</Text>
        </View>
      </View>

      {/* Coming soon */}
      <SectionTitle text="Account & Alerts" color={c.text} />
      <View style={[styles.card, { backgroundColor: c.card, borderColor: c.border }]}>
        <ComingRow icon="person-circle-outline" label="Sign in / create account" c={c} first />
        <ComingRow icon="notifications-outline" label="Game & breaking-news alerts" c={c} />
        <ComingRow icon="bookmark-outline" label="Saved stories" c={c} last />
      </View>

      {/* About */}
      <SectionTitle text="About" color={c.text} />
      <View style={[styles.card, { backgroundColor: c.card, borderColor: c.border }]}>
        <View style={[styles.row, { borderBottomColor: c.border, borderBottomWidth: 1 }]}>
          <Text style={[styles.rowLabel, { color: c.text }]}>Mountaineer Pulse</Text>
          <Text style={{ color: c.textSecondary }}>v{version}</Text>
        </View>
        <Text style={[styles.about, { color: c.textSecondary }]}>
          Unofficial — not affiliated with or endorsed by West Virginia University. Data from
          CollegeFootballData, ESPN, wvusports.com, and public news feeds. Team names are property
          of their respective owners.
        </Text>
      </View>

      <Text style={[styles.footer, { color: c.textSecondary }]}>Let's go, Mountaineers. 🏔️💙💛</Text>
    </ScrollView>
  );
}

function SectionTitle({ text, color }: { text: string; color: string }) {
  return (
    <View style={styles.sectionRow}>
      <View style={styles.goldBar} />
      <Text style={[styles.sectionTitle, { color }]}>{text}</Text>
    </View>
  );
}

function ComingRow({
  icon,
  label,
  c,
  first,
  last,
}: {
  icon: keyof typeof Ionicons.glyphMap;
  label: string;
  c: ReturnType<typeof surfaces>;
  first?: boolean;
  last?: boolean;
}) {
  return (
    <View style={[styles.row, { borderBottomColor: c.border, borderBottomWidth: last ? 0 : 1, opacity: 0.6 }]}>
      <Ionicons name={icon} size={20} color={c.textSecondary} style={{ width: 26 }} />
      <Text style={[styles.rowLabel, { color: c.text }]}>{label}</Text>
      <View style={[styles.soon, { borderColor: c.border }]}>
        <Text style={[styles.soonText, { color: c.textSecondary }]}>Soon</Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  content: { padding: 16, paddingBottom: 40 },
  sectionRow: { flexDirection: 'row', alignItems: 'center', marginTop: 20, marginBottom: 8 },
  goldBar: { width: 4, height: 20, borderRadius: 2, backgroundColor: Brand.gold, marginRight: 8 },
  sectionTitle: { fontSize: 20, fontWeight: '800' },
  hint: { fontSize: 13, marginBottom: 10, marginTop: -2 },
  card: { borderWidth: 1, borderRadius: 14, paddingHorizontal: 14, overflow: 'hidden' },
  row: { flexDirection: 'row', alignItems: 'center', gap: 12, paddingVertical: 15 },
  rowLabel: { flex: 1, fontSize: 16, fontWeight: '600' },
  soon: { borderWidth: 1, borderRadius: 6, paddingHorizontal: 7, paddingVertical: 2 },
  soonText: { fontSize: 11, fontWeight: '800' },
  about: { fontSize: 12, lineHeight: 18, paddingVertical: 14 },
  footer: { textAlign: 'center', marginTop: 22, fontSize: 13, fontWeight: '600' },
});
