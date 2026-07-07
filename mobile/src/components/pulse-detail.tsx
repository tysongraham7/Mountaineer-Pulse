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
type Reason = { dir: 'up' | 'down'; title: string; detail: string };

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
  // window: game results first, then roster moves, else a generic standing update.
  const reasonForWindow = useMemo(() => {
    return (prevDate: string, curDate: string, dir: 'up' | 'down'): Reason => {
      // Compare by DATE, not timestamp: snapshot dates are midnight, but games
      // have a kickoff time — a same-day game must land in this window, not the
      // next one. Snapshot i reflects games/moves dated (prevDate, curDate].
      const pa = prevDate.slice(0, 10);
      const pb = curDate.slice(0, 10);
      const inWin = (iso: string | null) => {
        if (!iso) return false;
        const d = iso.slice(0, 10);
        return d > pa && d <= pb;
      };

      const gw = games.filter((g) => inWin(g.start_date));
      if (gw.length === 1) {
        const v = wvuView(gw[0]);
        return { dir, title: `${v.win ? 'Win' : 'Loss'} ${v.loc} ${v.opp}`, detail: v.scoreText };
      }
      if (gw.length > 1) {
        const wins = gw.filter((g) => wvuView(g).win).length;
        return { dir, title: `Went ${wins}–${gw.length - wins}`, detail: `${gw.length} games this stretch` };
      }

      const mw = moves.filter((m) => inWin(m.move_date));
      if (mw.length > 0) {
        const ins = mw.filter((m) => m.direction === 'in').length;
        const outs = mw.length - ins;
        const notable = mw.find((m) => m.direction === (dir === 'up' ? 'in' : 'out'));
        const who = notable
          ? `${notable.player_name}${notable.other_school ? ` (${dir === 'up' ? 'from' : 'to'} ${notable.other_school})` : ''}`
          : '';
        return { dir, title: 'Roster movement', detail: `+${ins} in / −${outs} out${who ? ` · ${who}` : ''}` };
      }

      return { dir, title: dir === 'up' ? 'Standing climb' : 'Standing slip', detail: 'ranking / record update' };
    };
  }, [games, moves]);

  // Markers at every notable jump, each carrying its grounded reason.
  const { markers, reasonByIndex } = useMemo(() => {
    const mk: ChartMarker[] = [];
    const byIdx: Record<number, Reason> = {};
    for (let i = 1; i < points.length; i++) {
      const delta = points[i].score - points[i - 1].score;
      if (Math.abs(delta) < JUMP_THRESHOLD) continue;
      const dir: 'up' | 'down' = delta >= 0 ? 'up' : 'down';
      mk.push({ index: i, dir });
      byIdx[i] = reasonForWindow(points[i - 1].date, points[i].date, dir);
    }
    return { markers: mk, reasonByIndex: byIdx };
  }, [points, reasonForWindow]);

  const n = points.length;
  const idx = activeIdx < 0 || activeIdx > n - 1 ? n - 1 : activeIdx;
  const activeReason = reasonByIndex[idx];

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
                  Drag across the chart to explore — dots mark notable moves
                </Text>

                {/* Reason panel — updates as you scrub */}
                <View style={[styles.reasonCard, { borderColor: c.border }]}>
                  <Text style={[styles.reasonDate, { color: c.textSecondary }]}>
                    {fullDate(points[idx].date)} · Pulse {points[idx].score}
                  </Text>
                  {activeReason ? (
                    <View style={styles.reasonBody}>
                      <View style={[styles.reasonBadge, { backgroundColor: activeReason.dir === 'up' ? Brand.win : Brand.loss }]}>
                        <Ionicons name={activeReason.dir === 'up' ? 'trending-up' : 'trending-down'} size={14} color="#fff" />
                      </View>
                      <View style={{ flex: 1 }}>
                        <Text style={[styles.reasonTitle, { color: c.text }]}>{activeReason.title}</Text>
                        {!!activeReason.detail && (
                          <Text style={[styles.reasonDetail, { color: c.textSecondary }]}>{activeReason.detail}</Text>
                        )}
                      </View>
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
  moveRow: { flexDirection: 'row', alignItems: 'center', gap: 8, borderBottomWidth: 1, paddingVertical: 10 },
  movePlayer: { flex: 1, fontSize: 15, fontWeight: '700' },
});
