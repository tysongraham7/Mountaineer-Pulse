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
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { PulseDetail } from '@/components/pulse-detail';
import { Card, RidgeMark, SectionLabel, Sparkline, SportIcon, TrendTag, Wordmark } from '@/components/ui';
import { Brand, Font, surfaces } from '@/constants/brand';
import { useFavorites } from '@/lib/favorites';
import { supabase } from '@/lib/supabase';
import { Briefing } from '@/lib/types';

const c = surfaces(true);

const SPORT_NAME: Record<string, string> = {
  football: 'Football',
  mbb: "Men's Basketball",
  baseball: 'Baseball',
};
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
type Rec = { w: number; l: number; season: number };

function todayLabel() {
  return new Date().toLocaleDateString('en-US', {
    weekday: 'long',
    month: 'long',
    day: 'numeric',
  });
}

// Resample a sport's dated snapshots into ~30 daily points over the past month
// (carry-forward on quiet days), so the preview sparkline is a consistent 1-month timeline.
const DAY = 86400000;
function monthSeries(snaps: { date: string; score: number }[]): number[] {
  if (!snaps.length) return [];
  const parsed = snaps.map((s) => ({ t: new Date(s.date).getTime(), score: s.score }));
  const anchor = parsed[parsed.length - 1].t;
  const out: number[] = [];
  for (let i = 29; i >= 0; i--) {
    const st = anchor - i * DAY;
    let score: number | null = null;
    for (let j = parsed.length - 1; j >= 0; j--) {
      if (parsed[j].t <= st) {
        score = parsed[j].score;
        break;
      }
    }
    if (score != null) out.push(score);
  }
  return out;
}

export default function PulseScreen() {
  const insets = useSafeAreaInsets();
  const [snaps, setSnaps] = useState<Record<string, Snapshot>>({});
  const [series, setSeries] = useState<Record<string, { date: string; score: number }[]>>({});
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
    const [snapRes, briefingRes, gamesRes] = await Promise.all([
      supabase.from('pulse_snapshots').select('*').order('date', { ascending: true }),
      supabase.from('daily_briefings').select('*').order('date', { ascending: false }).limit(1),
      supabase
        .from('games')
        .select('sport_id,season,home_points,away_points,is_wvu_home,status')
        .eq('status', 'final'),
    ]);

    setBriefing((briefingRes.data?.[0] as Briefing) ?? null);

    const latest: Record<string, Snapshot> = {};
    const ser: Record<string, { date: string; score: number }[]> = {};
    for (const s of (snapRes.data ?? []) as Snapshot[]) {
      latest[s.sport_id] = s; // ascending → ends on newest
      (ser[s.sport_id] = ser[s.sport_id] || []).push({ date: s.date, score: s.score });
    }
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

  const body = (
    <View style={{ flex: 1, backgroundColor: c.bg, paddingTop: insets.top + 10 }}>
      {/* Header — pinned above the scroll (stays put like the Team tab) */}
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
      {/* Daily briefing — per-sport sections when available, else plain text */}
      {briefing && (
        <Card style={styles.briefing}>
          <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' }}>
            <SectionLabel>Daily Briefing</SectionLabel>
          </View>
          {briefing.sections?.sections?.length ? (
            <>
              {briefing.sections.intro ? (
                <Text style={styles.briefingIntro}>{briefing.sections.intro}</Text>
              ) : null}
              {briefing.sections.sections.map((sec) => (
                <View key={sec.sport} style={styles.briefSport}>
                  <View style={styles.briefSportHead}>
                    <SportIcon sport={sec.sport} size={15} color={Brand.gold} />
                    <Text style={styles.briefSportName}>{SPORT_NAME[sec.sport] ?? sec.sport}</Text>
                  </View>
                  {sec.items.map((it, i) => (
                    <View key={i} style={styles.briefItem}>
                      <View style={styles.briefBullet} />
                      <View style={{ flex: 1 }}>
                        <Text style={styles.briefTopic}>{it.topic}</Text>
                        <Text style={styles.briefBody}>{it.body}</Text>
                      </View>
                    </View>
                  ))}
                </View>
              ))}
            </>
          ) : (
            <Text style={styles.briefingBody}>{briefing.content}</Text>
          )}
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
        const sser = monthSeries(series[sport] ?? []);
        // Day-over-day change (today vs the prior point) — arrow shows only if it moved.
        const sdelta = sser.length >= 2 ? sser[sser.length - 1] - sser[sser.length - 2] : 0;
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
              <SportIcon sport={sport} size={22} color={goldTile ? Brand.gold : c.blueLabel} />
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
                    // Ranking is a neutral status chip; everything else (incl. news)
                    // is colored by its signed delta — so bad news reads red.
                    const neutral = d.kind === 'rank';
                    return (
                      <View
                        key={i}
                        style={[
                          styles.driverChip,
                          {
                            backgroundColor: neutral
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
                            color: neutral ? c.textSecondary : pos ? Brand.green : Brand.red,
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
              {s && sdelta !== 0 && (
                <View style={{ marginTop: 2 }}>
                  <TrendTag trend={sdelta > 0 ? 'up' : 'down'} delta={sdelta} />
                </View>
              )}
            </View>
          </Pressable>
        );
      })}

      <Text style={styles.footer}>Tap a program to see its Pulse over time, day by day.</Text>
      </ScrollView>
    </View>
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
    paddingHorizontal: 20,
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
  briefing: { padding: 18, marginTop: 16 },
  briefingBody: { fontFamily: Font.body, fontSize: 14, lineHeight: 21, color: c.textSecondary, marginTop: 8 },
  briefingIntro: { fontFamily: Font.bodyMed, fontSize: 14, lineHeight: 21, color: c.text, marginTop: 10 },
  briefSport: { marginTop: 16 },
  briefSportHead: { flexDirection: 'row', alignItems: 'center', gap: 7, marginBottom: 8 },
  briefSportName: { fontFamily: Font.display, fontSize: 14, color: Brand.gold, letterSpacing: 0.2 },
  briefItem: { flexDirection: 'row', gap: 9, marginBottom: 10 },
  briefBullet: { width: 5, height: 5, borderRadius: 3, backgroundColor: Brand.gold, marginTop: 7 },
  briefTopic: { fontFamily: Font.bodyBold, fontSize: 13.5, color: c.text, marginBottom: 2 },
  briefBody: { fontFamily: Font.body, fontSize: 13, lineHeight: 19, color: c.textSecondary },
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
