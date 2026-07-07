import { Ionicons } from '@expo/vector-icons';
import { useCallback, useEffect, useState } from 'react';
import {
  ActivityIndicator,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  View,
  useColorScheme,
} from 'react-native';

import { PulseDetail } from '@/components/pulse-detail';
import { Brand, surfaces } from '@/constants/brand';
import { useFavorites } from '@/lib/favorites';
import { supabase } from '@/lib/supabase';

const SPORT_NAME: Record<string, string> = {
  football: 'Football',
  mbb: "Men's Basketball",
  baseball: 'Baseball',
};
const SPORT_ORDER = ['football', 'mbb', 'baseball'];
const TREND_EMOJI: Record<string, string> = { up: '📈', down: '📉', neutral: '➡️' };

type Driver = { label: string; delta?: number; kind: string };
type Snapshot = {
  sport_id: string;
  date: string;
  score: number;
  trend: string;
  explanation: string | null;
  drivers: Driver[] | null;
};
type Overall = { date: string; score: number; summary: string | null };
type Briefing = { date: string; content: string };

export default function PulseScreen() {
  const dark = useColorScheme() === 'dark';
  const c = surfaces(dark);

  const [overall, setOverall] = useState<Overall | null>(null);
  const [snaps, setSnaps] = useState<Record<string, Snapshot>>({});
  const [briefing, setBriefing] = useState<Briefing | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [selectedSport, setSelectedSport] = useState<string | null>(null);
  const { favorites } = useFavorites();
  // Favorited sports rise to the top.
  const orderedSports = [...SPORT_ORDER].sort(
    (a, b) => (favorites.includes(b) ? 1 : 0) - (favorites.includes(a) ? 1 : 0),
  );

  const load = useCallback(async () => {
    const [overallRes, snapRes, briefingRes] = await Promise.all([
      supabase.from('pulse_overall').select('*').order('date', { ascending: false }).limit(1),
      supabase.from('pulse_snapshots').select('*').order('date', { ascending: false }),
      supabase.from('daily_briefings').select('*').order('date', { ascending: false }).limit(1),
    ]);
    setOverall((overallRes.data?.[0] as Overall) ?? null);
    setBriefing((briefingRes.data?.[0] as Briefing) ?? null);

    const map: Record<string, Snapshot> = {};
    for (const s of (snapRes.data ?? []) as Snapshot[]) {
      if (!map[s.sport_id]) map[s.sport_id] = s; // latest per sport
    }
    setSnaps(map);
    setLoading(false);
    setRefreshing(false);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  if (loading) {
    return (
      <View style={[styles.center, { backgroundColor: c.bg }]}>
        <ActivityIndicator size="large" color={Brand.gold} />
        <Text style={{ color: c.textSecondary, marginTop: 12 }}>Taking WVU's pulse…</Text>
      </View>
    );
  }

  const body = (
    <ScrollView
      style={{ backgroundColor: c.bg }}
      contentContainerStyle={styles.content}
      refreshControl={
        <RefreshControl
          refreshing={refreshing}
          onRefresh={() => {
            setRefreshing(true);
            load();
          }}
          tintColor={Brand.gold}
        />
      }>
      <Text style={[styles.greeting, { color: c.textSecondary }]}>Today in WVU Athletics</Text>

      <View style={[styles.hero, { backgroundColor: Brand.blue }]}>
        <Text style={styles.heroLabel}>OVERALL WVU ATHLETICS</Text>
        <Text style={styles.heroScore}>{overall ? overall.score : '—'}</Text>
        <Text style={styles.heroOutOf}>out of 100</Text>
        {overall?.summary && <Text style={styles.heroNote}>{overall.summary}</Text>}
      </View>

      {briefing && (
        <View style={[styles.briefing, { backgroundColor: c.card, borderColor: c.border }]}>
          <Text style={styles.briefingTitle}>☀️  Daily Briefing</Text>
          <Text style={[styles.briefingBody, { color: c.text }]}>{briefing.content}</Text>
        </View>
      )}

      <View style={styles.sectionRow}>
        <View style={styles.goldBar} />
        <Text style={[styles.sectionTitle, { color: c.text }]}>Program Pulse</Text>
      </View>

      {orderedSports.map((sport) => {
        const s = snaps[sport];
        return (
          <Pressable
            key={sport}
            onPress={() => setSelectedSport(sport)}
            style={({ pressed }) => [
              styles.card,
              { backgroundColor: c.card, borderColor: c.border, opacity: pressed ? 0.7 : 1 },
            ]}>
            <View style={styles.cardTop}>
              <View style={styles.nameWrap}>
                {favorites.includes(sport) && <Ionicons name="star" size={14} color={Brand.gold} />}
                <Text style={[styles.cardName, { color: c.text }]}>{SPORT_NAME[sport]}</Text>
              </View>
              <View style={styles.scoreWrap}>
                <Text style={styles.trend}>{s ? TREND_EMOJI[s.trend] : ''}</Text>
                <Text style={[styles.score, { color: Brand.gold }]}>{s ? s.score : '—'}</Text>
                <Ionicons name="chevron-forward" size={16} color={c.textSecondary} />
              </View>
            </View>
            <Text style={[styles.explanation, { color: c.textSecondary }]}>
              {s?.explanation ?? 'Awaiting data…'}
            </Text>
            {s?.drivers && s.drivers.length > 0 && (
              <View style={styles.driverRow}>
                {s.drivers.map((d, i) => {
                  const hasDelta = d.delta !== undefined && d.delta !== null;
                  const color = hasDelta
                    ? (d.delta as number) >= 0
                      ? Brand.win
                      : Brand.loss
                    : Brand.gold;
                  return (
                    <View key={i} style={[styles.driverChip, { borderColor: color }]}>
                      <Text style={[styles.driverText, { color }]}>{d.label}</Text>
                    </View>
                  );
                })}
              </View>
            )}
          </Pressable>
        );
      })}

      <Text style={[styles.footer, { color: c.textSecondary }]}>
        Tap a program to see its Pulse over time. Trends go live once seasons start.
      </Text>
    </ScrollView>
  );

  return (
    <>
      {body}
      <PulseDetail sport={selectedSport} onClose={() => setSelectedSport(null)} />
    </>
  );
}

const styles = StyleSheet.create({
  center: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  content: { padding: 16, paddingBottom: 40 },
  greeting: { fontSize: 14, fontWeight: '600', marginBottom: 12 },
  hero: { borderRadius: 18, padding: 22, alignItems: 'center', marginBottom: 8 },
  heroLabel: { color: Brand.gold, fontSize: 12, fontWeight: '800', letterSpacing: 1 },
  heroScore: { color: '#fff', fontSize: 60, fontWeight: '900', lineHeight: 64 },
  heroOutOf: { color: '#8ea3bd', fontSize: 12, fontWeight: '700', marginBottom: 8 },
  heroNote: { color: '#c8d2de', fontSize: 13, textAlign: 'center' },
  briefing: { borderWidth: 1, borderRadius: 16, padding: 16, marginTop: 12 },
  briefingTitle: { color: Brand.gold, fontSize: 13, fontWeight: '900', letterSpacing: 0.5, marginBottom: 8 },
  briefingBody: { fontSize: 14, lineHeight: 21 },
  sectionRow: { flexDirection: 'row', alignItems: 'center', marginTop: 18, marginBottom: 10 },
  goldBar: { width: 4, height: 20, borderRadius: 2, backgroundColor: Brand.gold, marginRight: 8 },
  sectionTitle: { fontSize: 20, fontWeight: '800' },
  card: { borderWidth: 1, borderRadius: 14, padding: 16, marginBottom: 10 },
  cardTop: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  nameWrap: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  cardName: { fontSize: 17, fontWeight: '800' },
  scoreWrap: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  trend: { fontSize: 22 },
  score: { fontSize: 26, fontWeight: '900', minWidth: 40, textAlign: 'right' },
  explanation: { fontSize: 13, marginTop: 8, lineHeight: 19 },
  driverRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 6, marginTop: 10 },
  driverChip: { borderWidth: 1, borderRadius: 8, paddingHorizontal: 8, paddingVertical: 3 },
  driverText: { fontSize: 11, fontWeight: '800' },
  footer: { textAlign: 'center', marginTop: 16, fontSize: 12 },
});
