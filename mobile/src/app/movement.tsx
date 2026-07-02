import { Ionicons } from '@expo/vector-icons';
import * as WebBrowser from 'expo-web-browser';
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
import { RosterMove } from '@/lib/types';

const FILTERS = [
  { id: 'all', label: 'All' },
  { id: 'football', label: 'Football' },
  { id: 'mbb', label: 'Basketball' },
  { id: 'baseball', label: 'Baseball' },
] as const;

const SPORT_TAG: Record<string, string> = { football: 'FB', mbb: 'MBB', baseball: 'BSB' };
const CATEGORY_LABEL: Record<string, string> = {
  transfer: 'Transfer',
  recruit: 'Recruit',
  graduation: 'Graduated',
  draft: 'Draft',
};

function formatDate(iso: string | null): string {
  if (!iso) return '';
  return new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

export default function MovementScreen() {
  const dark = useColorScheme() === 'dark';
  const c = surfaces(dark);

  const [moves, setMoves] = useState<RosterMove[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [filter, setFilter] = useState<(typeof FILTERS)[number]['id']>('all');

  const load = useCallback(async () => {
    const { data } = await supabase
      .from('roster_moves')
      .select('*')
      .order('move_date', { ascending: false });
    setMoves((data ?? []) as RosterMove[]);
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
        <Text style={{ color: c.textSecondary, marginTop: 12 }}>Loading roster movement…</Text>
      </View>
    );
  }

  const visible = filter === 'all' ? moves : moves.filter((m) => m.sport_id === filter);
  const ins = visible.filter((m) => m.direction === 'in').length;
  const outs = visible.filter((m) => m.direction === 'out').length;
  const net = ins - outs;

  return (
    <View style={{ flex: 1, backgroundColor: c.bg }}>
      <View style={styles.filterRow}>
        {FILTERS.map((f) => {
          const active = filter === f.id;
          return (
            <Pressable
              key={f.id}
              onPress={() => setFilter(f.id)}
              style={[
                styles.chip,
                { backgroundColor: active ? Brand.blue : c.card, borderColor: active ? Brand.blue : c.border },
              ]}>
              <Text style={[styles.chipText, { color: active ? Brand.gold : c.textSecondary }]}>
                {f.label}
              </Text>
            </Pressable>
          );
        })}
      </View>

      <ScrollView
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
        <View style={[styles.summary, { backgroundColor: c.card, borderColor: c.border }]}>
          <SummaryStat label="IN" value={`+${ins}`} color={Brand.win} c={c} />
          <View style={[styles.divider, { backgroundColor: c.border }]} />
          <SummaryStat label="OUT" value={`-${outs}`} color={Brand.loss} c={c} />
          <View style={[styles.divider, { backgroundColor: c.border }]} />
          <SummaryStat label="NET" value={net > 0 ? `+${net}` : `${net}`} color={Brand.gold} c={c} />
        </View>

        {visible.length === 0 && (
          <Text style={[styles.empty, { color: c.textSecondary }]}>No moves logged yet.</Text>
        )}

        {visible.map((m) => (
          <MoveCard key={m.id} move={m} c={c} showTag={filter === 'all'} />
        ))}

        <Text style={[styles.footer, { color: c.textSecondary }]}>
          Confirmed portal entries & commitments · curated
        </Text>
      </ScrollView>
    </View>
  );
}

function SummaryStat({
  label,
  value,
  color,
  c,
}: {
  label: string;
  value: string;
  color: string;
  c: ReturnType<typeof surfaces>;
}) {
  return (
    <View style={styles.stat}>
      <Text style={[styles.statValue, { color }]}>{value}</Text>
      <Text style={[styles.statLabel, { color: c.textSecondary }]}>{label}</Text>
    </View>
  );
}

function MoveCard({
  move,
  c,
  showTag,
}: {
  move: RosterMove;
  c: ReturnType<typeof surfaces>;
  showTag: boolean;
}) {
  const isIn = move.direction === 'in';
  const accent = isIn ? Brand.win : Brand.loss;
  const body = (
    <View style={[styles.card, { backgroundColor: c.card, borderColor: c.border, borderLeftColor: accent }]}>
      <View style={styles.cardHead}>
        <View style={[styles.dirBadge, { backgroundColor: accent }]}>
          <Ionicons name={isIn ? 'arrow-down' : 'arrow-up'} size={12} color="#fff" />
          <Text style={styles.dirText}>{isIn ? 'IN' : 'OUT'}</Text>
        </View>
        {move.category && CATEGORY_LABEL[move.category] && (
          <View style={[styles.catTag, { borderColor: accent }]}>
            <Text style={[styles.catText, { color: accent }]}>{CATEGORY_LABEL[move.category]}</Text>
          </View>
        )}
        {showTag && move.sport_id && SPORT_TAG[move.sport_id] && (
          <View style={styles.tag}>
            <Text style={styles.tagText}>{SPORT_TAG[move.sport_id]}</Text>
          </View>
        )}
        <Text style={[styles.status, { color: c.textSecondary }]}>
          {move.status ?? ''} · {formatDate(move.move_date)}
        </Text>
      </View>

      <Text style={[styles.player, { color: c.text }]}>
        {move.player_name}
        {move.position ? <Text style={{ color: c.textSecondary }}> · {move.position}</Text> : null}
        {move.class_year ? <Text style={{ color: c.textSecondary }}> · {move.class_year}</Text> : null}
      </Text>
      {move.notes ? <Text style={[styles.notes, { color: c.textSecondary }]}>{move.notes}</Text> : null}
      {move.source_name ? (
        <Text style={[styles.source, { color: c.textSecondary }]}>
          {move.source_url ? 'Source: ' : ''}
          {move.source_name}
          {move.source_url ? ' ↗' : ''}
        </Text>
      ) : null}
    </View>
  );

  if (move.source_url) {
    return (
      <Pressable onPress={() => WebBrowser.openBrowserAsync(move.source_url!)}>{body}</Pressable>
    );
  }
  return body;
}

const styles = StyleSheet.create({
  center: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  content: { padding: 16, paddingBottom: 40 },
  filterRow: { flexDirection: 'row', gap: 8, paddingHorizontal: 16, paddingTop: 12, paddingBottom: 4, flexWrap: 'wrap' },
  chip: { paddingHorizontal: 14, paddingVertical: 7, borderRadius: 20, borderWidth: 1 },
  chipText: { fontSize: 13, fontWeight: '700' },
  summary: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-around',
    borderWidth: 1,
    borderRadius: 14,
    paddingVertical: 14,
    marginBottom: 14,
  },
  stat: { alignItems: 'center', flex: 1 },
  statValue: { fontSize: 24, fontWeight: '900' },
  statLabel: { fontSize: 11, fontWeight: '700', letterSpacing: 1, marginTop: 2 },
  divider: { width: 1, height: 30 },
  card: {
    borderWidth: 1,
    borderLeftWidth: 4,
    borderRadius: 12,
    padding: 14,
    marginBottom: 10,
  },
  cardHead: { flexDirection: 'row', alignItems: 'center', gap: 8, marginBottom: 6 },
  dirBadge: { flexDirection: 'row', alignItems: 'center', gap: 3, borderRadius: 6, paddingHorizontal: 7, paddingVertical: 2 },
  dirText: { color: '#fff', fontSize: 11, fontWeight: '900' },
  tag: { backgroundColor: Brand.blue, borderRadius: 5, paddingHorizontal: 6, paddingVertical: 1 },
  tagText: { color: Brand.gold, fontSize: 10, fontWeight: '900' },
  catTag: { borderWidth: 1, borderRadius: 5, paddingHorizontal: 6, paddingVertical: 1 },
  catText: { fontSize: 10, fontWeight: '800' },
  status: { fontSize: 12, fontWeight: '600', textTransform: 'capitalize', flex: 1, textAlign: 'right' },
  player: { fontSize: 17, fontWeight: '800' },
  notes: { fontSize: 13, marginTop: 4, lineHeight: 18 },
  source: { fontSize: 12, marginTop: 6, fontWeight: '600' },
  empty: { textAlign: 'center', marginTop: 30, fontSize: 14 },
  footer: { textAlign: 'center', marginTop: 16, fontSize: 12 },
});
