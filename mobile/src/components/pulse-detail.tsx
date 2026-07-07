import { Ionicons } from '@expo/vector-icons';
import { useEffect, useMemo, useState } from 'react';
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
import { Game, RosterMove } from '@/lib/types';
import { ChartMarker, ChartPoint, PulseChart } from './pulse-chart';

const SPORT_NAME: Record<string, string> = {
  football: 'Football',
  mbb: "Men's Basketball",
  baseball: 'Baseball',
};
const TREND_EMOJI: Record<string, string> = { up: '📈', down: '📉', neutral: '➡️' };
const JUMP_THRESHOLD = 5; // points of change that count as a "notable" move worth explaining

type Driver = { label: string; delta?: number; kind: string };
type PulseEvent = { kind: 'win' | 'loss' | 'in' | 'out'; label: string };

function fullDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
}

function wvuView(g: Game) {
  const home = !!g.is_wvu_home;
  const wpts = home ? g.home_points : g.away_points;
  const opts = home ? g.away_points : g.home_points;
  return {
    opp: home ? g.away_team : g.home_team,
    loc: home ? 'vs' : '@',
    win: (wpts ?? 0) > (opts ?? 0),
    scoreText: `${wpts}–${opts}`,
  };
}

export function PulseDetail({ sport, onClose }: { sport: string | null; onClose: () => void }) {
  const dark = useColorScheme() === 'dark';
  const c = surfaces(dark);

  const [snaps, setSnaps] = useState<{ date: string; score: number }[]>([]);
  const [games, setGames] = useState<Game[]>([]);
  const [current, setCurrent] = useState<{
    score: number;
    trend: string;
    explanation: string | null;
    drivers: Driver[] | null;
  } | null>(null);
  const [moves, setMoves] = useState<RosterMove[]>([]);
  const [loading, setLoading] = useState(true);
  const [activeIdx, setActiveIdx] = useState<number>(-1); // -1 => latest

  useEffect(() => {
    if (!sport) return;
    setLoading(true);
    setActiveIdx(-1);
    (async () => {
      const [snapRes, moveRes, gameRes] = await Promise.all([
        supabase.from('pulse_snapshots').select('*').eq('sport_id', sport).order('date'),
        supabase.from('roster_moves').select('*').eq('sport_id', sport).order('move_date', { ascending: false }),
        supabase.from('games').select('*').eq('sport_id', sport).eq('status', 'final'),
      ]);
      const s = (snapRes.data ?? []) as any[];
      setSnaps(s.map((x) => ({ date: x.date, score: x.score })));
      const latest = s[s.length - 1];
      setCurrent(latest ? { score: latest.score, trend: latest.trend, explanation: latest.explanation, drivers: latest.drivers } : null);
      setMoves((moveRes.data ?? []) as RosterMove[]);
      setGames((gameRes.data ?? []) as Game[]);
      setLoading(false);
    })();
  }, [sport]);

  const points: ChartPoint[] = snaps;

  // Explain the score change between two snapshot dates using REAL events in that
  // Every event (game + roster move) in the window (prevDate, curDate]. Compare by
  // DATE, not timestamp: snapshot dates are midnight, but a same-day game/move must
  // land in this window. Snapshot i reflects everything dated (prevDate, curDate].
  const eventsForWindow = useMemo(() => {
    return (prevDate: string, curDate: string): PulseEvent[] => {
      const pa = prevDate.slice(0, 10);
      const pb = curDate.slice(0, 10);
      const inWin = (iso: string | null) => {
        if (!iso) return false;
        const d = iso.slice(0, 10);
        return d > pa && d <= pb;
      };
      const evs: PulseEvent[] = [];
      for (const g of games) {
        if (!inWin(g.start_date)) continue;
        const v = wvuView(g);
        evs.push({ kind: v.win ? 'win' : 'loss', label: `${v.loc} ${v.opp} ${v.scoreText}` });
      }
      for (const m of moves) {
        if (!inWin(m.move_date)) continue;
        const isIn = m.direction === 'in';
        const school = m.other_school ? ` ${isIn ? 'from' : 'to'} ${m.other_school}` : '';
        evs.push({ kind: isIn ? 'in' : 'out', label: `${m.player_name}${school}` });
      }
      return evs;
    };
  }, [games, moves]);

  // Mark notable scoring jumps (green/red) and any roster-move point (gold).
  const markers = useMemo(() => {
    const mk: ChartMarker[] = [];
    for (let i = 1; i < points.length; i++) {
      const delta = points[i].score - points[i - 1].score;
      if (Math.abs(delta) >= JUMP_THRESHOLD) {
        mk.push({ index: i, kind: delta >= 0 ? 'up' : 'down' });
      } else if (eventsForWindow(points[i - 1].date, points[i].date).some((e) => e.kind === 'in' || e.kind === 'out')) {
        mk.push({ index: i, kind: 'move' });
      }
    }
    return mk;
  }, [points, eventsForWindow]);

  const n = points.length;
  const idx = activeIdx < 0 || activeIdx > n - 1 ? n - 1 : activeIdx;
  const activeEvents = idx > 0 ? eventsForWindow(points[idx - 1].date, points[idx].date) : [];

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

            {n >= 2 ? (
              <View style={[styles.chartCard, { backgroundColor: c.card, borderColor: c.border }]}>
                <PulseChart
                  data={points}
                  markers={markers}
                  textColor={c.textSecondary}
                  gridColor={c.border}
                  onActiveChange={setActiveIdx}
                />
                <Text style={[styles.hint, { color: c.textSecondary }]}>
                  Drag across the chart — <Text style={{ color: Brand.gold }}>●</Text> marks roster moves,{' '}
                  <Text style={{ color: Brand.win }}>●</Text>/<Text style={{ color: Brand.loss }}>●</Text> scoring swings
                </Text>

                {/* Events panel — lists the games & moves at the scrubbed point */}
                <View style={[styles.reasonCard, { borderColor: c.border }]}>
                  <Text style={[styles.reasonDate, { color: c.textSecondary }]}>
                    {fullDate(points[idx].date)} · Pulse {points[idx].score}
                  </Text>
                  {activeEvents.length > 0 ? (
                    <View style={{ marginTop: 8 }}>
                      {activeEvents.slice(0, 6).map((e, i) => {
                        const col = e.kind === 'win' || e.kind === 'in' ? Brand.win : Brand.loss;
                        const tag = e.kind === 'win' ? 'W' : e.kind === 'loss' ? 'L' : e.kind === 'in' ? 'IN' : 'OUT';
                        return (
                          <View key={i} style={styles.eventRow}>
                            <View style={[styles.eventTag, { backgroundColor: col }]}>
                              <Text style={styles.eventTagText}>{tag}</Text>
                            </View>
                            <Text style={[styles.eventLabel, { color: c.text }]} numberOfLines={1}>
                              {e.label}
                            </Text>
                          </View>
                        );
                      })}
                      {activeEvents.length > 6 && (
                        <Text style={[styles.reasonDetail, { color: c.textSecondary }]}>
                          +{activeEvents.length - 6} more
                        </Text>
                      )}
                    </View>
                  ) : (
                    <Text style={[styles.reasonDetail, { color: c.textSecondary }]}>
                      {idx === n - 1 && current?.explanation ? current.explanation : 'No notable change on this date.'}
                    </Text>
                  )}
                </View>
              </View>
            ) : (
              <View style={[styles.chartCard, { backgroundColor: c.card, borderColor: c.border }]}>
                <Text style={{ color: c.textSecondary, textAlign: 'center' }}>Not enough history yet.</Text>
              </View>
            )}

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
  hint: { fontSize: 11, marginTop: 6, fontStyle: 'italic' },
  reasonCard: { borderTopWidth: 1, marginTop: 10, paddingTop: 12, width: '100%' },
  reasonDate: { fontSize: 12, fontWeight: '700', textTransform: 'uppercase', letterSpacing: 0.5 },
  reasonBody: { flexDirection: 'row', alignItems: 'center', gap: 10, marginTop: 8 },
  reasonBadge: { width: 26, height: 26, borderRadius: 13, alignItems: 'center', justifyContent: 'center' },
  reasonTitle: { fontSize: 16, fontWeight: '800' },
  reasonDetail: { fontSize: 13, marginTop: 8, lineHeight: 18 },
  eventRow: { flexDirection: 'row', alignItems: 'center', gap: 8, paddingVertical: 4 },
  eventTag: { minWidth: 30, borderRadius: 5, paddingHorizontal: 5, paddingVertical: 1, alignItems: 'center' },
  eventTagText: { color: '#fff', fontSize: 10, fontWeight: '900' },
  eventLabel: { flex: 1, fontSize: 14, fontWeight: '600' },
  moveRow: { flexDirection: 'row', alignItems: 'center', gap: 8, borderBottomWidth: 1, paddingVertical: 10 },
  movePlayer: { flex: 1, fontSize: 15, fontWeight: '700' },
});
