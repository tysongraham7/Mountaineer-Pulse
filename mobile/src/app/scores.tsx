import { useCallback, useEffect, useState } from 'react';
import {
  ActivityIndicator,
  Image,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  View,
  useColorScheme,
} from 'react-native';

import { PlayerProfile } from '@/components/player-profile';
import { Brand, surfaces } from '@/constants/brand';
import { supabase } from '@/lib/supabase';
import { Game, Player } from '@/lib/types';

const FILTERS = [
  { id: 'all', label: 'All' },
  { id: 'football', label: 'Football' },
  { id: 'mbb', label: 'Basketball' },
  { id: 'baseball', label: 'Baseball' },
] as const;

const SPORT_LABEL: Record<string, string> = {
  football: 'Football',
  mbb: "Men's Basketball",
  baseball: 'Baseball',
};
const SPORT_TAG: Record<string, string> = { football: 'FB', mbb: 'MBB', baseball: 'BSB' };
const SPORT_ORDER = ['football', 'mbb', 'baseball'];
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
  const [players, setPlayers] = useState<Player[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [filter, setFilter] = useState<(typeof FILTERS)[number]['id']>('football');
  const [mode, setMode] = useState<'schedule' | 'roster'>('schedule');
  const [selected, setSelected] = useState<Player | null>(null);

  const load = useCallback(async () => {
    const [gRes, pRes] = await Promise.all([
      supabase.from('games').select('*').order('start_date', { ascending: true }),
      supabase.from('players').select('*'),
    ]);
    setGames((gRes.data ?? []) as Game[]);
    setPlayers((pRes.data ?? []) as Player[]);
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

  const sports = filter === 'all' ? SPORT_ORDER : [filter];

  return (
    <View style={{ flex: 1, backgroundColor: c.bg }}>
      {/* Schedule / Roster segmented control */}
      <View style={styles.segment}>
        {(['schedule', 'roster'] as const).map((m) => {
          const active = mode === m;
          return (
            <Pressable
              key={m}
              onPress={() => setMode(m)}
              style={[styles.segBtn, { backgroundColor: active ? Brand.gold : 'transparent' }]}>
              <Text style={[styles.segText, { color: active ? Brand.blueDeep : c.textSecondary }]}>
                {m === 'schedule' ? 'Schedule' : 'Roster'}
              </Text>
            </Pressable>
          );
        })}
      </View>

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
        {mode === 'schedule'
          ? <ScheduleView games={filter === 'all' ? games : games.filter((g) => g.sport_id === filter)} c={c} showTag={filter === 'all'} />
          : sports.map((sp) => (
              <RosterSection
                key={sp}
                sport={sp}
                players={players.filter((p) => p.sport_id === sp)}
                c={c}
                onPick={setSelected}
                showHeader={filter === 'all'}
              />
            ))}
      </ScrollView>

      <PlayerProfile player={selected} onClose={() => setSelected(null)} />
    </View>
  );
}

function ScheduleView({ games, c, showTag }: { games: Game[]; c: ReturnType<typeof surfaces>; showTag: boolean }) {
  const upcoming = games.filter((g) => g.status !== 'final');
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
    </>
  );
}

function RosterSection({
  sport,
  players,
  c,
  onPick,
  showHeader,
}: {
  sport: string;
  players: Player[];
  c: ReturnType<typeof surfaces>;
  onPick: (p: Player) => void;
  showHeader: boolean;
}) {
  const sorted = [...players].sort((a, b) => (a.jersey ?? 999) - (b.jersey ?? 999));
  return (
    <>
      {showHeader && <SectionTitle text={SPORT_LABEL[sport]} color={c.text} />}
      {players.length === 0 ? (
        <Text style={[styles.empty, { color: c.textSecondary }]}>
          {sport === 'baseball' ? 'Baseball roster isn’t available yet.' : 'No roster loaded.'}
        </Text>
      ) : (
        sorted.map((p) => <RosterRow key={p.id} player={p} c={c} onPick={onPick} />)
      )}
    </>
  );
}

function RosterRow({ player, c, onPick }: { player: Player; c: ReturnType<typeof surfaces>; onPick: (p: Player) => void }) {
  const name = `${player.first_name ?? ''} ${player.last_name ?? ''}`.trim();
  return (
    <Pressable
      onPress={() => onPick(player)}
      style={({ pressed }) => [styles.rosterRow, { backgroundColor: c.card, borderColor: c.border, opacity: pressed ? 0.7 : 1 }]}>
      {player.photo_url ? (
        <Image source={{ uri: player.photo_url }} style={styles.avatar} />
      ) : (
        <View style={[styles.avatar, styles.avatarFallback, { backgroundColor: Brand.blue }]}>
          <Text style={styles.avatarText}>{(player.first_name?.[0] ?? '') + (player.last_name?.[0] ?? '')}</Text>
        </View>
      )}
      <Text style={[styles.jersey, { color: c.textSecondary }]}>{player.jersey != null ? `#${player.jersey}` : ''}</Text>
      <View style={{ flex: 1 }}>
        <Text style={[styles.playerName, { color: c.text }]} numberOfLines={1}>{name}</Text>
        <Text style={[styles.playerMeta, { color: c.textSecondary }]}>
          {[player.position, player.class_display].filter(Boolean).join(' · ')}
        </Text>
      </View>
      <Text style={{ color: c.textSecondary }}>›</Text>
    </Pressable>
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
  segment: { flexDirection: 'row', margin: 16, marginBottom: 4, borderRadius: 10, backgroundColor: '#8883', padding: 3 },
  segBtn: { flex: 1, paddingVertical: 8, borderRadius: 8, alignItems: 'center' },
  segText: { fontSize: 14, fontWeight: '800' },
  filterRow: { flexDirection: 'row', gap: 8, paddingHorizontal: 16, paddingTop: 8, paddingBottom: 4, flexWrap: 'wrap' },
  chip: { paddingHorizontal: 14, paddingVertical: 7, borderRadius: 20, borderWidth: 1 },
  chipText: { fontSize: 13, fontWeight: '700' },
  sectionRow: { flexDirection: 'row', alignItems: 'center', marginTop: 12, marginBottom: 8 },
  goldBar: { width: 4, height: 20, borderRadius: 2, backgroundColor: Brand.gold, marginRight: 8 },
  sectionTitle: { fontSize: 20, fontWeight: '800', letterSpacing: 0.3 },
  empty: { fontSize: 14, paddingVertical: 12 },
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
  rosterRow: { flexDirection: 'row', alignItems: 'center', gap: 12, borderWidth: 1, borderRadius: 12, padding: 10, marginBottom: 8 },
  avatar: { width: 44, height: 44, borderRadius: 22, backgroundColor: '#0002' },
  avatarFallback: { alignItems: 'center', justifyContent: 'center' },
  avatarText: { color: '#fff', fontWeight: '800', fontSize: 15 },
  jersey: { fontSize: 14, fontWeight: '800', width: 34 },
  playerName: { fontSize: 16, fontWeight: '700' },
  playerMeta: { fontSize: 12, marginTop: 2 },
});
