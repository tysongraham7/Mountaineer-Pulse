import { Ionicons } from '@expo/vector-icons';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { useEffect, useMemo, useState } from 'react';
import { Modal, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { Skeleton } from '@/components/skeleton';
import { SectionLabel, Segmented } from '@/components/ui';
import { Brand, Font, surfaces } from '@/constants/brand';
import { useCountUp } from '@/lib/count-up';
import { supabase } from '@/lib/supabase';
import { Briefing, Game, RosterMove } from '@/lib/types';
import { ChartPoint, PulseChart } from './pulse-chart';
import { PulseExplainer } from './pulse-explainer';

const c = surfaces(true);

const SCRUB_DEMO_KEY = 'mp-scrub-demo-seen';

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
  { label: '1M', stepDays: 1, count: 30, word: 'past month' },
  { label: '3M', stepDays: 3, count: 30, word: 'past 3 months' },
  { label: '6M', stepDays: 7, count: 26, word: 'past 6 months' },
  { label: '1Y', stepDays: 14, count: 26, word: 'past year' },
];

type Driver = { label: string; delta?: number; kind: string };
type PulseEvent = { kind: 'win' | 'loss' | 'in' | 'out' | 'pending'; label: string };

function fullDate(iso: string): string {
  // Build from parts so a 'YYYY-MM-DD' isn't parsed as UTC midnight and rolled back a day
  // in western timezones (which made the latest point read as yesterday).
  const [y, m, d] = iso.slice(0, 10).split('-').map(Number);
  return new Date(y, m - 1, d).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
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
  const [current, setCurrent] = useState<{ score: number; trend: string; ranking: number | null; drivers: Driver[] | null } | null>(null);
  const [moves, setMoves] = useState<RosterMove[]>([]);
  const [notes, setNotes] = useState<{ date: string; note: string; pulse_delta: number | null }[]>([]);
  const [briefing, setBriefing] = useState<Briefing | null>(null);
  const [loading, setLoading] = useState(true);
  const [activeIdx, setActiveIdx] = useState<number>(-1);
  const [rangeIdx, setRangeIdx] = useState<number>(0);
  const [showAllEvents, setShowAllEvents] = useState(false);
  const [showExplainer, setShowExplainer] = useState(false);
  const [runScrubDemo, setRunScrubDemo] = useState(false);
  const [everScrubbed, setEverScrubbed] = useState(false);

  // The big score rolls up in sync with the chart's draw-in (same duration/easing
  // family) — display only, the real value is untouched. Re-runs per sport.
  const displayScore = useCountUp(loading ? null : current?.score, 900, curSport ?? '');

  // First-ever Pulse open: run the one-time scrub demo. A saved flag keeps it to once.
  useEffect(() => {
    AsyncStorage.getItem(SCRUB_DEMO_KEY).then((seen) => {
      if (!seen) setRunScrubDemo(true);
    });
  }, []);

  useEffect(() => {
    if (sport) setCurSport(sport);
  }, [sport]);

  useEffect(() => {
    if (!curSport) return;
    setLoading(true);
    setActiveIdx(-1);
    (async () => {
      const [snapRes, moveRes, gameRes, noteRes, briefRes] = await Promise.all([
        supabase.from('pulse_snapshots').select('*').eq('sport_id', curSport).order('date'),
        supabase.from('roster_moves').select('*').eq('sport_id', curSport).order('move_date', { ascending: false }),
        supabase.from('games').select('*').eq('sport_id', curSport).eq('status', 'final'),
        supabase.from('daily_sport_notes').select('date,note,pulse_delta').eq('sport_id', curSport).order('date'),
        supabase.from('daily_briefings').select('date,content,sections').order('date', { ascending: false }).limit(1),
      ]);
      const s = (snapRes.data ?? []) as { date: string; score: number; trend: string; ranking: number | null; drivers: Driver[] | null }[];
      setSnaps(s.map((x) => ({ date: x.date, score: x.score })));
      const latest = s[s.length - 1];
      setCurrent(latest ? { score: latest.score, trend: latest.trend, ranking: latest.ranking, drivers: latest.drivers } : null);
      setMoves((moveRes.data ?? []) as RosterMove[]);
      setGames((gameRes.data ?? []) as Game[]);
      setNotes((noteRes.data ?? []) as { date: string; note: string; pulse_delta: number | null }[]);
      setBriefing((briefRes.data?.[0] as Briefing) ?? null);
      setLoading(false);
    })();
  }, [curSport]);

  // Collapse the events list back to 6 whenever the scrubbed point, range, or sport changes.
  useEffect(() => {
    setShowAllEvents(false);
  }, [activeIdx, rangeIdx, curSport]);

  const points: ChartPoint[] = useMemo(() => {
    if (snaps.length === 0) return [];
    const { stepDays, count } = RANGES[rangeIdx];
    const parsed = snaps.map((s) => ({ t: new Date(s.date).getTime(), score: s.score }));
    // Anchor the last point on TODAY (local date), not the last snapshot — so today's date is
    // always on the chart. Its value carries forward from the most recent snapshot until the
    // nightly pipeline writes today's, then it shows today's real number.
    const now = new Date();
    const localToday = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
    const anchor = Math.max(new Date(localToday).getTime(), parsed[parsed.length - 1].t);
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
        // A drafted player whose stay-or-go decision is still pending — not a confirmed
        // departure. Shown in an amber "pending" box (vs. a red OUT) with its alert text.
        if (m.category === 'draft-pending') {
          evs.push({ kind: 'pending', label: `${m.player_name} — ${m.alert || 'drafted, decision pending'}` });
          continue;
        }
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

  // Today's per-sport briefing, surfaced on the chart's TODAY point. This reuses the same
  // daily briefing shown on the home tab (that card is untouched) — here we show only this
  // sport's section, and only when the scrubbed point is actually today.
  const now = new Date();
  const todayStr = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
  const todayBrief = briefing?.sections?.sections?.find((s) => s.sport === curSport) ?? null;
  const briefIsForToday = !!(
    n >= 1 && points[idx] && points[idx].date === todayStr &&
    briefing?.date?.slice(0, 10) === todayStr && todayBrief && todayBrief.items.length > 0
  );

  // "What's driving the score" — scoped to the VISIBLE range (points[0]..points[last]), so a
  // 1-month view doesn't blame a score on a January portal class. Ranking is a live status and
  // always shows; everything else (transfers/recruits/departures/news/CWS) is windowed.
  const rangeDrivers: Driver[] = useMemo(() => {
    if (n < 2) return [];
    const lo = points[0].date.slice(0, 10);
    const hi = points[n - 1].date.slice(0, 10);
    const inWin = (iso: string | null) => {
      if (!iso) return false;
      const d = iso.slice(0, 10);
      return d >= lo && d <= hi;
    };
    const wm = moves.filter((m) => inWin(m.move_date));
    const tin = wm.filter((m) => m.direction === 'in' && m.category === 'transfer').length;
    const tout = wm.filter((m) => m.direction === 'out' && m.category === 'transfer').length;
    const recruits = wm.filter((m) => m.direction === 'in' && ['recruit', 'juco', 'hs'].includes(m.category ?? '')).length;
    const departures = wm.filter((m) => m.direction === 'out' && ['graduation', 'eligibility', 'draft'].includes(m.category ?? '')).length;
    const newsSum = notes.filter((nt) => inWin(nt.date)).reduce((sum, nt) => sum + (nt.pulse_delta ?? 0), 0);
    const cws = games.some((g) => {
      const v = (g.venue ?? '').toLowerCase();
      return (v.includes('charles schwab') || v.includes('omaha')) && inWin(g.start_date);
    });
    const out: Driver[] = [];
    if (current?.ranking) out.push({ label: `#${current.ranking} nationally`, kind: 'rank' });
    if (Math.round(newsSum) !== 0) out.push({ label: newsSum > 0 ? 'News buzz' : 'Recent news', delta: Math.round(newsSum), kind: 'news' });
    if (cws) out.push({ label: 'CWS run', kind: 'post' });
    if (tin || tout) out.push({ label: `Transfers +${tin}/-${tout}`, delta: Math.round((tin - tout) * 1.5), kind: 'portal' });
    if (recruits) out.push({ label: `Recruits +${recruits}`, delta: Math.round(recruits * 0.8), kind: 'recruit' });
    if (departures) out.push({ label: `Departures -${departures}`, delta: Math.round(departures * -0.4), kind: 'depart' });
    return out;
  }, [points, n, moves, notes, games, current]);

  return (
    <Modal visible={!!sport} animationType="slide" transparent={false} onRequestClose={onClose}>
      <View style={{ flex: 1, backgroundColor: c.bg }}>
        <View style={[styles.header, { paddingTop: insets.top + 8 }]}>
          <Pressable onPress={onClose} hitSlop={12} style={styles.circleBtn}>
            <Ionicons name="chevron-back" size={20} color={c.textSecondary} />
          </Pressable>
          <Text style={styles.headerTitle}>{curSport ? SPORT_NAME[curSport] : ''} Pulse</Text>
          {/* Invisible spacer — balances the back button so the title stays centered. */}
          <View style={{ width: 32, height: 32 }} />
        </View>

        {loading ? (
          <View style={styles.content}>
            {/* sport tabs */}
            <Skeleton width={'100%'} height={38} radius={12} />
            {/* score block */}
            <View style={{ marginTop: 22, gap: 10 }}>
              <Skeleton width={90} height={11} radius={4} />
              <Skeleton width={150} height={72} radius={14} />
              <Skeleton width={120} height={22} radius={999} />
            </View>
            {/* chart + range + panel */}
            <Skeleton width={'100%'} height={210} radius={16} style={{ marginTop: 16 }} />
            <Skeleton width={'100%'} height={38} radius={12} style={{ marginTop: 14 }} />
            <Skeleton width={'100%'} height={120} radius={18} style={{ marginTop: 16 }} />
          </View>
        ) : (
          <ScrollView contentContainerStyle={styles.content}>
            <Segmented options={SPORT_OPTS} value={curSport ?? 'football'} onChange={setCurSport} />

            <View style={{ marginTop: 22 }}>
              <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
                <SectionLabel tone="muted">Pulse Score</SectionLabel>
                <Pressable onPress={() => setShowExplainer(true)} hitSlop={10}>
                  <Ionicons name="information-circle-outline" size={15} color={c.textMuted} />
                </Pressable>
              </View>
              <Text style={styles.bigScore}>{displayScore ?? '—'}</Text>
              {n >= 2 && (
                <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8, marginTop: 6 }}>
                  <View style={[styles.deltaTag, { backgroundColor: deltaColor + '22' }]}>
                    <Text style={{ fontFamily: Font.bodyBold, fontSize: 13, color: deltaColor }}>
                      {rangeDelta > 0 ? '▲ +' : rangeDelta < 0 ? '▼ ' : ''}
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
                  <PulseChart
                    data={points}
                    textColor={c.textSecondary}
                    gridColor={c.border}
                    onActiveChange={(i) => {
                      setActiveIdx(i);
                      if (i !== n - 1) setEverScrubbed(true); // any real move off the latest point = learned
                    }}
                    runDemo={runScrubDemo}
                    onDemoComplete={() => {
                      setRunScrubDemo(false);
                      AsyncStorage.setItem(SCRUB_DEMO_KEY, '1');
                    }}
                  />
                  {!everScrubbed && (
                    <View style={styles.scrubHint}>
                      <Ionicons name="hand-left-outline" size={13} color={c.textMuted} />
                      <Text style={styles.scrubHintText}>Drag across the line to explore any day</Text>
                    </View>
                  )}
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
                  {briefIsForToday && (
                    <View style={{ marginTop: noteForWindow ? 12 : 8 }}>
                      <Text style={styles.briefTag}>Today's briefing</Text>
                      {todayBrief!.items.map((it, i) => (
                        <View key={i} style={styles.briefRow}>
                          <View style={styles.briefBullet} />
                          <View style={{ flex: 1 }}>
                            <Text style={styles.briefTopic}>{it.topic}</Text>
                            <Text style={styles.briefBody}>{it.body}</Text>
                          </View>
                        </View>
                      ))}
                    </View>
                  )}
                  {activeEvents.length > 0 && (
                    <View style={{ marginTop: 10, gap: 4 }}>
                      {(showAllEvents ? activeEvents : activeEvents.slice(0, 6)).map((e, i) => {
                        const pending = e.kind === 'pending';
                        const good = e.kind === 'win' || e.kind === 'in';
                        const tagBg = pending ? Brand.goldTint : good ? Brand.greenTint : Brand.redTint;
                        const tagColor = pending ? Brand.gold : good ? Brand.green : Brand.red;
                        const tagText = e.kind === 'in' ? '↓ IN' : e.kind === 'out' ? '↑ OUT'
                          : pending ? 'DRAFT?' : good ? 'W' : 'L';
                        return (
                          <View key={i} style={{ flexDirection: 'row', alignItems: 'flex-start', gap: 8 }}>
                            <View style={[styles.evTag, { backgroundColor: tagBg }]}>
                              <Text style={{ fontSize: 10, fontFamily: Font.bodyBold, color: tagColor }}>{tagText}</Text>
                            </View>
                            <Text style={styles.evLabel} numberOfLines={pending ? 2 : 1}>{e.label}</Text>
                          </View>
                        );
                      })}
                      {activeEvents.length > 6 && (
                        <Pressable onPress={() => setShowAllEvents((v) => !v)} hitSlop={8} style={{ paddingTop: 6 }}>
                          <Text style={styles.showAll}>
                            {showAllEvents ? 'Show less' : `Show all ${activeEvents.length} events`}
                          </Text>
                        </Pressable>
                      )}
                    </View>
                  )}
                  {!noteForWindow && activeEvents.length === 0 && !briefIsForToday && (
                    <Text style={styles.quiet}>No notable change on this date.</Text>
                  )}
                </View>

                {/* Drivers — scoped to the visible range window */}
                <SectionLabel tone="muted" style={{ marginTop: 22, marginBottom: 8 } as never}>
                  {`What's driving the score · ${RANGES[rangeIdx].word}`}
                </SectionLabel>
                {rangeDrivers.length > 0 ? (
                  <View style={{ gap: 8 }}>
                    {rangeDrivers.map((d, i) => {
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
                ) : (
                  <Text style={styles.quiet}>No roster or news changes in this window.</Text>
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
        <PulseExplainer
          visible={showExplainer}
          onClose={() => setShowExplainer(false)}
          sportName={curSport ? SPORT_NAME[curSport] : undefined}
          drivers={current?.drivers}
        />
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
  briefTag: { fontFamily: Font.bodyBold, fontSize: 10, letterSpacing: 1, color: Brand.gold, textTransform: 'uppercase' },
  briefRow: { flexDirection: 'row', gap: 9, marginTop: 8 },
  briefBullet: { width: 5, height: 5, borderRadius: 3, backgroundColor: Brand.gold, marginTop: 6 },
  briefTopic: { fontFamily: Font.bodyBold, fontSize: 13.5, color: c.text, marginBottom: 2 },
  briefBody: { fontFamily: Font.body, fontSize: 13, lineHeight: 19, color: c.textSecondary },
  evTag: { borderRadius: 6, paddingHorizontal: 7, paddingVertical: 3, minWidth: 30, alignItems: 'center' },
  evLabel: { flex: 1, fontSize: 13, color: c.textSecondary, fontFamily: Font.bodyMed },
  quiet: { fontSize: 13, marginTop: 8, color: c.textMuted, fontFamily: Font.body },
  showAll: { fontFamily: Font.bodyBold, fontSize: 12.5, color: Brand.gold },
  scrubHint: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 6,
    marginTop: 8,
  },
  scrubHintText: { fontFamily: Font.body, fontSize: 12, color: c.textMuted },
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
