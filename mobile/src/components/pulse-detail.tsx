import { Ionicons } from '@expo/vector-icons';
import { useEffect, useMemo, useState } from 'react';
import { ActivityIndicator, Modal, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { SectionLabel, Segmented } from '@/components/ui';
import { Brand, Font, surfaces } from '@/constants/brand';
import { supabase } from '@/lib/supabase';
import { Game, RosterMove } from '@/lib/types';
import { ChartPoint, PulseChart } from './pulse-chart';

const c = surfaces(true);

const SPORT_NAME: Record<string, string> = {
  football: 'Football',
  mbb: "Men's Basketball",
  baseball: 'Baseball',
};
const SPORT_OPTS = [
  { key: 'football', label: 'Football' },
  { key: 'mbb', label: 'Basketball' },
  { key: 'baseball', label: 'Baseball' },
];

const RANGES: { label: string; stepDays: number; count: number; word: string }[] = [
  { label: '1M', stepDays: 2, count: 15, word: 'past month' },
  { label: '3M', stepDays: 7, count: 13, word: 'past 3 months' },
  { label: '6M', stepDays: 14, count: 13, word: 'past 6 months' },
  { label: '1Y', stepDays: 30, count: 12, word: 'past year' },
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
    win: (wpts ?? 0) > (opts ?? 0),
    scoreText: `${wpts}–${opts}`,
  };
}

