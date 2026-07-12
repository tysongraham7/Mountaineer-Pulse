import { Ionicons } from '@expo/vector-icons';
import { LinearGradient } from 'expo-linear-gradient';
import { useCallback, useEffect, useState } from 'react';
import {
  ActivityIndicator,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { PulseDetail } from '@/components/pulse-detail';
import { Card, RidgeMark, SectionLabel, Sparkline, TrendTag, Wordmark } from '@/components/ui';
import { Brand, Elevation, Font, Gradients, surfaces } from '@/constants/brand';
import { useFavorites } from '@/lib/favorites';
import { supabase } from '@/lib/supabase';

const c = surfaces(true);

const SPORT_NAME: Record<string, string> = {
  football: 'Football',
  mbb: "Men's Basketball",
  baseball: 'Baseball',
};
const SPORT_EMOJI: Record<string, string> = { football: '🏈', mbb: '🏀', baseball: '⚾' };
const SPORT_ORDER = ['football', 'mbb', 'baseball'];

type Driver = { label: string; delta?: number; kind: string };
type Snapshot = {
  sport_id: string;
  date: string;
  score: number;
  trend: string;
  ranking: number | null;
  explanation: string | null;
  drivers: Driver[] | null;
};
type Overall = { date: string; score: number; summary: string | null };
type Briefing = { date: string; content: string };
type Rec = { w: number; l: number; season: number };

function todayLabel() {
  return new Date().toLocaleDateString('en-US', {
    weekday: 'long',
    month: 'long',
    day: 'numeric',
  });
}

export default function PulseScreen() {
  const insets = useSafeAreaInsets();
  const [overall, setOverall] = useState<Overall | null>(null);
  const [overallSeries, setOverallSeries] = useState<number[]>([]);
  const [overallDelta, setOverallDelta] = useState(0);
  const [snaps, setSnaps] = useState<Record<string, Snapshot>>({});
  const [series, setSeries] = useState<Record<string, number[]>>({});
  const [records, setRecords] = useState<Record<string, Rec>>({});
  const [briefing, setBriefing] = useState<Briefing | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [selectedSport, setSelectedSport] = useState<string | null>(null);
  const { favorites } = useFavorites();
  const orderedSports = [...SPORT_ORDER].sort(
    (a, b) => (favorites.includes(b) ? 1 : 0) - (favorites.includes(a) ? 1 : 0),
  );

  const load = useCallback(async () => {
    const [overallRes, snapRes, briefingRes, gamesRes] = await Promise.all([
      supabase.from('pulse_overall').select('*').order('date', { ascending: true }),
      supabase.from('pulse_snapshots').select('*').order('date', { ascending: true }),
      supabase.from('daily_briefings').select('*').order('date', { ascending: false }).limit(1),
      supabase
        .from('games')
        .select('sport_id,season,home_points,away_points,is_wvu_home,status')
        .eq('status', 'final'),
    ]);

    const overalls = (overallRes.data ?? []) as Overall[];
    setOverall(overalls.length ? overalls[overalls.length - 1] : null);
    const oseries = overalls.map((o) => o.score);
    setOverallSeries(oseries.slice(-16));
    setOverallDelta(oseries.length >= 2 ? oseries[oseries.length - 1] - oseries[Math.max(0, oseries.length - 8)] : 0);
    setBriefing((briefingRes.data?.[0] as Briefing) ?? null);

    const latest: Record<string, Snapshot> = {};
    const ser: Record<string, number[]> = {};
    for (const s of (snapRes.data ?? []) as Snapshot[]) {
      latest[s.sport_id] = s; // ascending → ends on newest
      (ser[s.sport_id] = ser[s.sport_id] || []).push(s.score);
    }
    for (const k of Object.keys(ser)) ser[k] = ser[k].slice(-16);
    setSnaps(latest);
    setSeries(ser);

    // Win–loss for each sport's most recent season.
    const games = (gamesRes.data ?? []) as {
      sport_id: string;
      season: number;
      home_points: number;
      away_points: number;
      is_wvu_home: boolean;
    }[];
    const rec: Record<string, Rec> = {};
    const latestSeason: Record<string, number> = {};
    for (const g of games) latestSeason[g.sport_id] = Math.max(latestSeason[g.sport_id] ?? 0, g.season);
    for (const g of games) {
      if (g.season !== latestSeason[g.sport_id]) continue;
      const wvu = g.is_wvu_home ? g.home_points : g.away_points;
      const opp = g.is_wvu_home ? g.away_points : g.home_points;
      const r = (rec[g.sport_id] = rec[g.sport_id] || { w: 0, l: 0, season: g.season });
      if ((wvu ?? 0) > (opp ?? 0)) r.w += 1;
      else r.l += 1;
    }
    setRecords(rec);

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
        <Text style={{ color: c.textSecondary, marginTop: 12, fontFamily: Font.bodyMed }}>
          Taking WVU's pulse…
        </Text>
      </View>
    );
  }

  const trendColor = overallDelta > 0 ? Brand.green : overallDelta < 0 ? Brand.red : c.textSecondary;

  const body = (
    <ScrollView
      style={{ backgroundColor: c.bg }}
      contentContainerStyle={[styles.content, { paddingTop: insets.top + 10 }]}
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
      {/* Header */}
      <View style={styles.header}>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 10 }}>
          <RidgeMark size={34} />
          <View>
            <Wordmark size={17} />
            <Text style={styles.headerSub}>{todayLabel()} · Morgantown</Text>
          </View>
        </View>
        <View style={styles.bell}>
          <Ionicons name="notifications-outline" size={17} color={c.textSecondary} />
        </View>
      </View>

      {/* Overall pulse hero */}
      <LinearGradient
        colors={Gradients.hero}
        start={{ x: 0.1, y: 0 }}
        end={{ x: 0.9, y: 1 }}
        style={[styles.hero, Elevation.hero]}>
        <View style={{ flex: 1 }}>
          <SectionLabel tone="muted" style={{ color: c.blueLabel } as never}>
            OVERALL PROGRAM PULSE
          </SectionLabel>
          <View style={styles.heroScoreRow}>
            <Text style={styles.heroScore}>{overall ? overall.score : '—'}</Text>
            <Text style={styles.heroOutOf}>/ 100</Text>
          </View>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6, marginTop: 6 }}>
            <Text style={{ fontFamily: Font.bodyBold, fontSize: 12, color: trendColor }}>
              {overallDelta > 0 ? '▲' : overallDelta < 0 ? '▼' : '▶'} {overallDelta > 0 ? '+' : ''}
              {overallDelta}
            </Text>
            <Text style={{ color: c.blueLabel, fontSize: 12 }}>this week</Text>
          </View>
        </View>
        <Sparkline data={overallSeries} color={Brand.gold} width={140} height={68} />
      </LinearGradient>

      {/* Daily briefing */}
      {briefing && (
        <Card style={styles.briefing}>
          <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' }}>
            <SectionLabel>Daily Briefing</SectionLabel>
          </View>
          <Text style={styles.briefingBody}>{briefing.content}</Text>
        </Card>
      )}

      {/* Program pulse */}
      <View style={styles.sectionRow}>
        <Text style={styles.sectionTitle}>Program Pulse</Text>
      </View>

      {orderedSports.map((sport) => {
        const s = snaps[sport];
        const rec = records[sport];
        const meta: string[] = [];
        if (rec) meta.push(`${rec.w}–${rec.l} · ${rec.season}`);
        if (s?.ranking) meta.push(`#${s.ranking}`);
        const scoreColor = (s?.score ?? 0) >= 60 ? Brand.gold : c.text;
        const sser = series[sport] ?? [];
        const sdelta = sser.length >= 2 ? sser[sser.length - 1] - sser[Math.max(0, sser.length - 8)] : 0;
        const lineColor = sdelta > 0 ? Brand.green : sdelta < 0 ? Brand.red : c.textSecondary;
        const goldTile = sport !== 'mbb';
        return (
          <Pressable
            key={sport}
            onPress={() => setSelectedSport(sport)}
            style={({ pressed }) => [styles.sportCard, { opacity: pressed ? 0.75 : 1 }]}>
            <View
              style={[
                styles.tile,
                goldTile
                  ? { backgroundColor: Brand.goldTint, borderColor: Brand.goldBorder }
                  : { backgroundColor: 'rgba(159,180,206,0.07)', borderColor: 'rgba(159,180,206,0.14)' },
              ]}>
              <Text style={{ fontSize: 19 }}>{SPORT_EMOJI[sport]}</Text>
            </View>
            <View style={{ flex: 1 }}>
              <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
                {favorites.includes(sport) && <Ionicons name="star" size={13} color={Brand.gold} />}
                <Text style={styles.sportName}>{SPORT_NAME[sport]}</Text>
                {meta.length > 0 && <Text style={styles.sportMeta}>{meta.join(' · ')}</Text>}
              </View>
              {s?.drivers && s.drivers.length > 0 && (
                <View style={styles.driverRow}>
                  {s.drivers.slice(0, 2).map((d, i) => {
                    const pos = (d.delta ?? 0) >= 0;
                    const isNews = d.kind === 'news' || d.kind === 'rank';
                    return (
                      <View
                        key={i}
                        style={[
                          styles.driverChip,
                          {
                            backgroundColor: isNews
                              ? c.surface2
                              : pos
                                ? Brand.greenTint
                                : Brand.redTint,
                          },
                        ]}>
                        <Text
                          style={{
                            fontFamily: Font.bodyBold,
                            fontSize: 10,
                            color: isNews ? c.textSecondary : pos ? Brand.green : Brand.red,
                          }}>
                          {d.label}
                        </Text>
                      </View>
                    );
                  })}
                </View>
              )}
            </View>
            <Sparkline data={sser} color={lineColor} width={56} height={30} />
            <View style={{ alignItems: 'flex-end', minWidth: 40 }}>
              <Text style={[styles.sportScore, { color: scoreColor }]}>{s ? s.score : '—'}</Text>
              {s && (
                <View style={{ marginTop: 2 }}>
                  <TrendTag trend={sdelta > 0 ? 'up' : sdelta < 0 ? 'down' : 'neutral'} delta={sdelta} />
                </View>
              )}
            </View>
          </Pressable>
        );
      })}

      <Text style={styles.footer}>Tap a program to see its Pulse over time, day by day.</Text>
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
  content: { paddingHorizontal: 20, paddingBottom: 40 },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingVertical: 8,
    marginBottom: 6,
  },
  headerSub: { fontFamily: Font.body, fontSize: 11, color: c.textMuted, marginTop: 3 },
  bell: {
    width: 34,
    height: 34,
    borderRadius: 17,
    backgroundColor: c.surface3,
    borderWidth: 1,
    borderColor: c.border,
    alignItems: 'center',
    justifyContent: 'center',
  },
  hero: {
    flexDirection: 'row',
    alignItems: 'center',
    borderRadius: 20,
    borderWidth: 1,
    borderColor: 'rgba(234,170,0,0.18)',
    padding: 18,
    marginTop: 8,
  },
  heroScoreRow: { flexDirection: 'row', alignItems: 'baseline', gap: 8, marginTop: 4 },
  heroScore: { fontFamily: Font.black, fontSize: 56, lineHeight: 58, color: Brand.gold, letterSpacing: -1.5 },
  heroOutOf: { fontSize: 13, color: c.blueLabel },
  briefing: { padding: 18, marginTop: 14 },
  briefingBody: { fontFamily: Font.body, fontSize: 14, lineHeight: 21, color: c.textSecondary, marginTop: 8 },
  sectionRow: { flexDirection: 'row', alignItems: 'center', marginTop: 22, marginBottom: 10 },
  sectionTitle: { fontFamily: Font.display, fontSize: 18, color: c.text, letterSpacing: -0.3 },
  sportCard: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    backgroundColor: c.card,
    borderWidth: 1,
    borderColor: c.border,
    borderRadius: 18,
    padding: 14,
    marginBottom: 10,
  },
  tile: { width: 44, height: 44, borderRadius: 12, borderWidth: 1, alignItems: 'center', justifyContent: 'center' },
  sportName: { fontFamily: Font.display, fontSize: 15, color: c.text },
  sportMeta: { fontFamily: Font.body, fontSize: 11, color: c.textMuted },
  driverRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 5, marginTop: 7 },
  driverChip: { paddingHorizontal: 8, paddingVertical: 3, borderRadius: 999 },
  sportScore: { fontFamily: Font.black, fontSize: 30, lineHeight: 32 },
  footer: { textAlign: 'center', marginTop: 16, fontSize: 12, color: c.textMuted, fontFamily: Font.body },
});
