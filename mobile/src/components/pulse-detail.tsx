import { Ionicons } from '@expo/vector-icons';
import { useEffect, useState } from 'react';
import {
  ActivityIndicator,
  Modal,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
  useColorScheme,
} from 'react-native';

import { Brand, surfaces } from '@/constants/brand';
import { supabase } from '@/lib/supabase';
import { RosterMove } from '@/lib/types';
import { ChartPoint, PulseChart } from './pulse-chart';

const SPORT_NAME: Record<string, string> = {
  football: 'Football',
  mbb: "Men's Basketball",
  baseball: 'Baseball',
};
const TREND_EMOJI: Record<string, string> = { up: '📈', down: '📉', neutral: '➡️' };

type Driver = { label: string; delta?: number; kind: string };

export function PulseDetail({ sport, onClose }: { sport: string | null; onClose: () => void }) {
  const dark = useColorScheme() === 'dark';
  const c = surfaces(dark);

  const [points, setPoints] = useState<ChartPoint[]>([]);
  const [current, setCurrent] = useState<{ score: number; trend: string; explanation: string | null; drivers: Driver[] | null } | null>(null);
  const [moves, setMoves] = useState<RosterMove[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!sport) return;
    setLoading(true);
    (async () => {
      const [snapRes, moveRes] = await Promise.all([
        supabase.from('pulse_snapshots').select('*').eq('sport_id', sport).order('date'),
        supabase.from('roster_moves').select('*').eq('sport_id', sport).order('move_date', { ascending: false }),
      ]);
      const snaps = snapRes.data ?? [];
      setPoints(snaps.map((s: any) => ({ date: s.date, score: s.score })));
      const latest = snaps[snaps.length - 1] as any;
      setCurrent(latest ? { score: latest.score, trend: latest.trend, explanation: latest.explanation, drivers: latest.drivers } : null);
      setMoves((moveRes.data ?? []) as RosterMove[]);
      setLoading(false);
    })();
  }, [sport]);

  return (
    <Modal visible={!!sport} animationType="slide" transparent={false} onRequestClose={onClose}>
      <View style={{ flex: 1, backgroundColor: c.bg }}>
        <View style={[styles.header, { backgroundColor: Brand.blue }]}>
          <Text style={styles.headerTitle}>{sport ? SPORT_NAME[sport] : ''} Pulse</Text>
          <Pressable onPress={onClose} hitSlop={12}>
            <Ionicons name="close" size={26} color="#fff" />
          </Pressable>
        </View>

        {loading ? (
          <View style={styles.center}>
            <ActivityIndicator size="large" color={Brand.gold} />
          </View>
        ) : (
          <ScrollView contentContainerStyle={styles.content}>
            <View style={styles.scoreRow}>
              <Text style={[styles.bigScore, { color: c.text }]}>{current?.score ?? '—'}</Text>
              <Text style={styles.bigTrend}>{current ? TREND_EMOJI[current.trend] : ''}</Text>
              <Text style={[styles.outOf, { color: c.textSecondary }]}>/ 100</Text>
            </View>

            {current?.explanation && (
              <Text style={[styles.explanation, { color: c.textSecondary }]}>{current.explanation}</Text>
            )}

            {current?.drivers && current.drivers.length > 0 && (
              <View style={styles.driverRow}>
                {current.drivers.map((d, i) => {
                  const hasDelta = d.delta !== undefined && d.delta !== null;
                  const col = hasDelta ? ((d.delta as number) >= 0 ? Brand.win : Brand.loss) : Brand.gold;
                  return (
                    <View key={i} style={[styles.chip, { borderColor: col }]}>
                      <Text style={[styles.chipText, { color: col }]}>{d.label}</Text>
                    </View>
                  );
                })}
              </View>
            )}

            <View style={styles.sectionRow}>
              <View style={styles.goldBar} />
              <Text style={[styles.sectionTitle, { color: c.text }]}>Pulse over time</Text>
            </View>
            <View style={[styles.chartCard, { backgroundColor: c.card, borderColor: c.border }]}>
              {points.length >= 2 ? (
                <PulseChart data={points} textColor={c.textSecondary} gridColor={c.border} />
              ) : (
                <Text style={{ color: c.textSecondary, textAlign: 'center' }}>Not enough history yet.</Text>
              )}
            </View>

            {moves.length > 0 && (
              <>
                <View style={styles.sectionRow}>
                  <View style={styles.goldBar} />
                  <Text style={[styles.sectionTitle, { color: c.text }]}>Recent movement</Text>
                </View>
                {moves.slice(0, 8).map((m) => {
                  const isIn = m.direction === 'in';
                  return (
                    <View key={m.id} style={[styles.moveRow, { borderColor: c.border }]}>
                      <Text style={{ color: isIn ? Brand.win : Brand.loss, fontWeight: '900', width: 34 }}>
                        {isIn ? 'IN' : 'OUT'}
                      </Text>
                      <Text style={[styles.movePlayer, { color: c.text }]}>
                        {m.player_name}
                        {m.position ? <Text style={{ color: c.textSecondary }}> · {m.position}</Text> : null}
                      </Text>
                      <Text style={{ color: c.textSecondary, fontSize: 12 }}>{m.category}</Text>
                    </View>
                  );
                })}
              </>
            )}
          </ScrollView>
        )}
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingTop: 54,
    paddingBottom: 16,
    paddingHorizontal: 18,
  },
  headerTitle: { color: '#fff', fontSize: 20, fontWeight: '800' },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  content: { padding: 18, paddingBottom: 40 },
  scoreRow: { flexDirection: 'row', alignItems: 'flex-end', gap: 8 },
  bigScore: { fontSize: 64, fontWeight: '900', lineHeight: 68 },
  bigTrend: { fontSize: 30, marginBottom: 8 },
  outOf: { fontSize: 16, fontWeight: '700', marginBottom: 12 },
  explanation: { fontSize: 15, lineHeight: 22, marginTop: 8 },
  driverRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 6, marginTop: 12 },
  chip: { borderWidth: 1, borderRadius: 8, paddingHorizontal: 9, paddingVertical: 4 },
  chipText: { fontSize: 12, fontWeight: '800' },
  sectionRow: { flexDirection: 'row', alignItems: 'center', marginTop: 22, marginBottom: 10 },
  goldBar: { width: 4, height: 20, borderRadius: 2, backgroundColor: Brand.gold, marginRight: 8 },
  sectionTitle: { fontSize: 18, fontWeight: '800' },
  chartCard: { borderWidth: 1, borderRadius: 14, padding: 10, alignItems: 'center' },
  moveRow: { flexDirection: 'row', alignItems: 'center', gap: 8, borderBottomWidth: 1, paddingVertical: 10 },
  movePlayer: { flex: 1, fontSize: 15, fontWeight: '700' },
});