export function PulseDetail({ sport, onClose }: { sport: string | null; onClose: () => void }) {
  const insets = useSafeAreaInsets();
  const [curSport, setCurSport] = useState<string | null>(sport);
  const [snaps, setSnaps] = useState<{ date: string; score: number }[]>([]);
  const [games, setGames] = useState<Game[]>([]);
  const [current, setCurrent] = useState<{ score: number; trend: string; drivers: Driver[] | null } | null>(null);
  const [moves, setMoves] = useState<RosterMove[]>([]);
  const [notes, setNotes] = useState<{ date: string; note: string }[]>([]);
  const [loading, setLoading] = useState(true);
  const [activeIdx, setActiveIdx] = useState<number>(-1);
  const [rangeIdx, setRangeIdx] = useState<number>(0);

  useEffect(() => {
    if (sport) setCurSport(sport);
  }, [sport]);

  useEffect(() => {
    if (!curSport) return;
    setLoading(true);
    setActiveIdx(-1);
    (async () => {
      const [snapRes, moveRes, gameRes, noteRes] = await Promise.all([
        supabase.from('pulse_snapshots').select('*').eq('sport_id', curSport).order('date'),
        supabase.from('roster_moves').select('*').eq('sport_id', curSport).order('move_date', { ascending: false }),
        supabase.from('games').select('*').eq('sport_id', curSport).eq('status', 'final'),
        supabase.from('daily_sport_notes').select('date,note').eq('sport_id', curSport).order('date'),
      ]);
      const s = (snapRes.data ?? []) as { date: string; score: number; trend: string; drivers: Driver[] | null }[];
      setSnaps(s.map((x) => ({ date: x.date, score: x.score })));
      const latest = s[s.length - 1];
      setCurrent(latest ? { score: latest.score, trend: latest.trend, drivers: latest.drivers } : null);
      setMoves((moveRes.data ?? []) as RosterMove[]);
      setGames((gameRes.data ?? []) as Game[]);
      setNotes((noteRes.data ?? []) as { date: string; note: string }[]);
      setLoading(false);
    })();
  }, [curSport]);

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
      if (score == null) continue;
      out.push({ date: new Date(st).toISOString().slice(0, 10), score });
    }
    return out;
  }, [snaps, rangeIdx]);

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
  const rangeDelta = n >= 2 ? points[n - 1].score - points[0].score : 0;
  const deltaColor = rangeDelta > 0 ? Brand.green : rangeDelta < 0 ? Brand.red : c.textSecondary;

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
        <View style={[styles.header, { paddingTop: insets.top + 8 }]}>
          <Pressable onPress={onClose} hitSlop={12} style={styles.circleBtn}>
            <Ionicons name="chevron-back" size={20} color={c.textSecondary} />
          </Pressable>
          <Text style={styles.headerTitle}>{curSport ? SPORT_NAME[curSport] : ''} Pulse</Text>
          <View style={styles.circleBtn} />
        </View>

        {loading ? (
          <View style={styles.center}>
            <ActivityIndicator size="large" color={Brand.gold} />
          </View>
        ) : (
          <ScrollView contentContainerStyle={styles.content}>
            <Segmented options={SPORT_OPTS} value={curSport ?? 'football'} onChange={setCurSport} />

            <View style={{ marginTop: 22 }}>
              <SectionLabel tone="muted">Pulse Score</SectionLabel>
              <Text style={styles.bigScore}>{current?.score ?? '—'}</Text>
              {n >= 2 && (
                <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8, marginTop: 6 }}>
                  <View style={[styles.deltaTag, { backgroundColor: deltaColor + '22' }]}>
                    <Text style={{ fontFamily: Font.bodyBold, fontSize: 13, color: deltaColor }}>
                      {rangeDelta > 0 ? '▲ +' : rangeDelta < 0 ? '▼ ' : '▶ '}
                      {rangeDelta}
                    </Text>
                  </View>
                  <Text style={{ color: c.textMuted, fontSize: 12, fontFamily: Font.body }}>
                    {RANGES[rangeIdx].word}
                  </Text>
                </View>
              )}
            </View>

            {n >= 2 ? (
              <>
                <View style={{ marginTop: 16 }}>
                  <PulseChart data={points} textColor={c.textSecondary} gridColor={c.border} onActiveChange={setActiveIdx} />
                </View>

                <View style={{ marginTop: 14 }}>
                  <Segmented
                    options={RANGES.map((r, i) => ({ key: String(i), label: r.label }))}
                    value={String(rangeIdx)}
                    onChange={(k) => setRangeIdx(Number(k))}
                    variant="solid"
                  />
                </View>

                {/* Note / events panel for the scrubbed point */}
                <View style={styles.panel}>
                  <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' }}>
                    <SectionLabel>{`${fullDate(points[idx].date)} · Pulse ${points[idx].score}`}</SectionLabel>
                    {activeEvents.length > 0 && (
                      <Text style={{ fontSize: 11, color: c.textMuted, fontFamily: Font.body }}>
                        {activeEvents.length} event{activeEvents.length > 1 ? 's' : ''}
                      </Text>
                    )}
                  </View>
                  {noteForWindow && <Text style={styles.noteLine}>{noteForWindow}</Text>}
                  {activeEvents.length > 0 && (
                    <View style={{ marginTop: 10, gap: 4 }}>
                      {activeEvents.slice(0, 6).map((e, i) => {
                        const good = e.kind === 'win' || e.kind === 'in';
                        return (
                          <View key={i} style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
                            <View style={[styles.evTag, { backgroundColor: good ? Brand.greenTint : Brand.redTint }]}>
                              <Text style={{ fontSize: 10, fontFamily: Font.bodyBold, color: good ? Brand.green : Brand.red }}>
                                {e.kind === 'in' ? '↓ IN' : e.kind === 'out' ? '↑ OUT' : good ? 'W' : 'L'}
                              </Text>
                            </View>
                            <Text style={styles.evLabel} numberOfLines={1}>{e.label}</Text>
                          </View>
                        );
                      })}
                    </View>
                  )}
                  {!noteForWindow && activeEvents.length === 0 && (
                    <Text style={styles.quiet}>No notable change on this date.</Text>
                  )}
                </View>

                {/* Drivers */}
                {current?.drivers && current.drivers.length > 0 && (
                  <>
                    <SectionLabel tone="muted" style={{ marginTop: 22, marginBottom: 8 } as never}>
                      What's driving the score
                    </SectionLabel>
                    <View style={{ gap: 8 }}>
                      {current.drivers.map((d, i) => {
                        const has = d.delta !== undefined && d.delta !== null;
                        const pos = (d.delta ?? 0) >= 0;
                        const col = has ? (pos ? Brand.green : Brand.red) : c.textSecondary;
                        return (
                          <View key={i} style={styles.driverCard}>
                            <Text style={styles.driverLabel}>{d.label}</Text>
                            {has && (
                              <Text style={{ fontFamily: Font.bodyBold, fontSize: 13, color: col }}>
                                {pos ? '+' : ''}
                                {d.delta}
                              </Text>
                            )}
                          </View>
                        );
                      })}
                    </View>
                  </>
                )}
              </>
            ) : (
              <View style={[styles.panel, { alignItems: 'center' }]}>
                <Text style={{ color: c.textSecondary, textAlign: 'center', fontFamily: Font.body }}>
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
    paddingBottom: 12,
    paddingHorizontal: 20,
  },
  headerTitle: { color: c.text, fontSize: 15, fontFamily: Font.display, letterSpacing: -0.2 },
  circleBtn: {
    width: 32,
    height: 32,
    borderRadius: 16,
    backgroundColor: c.surface3,
    borderWidth: 1,
    borderColor: c.border,
    alignItems: 'center',
    justifyContent: 'center',
  },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  content: { paddingHorizontal: 20, paddingBottom: 48 },
  bigScore: { fontFamily: Font.black, fontSize: 84, lineHeight: 84, color: c.text, letterSpacing: -3 },
  deltaTag: { borderRadius: 999, paddingHorizontal: 10, paddingVertical: 4 },
  panel: {
    backgroundColor: c.card,
    borderWidth: 1,
    borderColor: c.border,
    borderRadius: 18,
    padding: 16,
    marginTop: 16,
  },
  noteLine: { fontFamily: Font.displaySemi, fontSize: 15, lineHeight: 21, color: c.text, marginTop: 8 },
  evTag: { borderRadius: 6, paddingHorizontal: 7, paddingVertical: 3, minWidth: 30, alignItems: 'center' },
  evLabel: { flex: 1, fontSize: 13, color: c.textSecondary, fontFamily: Font.bodyMed },
  quiet: { fontSize: 13, marginTop: 8, color: c.textMuted, fontFamily: Font.body },
  driverCard: {
    backgroundColor: c.card,
    borderWidth: 1,
    borderColor: c.border,
    borderRadius: 14,
    paddingHorizontal: 16,
    paddingVertical: 12,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  driverLabel: { fontSize: 13, color: c.text, fontFamily: Font.bodySemi, flex: 1 },
});
