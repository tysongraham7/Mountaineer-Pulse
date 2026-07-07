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

import { Brand, surfaces } from '@/constants/brand';
import { supabase } from '@/lib/supabase';
import { Game } from '@/lib/types';

const FILTERS = [
  { id: 'all', label: 'All' },
  { id: 'football', label: 'Football' },
  { id: 'mbb', label: 'Basketball' },
  { id: 'baseball', label: 'Baseball' },
] as const;

const SPORT_TAG: Record<string, string> = { football: 'FB', mbb: 'MBB', baseball: 'BSB' };
const RESULTS_LIMIT = 60;

function formatDate(iso: string | null): string {
  if (!iso) return 'TBD';
  return new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
}

function fromWvuView(g: Game) {
  const wvuHome = !!g.is_wvu_home;
  const final = g.status === 'final' && g.home_points != null && g.away_points != null;
  const wvuPts = wvuHome ? g.home_points : g.away_points;
  const oppPts = wvuHome ? g.away_points : g.home_points;
  return {
    opponent: wvuHome ? g.away_team : g.home_team,
    locator: wvuHome ? 'vs' : '@',
    final,
    win: final ? (wvuPts ?? 0) > (oppPts ?? 0) : false,
    scoreText: final ? `${wvuPts}–${oppPts}` : '',
  };
}

export default function ScoresScreen() {
  const dark = useColorScheme() === 'dark';
  const c = surfaces(dark);

  const [games, setGames] = useState<Game[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [filter, setFilter] = useState<(typeof FILTERS)[number]['id']>('football');

  const load = useCallback(async () => {
    const { data } = await supabase.from('games').select('*').order('start_date', { ascending: true });
    setGames((data ?? []) as Game[]);
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
        <Text style={{ color: c.textSecondary, marginTop: 12 }}>Loading…</Text>
      </View>
    );
  }

  const visible = filter === 'all' ? games : games.filter((g) => g.sport_id === filter);

  return (
    <View style={{ flex: 1, backgroundColor: c.bg }}>
      <View style={styles.filterRow}>
        {FILTERS.map((f) => {
          const active = filter === f.id;
          return (
            <Pressable
              key={f.id}
              onPress={() => setFilter(f.id)}
              style={[styles.chip, { backgroundColor: active ? Brand.blue : c.card, borderColor: active ? Brand.blue : c.border }]}>
              <Text style={[styles.chipText, { color: active ? Brand.gold : c.textSecondary }]}>{f.label}</Text>
            </Pressable>
          );
        })}
      </View>

      <ScrollView
        contentContainerStyle={styles.content}
        refreshControl={
          <RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} tintColor={Brand.gold} />
        }>
        <ScheduleView games={visible} c={c} showTag={filter === 'all'} />
      </ScrollView>
    </View>
  );
}

function ScheduleView({ games, c, showTag }: { games: Game[]; c: ReturnType<typeof surfaces>; showTag: boolean }) {
  // "Upcoming" = not final AND still in the future. Past games with no result
  // (postponed/cancelled dates ESPN never scored) shouldn't linger as upcoming.
  const startOfToday = new Date();
  startOfToday.setHours(0, 0, 0, 0);
  const upcoming = games.filter(
    (g) => g.status !== 'final' && g.start_date != null && new Date(g.start_date) >= startOfToday,
  );
  const results = games.filter((g) => g.status === 'final').reverse().slice(0, RESULTS_LIMIT);
  return (
    <>
      {upcoming.length > 0 && (
        <>
          <SectionTitle text="Upcoming" color={c.text} />
          {upcoming.map((g) => <GameCard key={g.id} game={g} c={c} showTag={showTag} />)}
          <View style={{ height: 8 }} />
        </>
      )}
      {results.length > 0 && (
        <>
          <SectionTitle text="Recent Results" color={c.text} />
          {results.map((g) => <GameCard key={g.id} game={g} c={c} showTag={showTag} />)}
        </>
      )}
      {upcoming.length === 0 && results.length === 0 && (
        <Text style={[styles.empty, { color: c.textSecondary }]}>No games to show yet.</Text>
      )}
    </>
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

function GameCard({ game, c, showTag }: { game: Game; c: ReturnType<typeof surfaces>; showTag: boolean }) {
  const p = fromWvuView(game);
  return (
    <View style={[styles.card, { backgroundColor: c.card, borderColor: c.border }]}>
      <View style={styles.cardLeft}>
        <View style={styles.metaRow}>
          {showTag && SPORT_TAG[game.sport_id] && (
            <View style={styles.tag}><Text style={styles.tagText}>{SPORT_TAG[game.sport_id]}</Text></View>
          )}
          <Text style={[styles.date, { color: c.textSecondary }]}>{formatDate(game.start_date)}</Text>
        </View>
        <Text style={[styles.matchup, { color: c.text }]} numberOfLines={1}>
          <Text style={{ color: c.textSecondary }}>{p.locator} </Text>{p.opponent}
        </Text>
      </View>
      <View style={styles.cardRight}>
        {p.final ? (
          <>
            <View style={[styles.badge, { backgroundColor: p.win ? Brand.win : Brand.loss }]}>
              <Text style={styles.badgeText}>{p.win ? 'W' : 'L'}</Text>
            </View>
            <Text style={[styles.score, { color: c.text }]}>{p.scoreText}</Text>
          </>
        ) : (
          <Text style={[styles.upcoming, { color: Brand.gold }]}>Upcoming</Text>
        )}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  center: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  content: { padding: 16, paddingBottom: 40 },
  filterRow: { flexDirection: 'row', gap: 8, paddingHorizontal: 16, paddingTop: 14, paddingBottom: 4, flexWrap: 'wrap' },
  chip: { paddingHorizontal: 14, paddingVertical: 7, borderRadius: 20, borderWidth: 1 },
  chipText: { fontSize: 13, fontWeight: '700' },
  sectionRow: { flexDirection: 'row', alignItems: 'center', marginTop: 12, marginBottom: 8 },
  goldBar: { width: 4, height: 20, borderRadius: 2, backgroundColor: Brand.gold, marginRight: 8 },
  sectionTitle: { fontSize: 20, fontWeight: '800', letterSpacing: 0.3 },
  empty: { fontSize: 14, paddingVertical: 12, textAlign: 'center' },
  card: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', borderWidth: 1, borderRadius: 14, padding: 14, marginBottom: 10 },
  cardLeft: { flex: 1, paddingRight: 10 },
  cardRight: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  metaRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  tag: { backgroundColor: Brand.blue, borderRadius: 5, paddingHorizontal: 6, paddingVertical: 1 },
  tagText: { color: Brand.gold, fontSize: 10, fontWeight: '900' },
  date: { fontSize: 12, fontWeight: '600', textTransform: 'uppercase', letterSpacing: 0.5 },
  matchup: { fontSize: 18, fontWeight: '700', marginTop: 2 },
  badge: { minWidth: 26, height: 26, borderRadius: 13, alignItems: 'center', justifyContent: 'center', paddingHorizontal: 6 },
  badgeText: { color: '#fff', fontWeight: '900', fontSize: 13 },
  score: { fontSize: 18, fontWeight: '800', minWidth: 56, textAlign: 'right' },
  upcoming: { fontSize: 13, fontWeight: '700' },
});
