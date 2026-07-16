import Constants from 'expo-constants';
import { useEffect, useState } from 'react';
import { Alert, Pressable, ScrollView, StyleSheet, Switch, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { RidgeMark, SectionLabel, SportIcon } from '@/components/ui';
import { Brand, Font, surfaces } from '@/constants/brand';
import { useFavorites } from '@/lib/favorites';
import { areAlertsEnabled, disableAlerts, enableAlerts } from '@/lib/notifications';

const c = surfaces(true);

const SPORTS = [
  { id: 'football', name: 'Football', gold: true },
  { id: 'mbb', name: "Men's Basketball", gold: false },
  { id: 'baseball', name: 'Baseball', gold: true },
];

export default function YouScreen() {
  const insets = useSafeAreaInsets();
  const { favorites, toggle } = useFavorites();
  const version = Constants.expoConfig?.version ?? '2.0.0';

  const [alertsOn, setAlertsOn] = useState(false);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    areAlertsEnabled().then(setAlertsOn);
  }, []);

  const toggleAlerts = async (next: boolean) => {
    if (busy) return;
    setBusy(true);
    if (next) {
      const token = await enableAlerts();
      setAlertsOn(!!token);
      if (!token) {
        Alert.alert(
          'Turn on alerts',
          'Enable notifications for Mountaineer Pulse in your device Settings to get game and breaking-news alerts.',
        );
      }
    } else {
      await disableAlerts();
      setAlertsOn(false);
    }
    setBusy(false);
  };

  return (
    <View style={{ flex: 1, backgroundColor: c.bg, paddingTop: insets.top + 10 }}>
      {/* Header — pinned above the scroll (stays put like the Team tab) */}
      <View style={styles.header}>
        <Text style={styles.title}>You</Text>
      </View>
      <ScrollView
        style={{ backgroundColor: c.bg }}
        contentContainerStyle={styles.content}>
      <SectionLabel style={{ marginTop: 8, marginBottom: 4 } as never}>Favorite Sports</SectionLabel>
      <Text style={styles.hint}>Starred teams move to the top of your Pulse.</Text>
      <View style={styles.card}>
        {SPORTS.map((s, i) => {
          const on = favorites.includes(s.id);
          return (
            <Pressable
              key={s.id}
              onPress={() => toggle(s.id)}
              style={[styles.row, { borderBottomWidth: i === SPORTS.length - 1 ? 0 : 1 }]}>
              <View
                style={[
                  styles.tile,
                  s.gold
                    ? { backgroundColor: Brand.goldTint, borderColor: Brand.goldBorder }
                    : { backgroundColor: 'rgba(159,180,206,0.07)', borderColor: 'rgba(159,180,206,0.14)' },
                ]}>
                <SportIcon sport={s.id} size={18} color={s.gold ? Brand.gold : c.blueLabel} />
              </View>
              <Text style={styles.rowLabel}>{s.name}</Text>
              <Text style={{ fontSize: 17, color: on ? Brand.gold : '#3A4658' }}>{on ? '★' : '☆'}</Text>
            </Pressable>
          );
        })}
      </View>

      <SectionLabel style={{ marginTop: 22, marginBottom: 8 } as never}>Account &amp; Alerts</SectionLabel>
      <View style={styles.card}>
        <ComingRow label="Sign in / create account" first />
        <View style={[styles.row, { borderBottomWidth: 1 }]}>
          <Text style={styles.rowLabel}>Game &amp; breaking-news alerts</Text>
          <Switch
            value={alertsOn}
            onValueChange={toggleAlerts}
            disabled={busy}
            trackColor={{ true: Brand.gold, false: c.surface2 }}
            thumbColor="#ffffff"
            ios_backgroundColor={c.surface2}
          />
        </View>
        <ComingRow label="Saved stories" last />
      </View>

      <SectionLabel tone="muted" style={{ marginTop: 22, marginBottom: 8 } as never}>About</SectionLabel>
      <View style={styles.card}>
        <View style={[styles.row, { borderBottomWidth: 1 }]}>
          <Text style={styles.rowLabel}>Mountaineer Pulse</Text>
          <Text style={styles.meta}>v{version}</Text>
        </View>
        <Text style={styles.about}>
          Unofficial — not affiliated with or endorsed by West Virginia University. Data from
          CollegeFootballData, ESPN, wvusports.com, and public news feeds. Team names are property of
          their respective owners.
        </Text>
      </View>

      <View style={styles.brandFooter}>
        <RidgeMark size={30} />
        <Text style={styles.footerText}>Mountaineer Pulse v{version} · Made in Morgantown</Text>
      </View>
      </ScrollView>
    </View>
  );
}

function ComingRow({ label, first, last }: { label: string; first?: boolean; last?: boolean }) {
  return (
    <View style={[styles.row, { borderBottomWidth: last ? 0 : 1 }]}>
      <Text style={styles.rowLabel}>{label}</Text>
      <View style={styles.soon}>
        <Text style={styles.soonText}>SOON</Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  content: { paddingHorizontal: 20, paddingBottom: 40 },
  header: { paddingHorizontal: 20, paddingVertical: 8 },
  title: { fontFamily: Font.display, fontSize: 24, color: c.text, letterSpacing: -0.4 },
  hint: { fontSize: 12, color: c.textMuted, marginBottom: 8, fontFamily: Font.body },
  card: {
    backgroundColor: c.card,
    borderWidth: 1,
    borderColor: c.border,
    borderRadius: 16,
    paddingHorizontal: 16,
    overflow: 'hidden',
  },
  row: { flexDirection: 'row', alignItems: 'center', gap: 12, paddingVertical: 14, borderBottomColor: c.border },
  tile: { width: 36, height: 36, borderRadius: 10, borderWidth: 1, alignItems: 'center', justifyContent: 'center' },
  rowLabel: { flex: 1, fontSize: 14, color: c.text, fontFamily: Font.bodySemi },
  meta: { color: c.textSecondary, fontSize: 13, fontFamily: Font.body },
  soon: { backgroundColor: c.surface2, borderRadius: 999, paddingHorizontal: 8, paddingVertical: 3 },
  soonText: { fontSize: 10, color: c.textMuted, fontFamily: Font.bodyBold, letterSpacing: 0.5 },
  about: { fontSize: 12, lineHeight: 18, paddingVertical: 14, color: c.textSecondary, fontFamily: Font.body },
  brandFooter: { alignItems: 'center', marginTop: 26, gap: 6 },
  footerText: { fontSize: 11, color: '#3A4658', fontFamily: Font.body },
});
