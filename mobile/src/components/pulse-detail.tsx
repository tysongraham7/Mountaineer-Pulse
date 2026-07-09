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
import { ChartPoint, PulseChart } from './pulse-chart';

const SPORT_NAME: Record<string, string> = {
  football: 'Football',
  mbb: "Men's Basketball",
  baseball: 'Baseball',
};
const TREND_EMOJI: Record<string, string> = { up: '📈', down: '📉', neutral: '➡️' };

// Chart time ranges. Each resamples to a fixed cadence so the line has an even,
// hover-friendly number of points regardless of how dense the raw data is.
const RANGES: { label: string; stepDays: number; count: number }[] = [
  { label: '1M', stepDays: 2, count: 15 },  // last ~month, every other day
  { label: '3M', stepDays: 7, count: 13 },  // ~3 months, weekly
  { label: '6M', stepDays: 14, count: 13 }, // ~6 months, every other week
  { label: '1Y', stepDays: 30, count: 12 }, // ~1 year, monthly
];

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
  const [notes, setNotes] = useState<{ date: string; note: string }[]>([]);
  const [loading, setLoading] = useState(true);
  const [activeIdx, setActiveIdx] = useState<number>(-1); // -1 => latest
  const [rangeIdx, setRangeIdx] = useState<number>(0); // default: 1M

  useEffect(() => {
    if (!sport) return;
    setLoading(true);
    setActiveIdx(-1);
    (async () => {
      const [snapRes, moveRes, gameRes, noteRes] = await Promise.all([
        supabase.from('pulse_snapshots').select('*').eq('sport_id', sport).order('date'),
        supabase.from('roster_moves').select('*').eq('sport_id', sport).order('move_date', { ascending: false }),
        supabase.from('games').select('*').eq('sport_id', sport).eq('status', 'final'),
        supabase.from('daily_sport_notes').select('date,note').eq('sport_id', sport).order('date'),
      ]);
      const s = (snapRes.data ?? []) as any[];
      setSnaps(s.map((x) => ({ date: x.date, score: x.score })));
      const latest = s[s.length - 1];
      setCurrent(latest ? { score: latest.score, trend: latest.trend, explanation: latest.explanation, drivers: latest.drivers } : null);
      setMoves((moveRes.data ?? []) as RosterMove[]);
      setGames((gameRes.data ?? []) as Game[]);
      setNotes((noteRes.data ?? []) as { date: string; note: string }[]);
      setLoading(false);
    })();
  }, [sport]);

  // Resample the score onto an even cadence (carry-forward: each sampled point is
  // the score as of that date). Gives a consistent point count and fills gaps.
  const points: ChartPoint[] = useMemo(() => {
    if (snaps.length === 0) return [];
    const { stepDays, count } = RANGES[rangeIdx];
    const parsed = snaps.map((s) => ({ t: new Date(s.date).getTime(), score: s.score }));
    const anchor = new Date(snaps[snaps.length - 1].date).getTime();
    const DAY = 86400000;
    const out: ChartPoint[] = [];
    for (let i = count - 1; i >= 0; i--) {
      const st = anchor - i * stepDays * DAY;
      let score: number | null = null;
      for (let j = parsed.length - 1; j >= 0; j--) {
        if (parsed[j].t <= st) {
          score = parsed[j].score;
          break;
        }
      }
      if (score == null) continue; // sample predates all data
      out.push({ date: new Date(st).toISOString().slice(0, 10), score });
    }
    return out;
  }, [snaps, rangeIdx]);

  // Every event (game + roster move) in the window (prevDate, curDate]. Compare by
  // DATE, not timestamp: snapshot dates are midnight, but a same-day game/move must
  // land in this window. A point reflects everything dated (prevDate, curDate].
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
        evs.push({ kind: v.win ? 'win' : 'loss', label: `${v.win ? 'Beat' : 'Lost to'} ${v.opp} ${v.scoreText}` });
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

  const n = points.length;
  const idx = activeIdx < 0 || activeIdx > n - 1 ? n - 1 : activeIdx;
  const activeEvents = idx > 0 && n >= 2 ? eventsForWindow(points[idx - 1].date, points[idx].date) : [];

  // The per-sport daily headline for this point's date (most recent one in the window).
  const noteForWindow = (() => {
    if (n < 1 || notes.length === 0) return null;
    const pb = points[idx].date.slice(0, 10);
    const pa = idx > 0 ? points[idx - 1].date.slice(0, 10) : '';
    const win = notes.filter((nt) => {
      const d = nt.date.slice(0, 10);
      return idx > 0 ? d > pa && d <= pb : d === pb;
    });
    return win.length ? win[win.length - 1].note : null;
  })();

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

            {/* time range selector — default last month, up to a year */}
            <View style={styles.rangeRow}>
              {RANGES.map((r, i) => {
                const activeR = rangeIdx === i;
                return (
                  <Pressable
                    key={r.label}
                    onPress={() => setRangeIdx(i)}
                    style={[styles.rangeChip, { backgroundColor: activeR ? Brand.gold : c.card, borderColor: activeR ? Brand.gold : c.border }]}>
                    <Text style={[styles.rangeText, { color: activeR ? Brand.blueDeep : c.textSecondary }]}>{r.label}</Text>
                  </Pressable>
                );
              })}
            </View>

            {n >= 2 ? (
              <View style={[styles.chartCard, { backgroundColor: c.card, borderColor: c.border }]}>
                <PulseChart data={points} textColor={c.textSecondary} gridColor={c.border} onActiveChange={setActiveIdx} />
                <Text style={[styles.hint, { color: c.textSecondary }]}>Drag across the line to explore</Text>

                {/* Panel: the briefing (at the latest point) or what happened at the scrubbed point */}
                <View style={[styles.reasonCard, { borderColor: c.border }]}>
                  <Text style={[styles.reasonDate, { color: c.textSecondary }]}>
                    {fullDate(points[idx].date)} · Pulse {points[idx].score}
                  </Text>
                  {noteForWindow && (
                    <Text style={[styles.noteLine, { color: c.text }]}>{noteForWindow}</Text>
                  )}
                  {activeEvents.length > 0 && (
                    <View style={{ marginTop: 8 }}>
                      {activeEvents.slice(0, 6).map((e, i) => (
                        <Text
                          key={i}
                          style={[styles.eventLine, { color: e.kind === 'win' || e.kind === 'in' ? Brand.win : Brand.loss }]}
                          numberOfLines={1}>
                          {e.label}
                        </Text>
                      ))}
                      {activeEvents.length > 6 && (
                        <Text style={[styles.reasonDetail, { color: c.textSecondary }]}>+{activeEvents.length - 6} more</Text>
                      )}
                    </View>
                  )}
                  {!noteForWindow && activeEvents.length === 0 && (
                    <Text style={[styles.reasonDetail, { color: c.textSecondary }]}>No notable change on this date.</Text>
                  )}
                </View>
              </View>
            ) : (
              <View style={[styles.chartCard, { backgroundColor: c.card, borderColor: c.border }]}>
                <Text style={{ color: c.textSecondary, textAlign: 'center' }}>
                  Not enough history in this range — try a longer one.
                </Text>
              </View>
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
  rangeRow: { flexDirection: 'row', gap: 8, marginBottom: 12 },
  rangeChip: { paddingHorizontal: 16, paddingVertical: 6, borderRadius: 16, borderWidth: 1 },
  rangeText: { fontSize: 13, fontWeight: '800' },
  eventLine: { fontSize: 15, fontWeight: '700', paddingVertical: 3 },
  noteLine: { fontSize: 15, fontWeight: '700', lineHeight: 21, marginTop: 8 },
  briefing: { fontSize: 14, lineHeight: 20, marginTop: 10 },
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
