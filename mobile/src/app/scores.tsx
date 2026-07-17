import { useCallback, useEffect, useState } from 'react';
import {
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { GameCardSkeleton, Skeleton, SkeletonList } from '@/components/skeleton';
import { SectionLabel, Segmented, SportIcon } from '@/components/ui';
import { Brand, Font, surfaces } from '@/constants/brand';
import { supabase } from '@/lib/supabase';
import { Game } from '@/lib/types';

const c = surfaces(true);

const FILTERS = [
  { key: 'all', label: 'All' },
  { key: 'football', label: 'Football' },
  { key: 'mbb', label: 'Basketball' },
  { key: 'baseball', label: 'Baseball' },
];
const RESULTS_LIMIT = 60;

function formatDate(iso: string | null): string {
  if (!iso) return 'TBD';
  return new Date(iso).toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' });
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
  const insets = useSafeAreaInsets();
  const [games, setGames] = useState<Game[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [filter, setFilter] = useState('football');

  const load = useCallback(async () => {
    const { data } = await supabase.from('games').select('*').order('start_date', { ascending: true });
    setGames((data ?? []) as Game[]);
    setLoading(false);
    setRefreshing(false);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const visible = filter === 'all' ? games : games.filter((g) => g.sport_id === filter);
  const showTag = filter === 'all';

  const startOfToday = new Date();
  startOfToday.setHours(0, 0, 0, 0);
  const upcoming = visible.filter(
    (g) => g.status !== 'final' && g.start_date != null && new Date(g.start_date) >= startOfToday,
  );
  const results = visible.filter((g) => g.status === 'final').reverse().slice(0, RESULTS_LIMIT);

  return (
    <View style={{ flex: 1, backgroundColor: c.bg, paddingTop: insets.top + 10 }}>
      {/* Header + sport filter — pinned above the scroll (stays put like the Team tab) */}
      <View style={styles.header}>
        <Text style={styles.title}>Scores</Text>
        <Text style={styles.headerMeta}>
          {new Date().toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}
        </Text>
      </View>
      <View style={styles.filterBar}>
        <Segmented options={FILTERS} value={filter} onChange={setFilter} />
      </View>

      <ScrollView
        contentContainerStyle={styles.content}
        refreshControl={
          <RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} tintColor={Brand.gold} />
        }>
        {loading ? (
          <>
            <Skeleton width={72} height={11} radius={4} style={styles.sectionLabel} />
            <SkeletonList count={5}>
              <GameCardSkeleton />
            </SkeletonList>
          </>
        ) : (
          <>
            {upcoming.length > 0 && (
              <>
                <SectionLabel style={styles.sectionLabel as never}>Upcoming</SectionLabel>
                {upcoming.map((g) => <GameCard key={g.id} game={g} showTag={showTag} />)}
              </>
            )}
            {results.length > 0 && (
              <>
                <SectionLabel tone="muted" style={styles.sectionLabel as never}>Final</SectionLabel>
                {results.map((g) => <GameCard key={g.id} game={g} showTag={showTag} />)}
              </>
            )}
            {upcoming.length === 0 && results.length === 0 && (
              <Text style={styles.empty}>No games to show yet.</Text>
            )}
          </>
        )}
      </ScrollView>
    </View>
  );
}

function GameCard({ game, showTag }: { game: Game; showTag: boolean }) {
  const p = fromWvuView(game);
  return (
    <View style={styles.card}>
      <View style={styles.tile}>
        <SportIcon sport={game.sport_id} size={20} color={Brand.gold} />
      </View>
      <View style={{ flex: 1 }}>
        <Text style={styles.matchup} numberOfLines={1}>
          <Text style={{ color: c.textSecondary }}>{p.locator} </Text>
          {p.opponent}
        </Text>
        <Text style={styles.meta}>{formatDate(game.start_date)}{showTag ? ` · ${labelOf(game.sport_id)}` : ''}</Text>
      </View>
      {p.final ? (
        <Text style={[styles.result, { color: p.win ? Brand.green : Brand.red }]}>
          {p.win ? 'W' : 'L'} {p.scoreText}
        </Text>
      ) : (
        <Text style={styles.chevron}>›</Text>
      )}
    </View>
  );
}

function labelOf(id: string) {
  return id === 'football' ? 'FB' : id === 'mbb' ? 'MBB' : id === 'baseball' ? 'BSB' : id;
}

const styles = StyleSheet.create({
  center: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  content: { paddingHorizontal: 20, paddingBottom: 40 },
  header: { flexDirection: 'row', alignItems: 'baseline', justifyContent: 'space-between', paddingHorizontal: 20, paddingVertical: 8 },
  filterBar: { paddingHorizontal: 20, marginBottom: 4 },
  title: { fontFamily: Font.display, fontSize: 24, color: c.text, letterSpacing: -0.4 },
  headerMeta: { fontFamily: Font.body, fontSize: 12, color: c.textMuted },
  sectionLabel: { marginTop: 20, marginBottom: 8 },
  empty: { fontSize: 14, paddingVertical: 24, textAlign: 'center', color: c.textSecondary, fontFamily: Font.body },
  card: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    backgroundColor: c.card,
    borderWidth: 1,
    borderColor: c.border,
    borderRadius: 16,
    padding: 14,
    marginBottom: 8,
  },
  tile: {
    width: 40,
    height: 40,
    borderRadius: 11,
    backgroundColor: Brand.goldTint,
    borderWidth: 1,
    borderColor: Brand.goldBorder,
    alignItems: 'center',
    justifyContent: 'center',
  },
  matchup: { fontFamily: Font.displaySemi, fontSize: 15, color: c.text },
  meta: { fontFamily: Font.body, fontSize: 12, color: c.textSecondary, marginTop: 2 },
  result: { fontFamily: Font.black, fontSize: 18 },
  chevron: { fontSize: 20, color: c.textMuted },
});
