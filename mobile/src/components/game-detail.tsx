import { Ionicons } from '@expo/vector-icons';
import { LinearGradient } from 'expo-linear-gradient';
import { useEffect, useState } from 'react';
import { Modal, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { ReportModal } from '@/components/report-modal';
import { SectionLabel, SportIcon } from '@/components/ui';
import { Brand, Font, Gradients, surfaces } from '@/constants/brand';
import { countdownLabel, easternDateLong, easternTime } from '@/lib/eastern';
import { supabase } from '@/lib/supabase';
import { Game } from '@/lib/types';

/** The scouting report generate_matchup.py writes, ~10 days out from kickoff. */
type Matchup = {
  headline: string;
  opponent: { record: string; snapshot: string };
  history: string;
  watch: { topic: string; body: string }[];
  injuries: string;
  weather: string;
  /** Set when the report was written. Its contents move, so the sheet says when. */
  generated_at?: string;
};

const c = surfaces(true);

const SPORT_LABEL: Record<string, string> = {
  football: 'Football',
  mbb: "Men's Basketball",
  baseball: 'Baseball',
};

/** Trim "West Virginia Mountaineers" and the like down to the school. */
function shortTeam(name: string): string {
  return name.replace(/\s+(Mountaineers|Tar Heels|Trojans|Bears|Cowboys|Cyclones|Wildcats|Bearcats|Horned Frogs)$/i, '');
}

export function GameDetail({ game, onClose }: { game: Game | null; onClose: () => void }) {
  const insets = useSafeAreaInsets();
  const [reportOpen, setReportOpen] = useState(false);
  // Absent for most of the year — the report is only written near kickoff, so every field
  // below renders conditionally and the sheet looks normal when there is nothing yet.
  const [scout, setScout] = useState<Matchup | null>(null);

  useEffect(() => {
    if (!game?.id) { setScout(null); return; }
    let live = true;
    supabase.from('matchups').select('sections,generated_at').eq('game_id', game.id).maybeSingle()
      .then(({ data }) => {
        if (!live) return;
        setScout(data?.sections
          ? { ...(data.sections as Matchup), generated_at: data.generated_at as string }
          : null);
      });
    return () => { live = false; };
  }, [game?.id]);

  const wvuHome = !!game?.is_wvu_home;
  const opponent = game ? shortTeam(wvuHome ? game.away_team : game.home_team) : '';
  const final =
    game?.status === 'final' && game.home_points != null && game.away_points != null;
  const wvuPts = wvuHome ? game?.home_points : game?.away_points;
  const oppPts = wvuHome ? game?.away_points : game?.home_points;
  const won = final && (wvuPts ?? 0) > (oppPts ?? 0);

  const iso = game?.start_date ?? null;
  const kickoff = iso ? easternTime(iso) : null;
  const countdown = iso && !final ? countdownLabel(iso) : null;

  const rows: [string, string][] = [];
  if (iso) rows.push(['Date', easternDateLong(iso)]);
  // A null kickoff is a real state, not missing data — say so rather than print
  // the midnight placeholder the feed uses for an unannounced start.
  rows.push(['Time', kickoff ?? 'To be announced']);
  if (game?.venue) rows.push(['Venue', game.venue]);
  rows.push(['Site', wvuHome ? 'Home' : 'Away']);
  if (game?.week != null) rows.push(['Week', String(game.week)]);

  return (
    <Modal visible={!!game} animationType="slide" onRequestClose={onClose}>
      <View style={{ flex: 1, backgroundColor: c.bg }}>
        {game && (
          <ScrollView contentContainerStyle={{ paddingBottom: 40 }}>
            <LinearGradient
              colors={Gradients.hero}
              start={{ x: 0.2, y: 0 }}
              end={{ x: 0.9, y: 1 }}
              style={[styles.hero, { paddingTop: insets.top + 8 }]}>
              <View style={styles.heroTop}>
                <Pressable onPress={onClose} hitSlop={12} style={styles.circleBtn}>
                  <Ionicons name="chevron-back" size={20} color="#C8D4E4" />
                </Pressable>
                <SectionLabel style={{ color: c.blueLabel } as never}>
                  {SPORT_LABEL[game.sport_id] ?? game.sport_id}
                </SectionLabel>
                {/* Balances the back button so the label stays centred. Sized, not
                    styled — reusing circleBtn drew an empty circle in the corner. */}
                <View style={styles.headerSpacer} />
              </View>

              <View style={styles.heroBody}>
                <View style={styles.tile}>
                  <SportIcon sport={game.sport_id} size={24} color={Brand.gold} />
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.locator}>{wvuHome ? 'vs' : 'at'}</Text>
                  <Text style={styles.opponent}>{opponent}</Text>
                </View>
                {final ? (
                  <View style={{ alignItems: 'flex-end' }}>
                    <Text style={[styles.resultTag, { color: won ? Brand.green : Brand.red }]}>
                      {won ? 'W' : 'L'}
                    </Text>
                    <Text style={styles.score}>{wvuPts}–{oppPts}</Text>
                  </View>
                ) : countdown ? (
                  <View style={styles.countdownPill}>
                    <Text style={styles.countdownText}>{countdown}</Text>
                  </View>
                ) : null}
              </View>
            </LinearGradient>

            <View style={{ paddingHorizontal: 20 }}>
              <SectionLabel tone="muted" style={styles.head as never}>Game Info</SectionLabel>
              <View style={styles.table}>
                {rows.map(([label, value], i) => (
                  <View
                    key={label}
                    style={[styles.tableRow, i === rows.length - 1 && { borderBottomWidth: 0 }]}>
                    <Text style={styles.tableLabel}>{label}</Text>
                    <Text style={styles.tableValue}>{value}</Text>
                  </View>
                ))}
              </View>

              {!final && !kickoff && (
                <Text style={styles.note}>
                  Kickoff times are usually set about two weeks out, once TV picks the window.
                </Text>
              )}

              {scout && (
                <>
                  <SectionLabel style={styles.head as never}>Scouting Report</SectionLabel>
                  {!!scout.headline && <Text style={styles.scoutLede}>{scout.headline}</Text>}

                  {(!!scout.opponent?.record || !!scout.opponent?.snapshot) && (
                    <View style={styles.scoutCard}>
                      {!!scout.opponent.record && (
                        <Text style={styles.scoutRecord}>{scout.opponent.record}</Text>
                      )}
                      {!!scout.opponent.snapshot && (
                        <Text style={styles.scoutBody}>{scout.opponent.snapshot}</Text>
                      )}
                    </View>
                  )}

                  {scout.watch?.map((w, i) => (
                    <View key={i} style={styles.scoutCard}>
                      <Text style={styles.scoutTopic}>{w.topic}</Text>
                      <Text style={styles.scoutBody}>{w.body}</Text>
                    </View>
                  ))}

                  {[['Series', scout.history], ['Injuries', scout.injuries],
                    ['Weather', scout.weather]]
                    .filter(([, v]) => !!(v || '').trim())
                    .map(([label, v]) => (
                      <View key={label} style={styles.scoutCard}>
                        <Text style={styles.scoutTopic}>{label}</Text>
                        <Text style={styles.scoutBody}>{v}</Text>
                      </View>
                    ))}

                  <Text style={styles.scoutNote}>
                    {scout.generated_at
                      ? `Researched from public sources on ${easternDateLong(scout.generated_at)}. Injuries and availability can change before kickoff.`
                      : 'Researched from public sources. Injuries and availability can change before kickoff.'}
                  </Text>
                </>
              )}

              <Pressable style={styles.reportBtn} onPress={() => setReportOpen(true)} hitSlop={8}>
                <Ionicons name="flag-outline" size={13} color={c.textMuted} />
                <Text style={styles.reportText}>Report incorrect info</Text>
              </Pressable>
            </View>
          </ScrollView>
        )}
        <ReportModal
          visible={reportOpen}
          onClose={() => setReportOpen(false)}
          context={{ screen: 'game', sport: game?.sport_id }}
        />
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  hero: { paddingHorizontal: 20, paddingBottom: 22 },
  heroTop: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  circleBtn: { width: 32, height: 32, borderRadius: 16, backgroundColor: 'rgba(255,255,255,0.08)', alignItems: 'center', justifyContent: 'center' },
  headerSpacer: { width: 32, height: 32 },
  heroBody: { flexDirection: 'row', alignItems: 'center', gap: 14, marginTop: 18 },
  tile: { width: 48, height: 48, borderRadius: 13, backgroundColor: Brand.goldTint, borderWidth: 1, borderColor: Brand.goldBorder, alignItems: 'center', justifyContent: 'center' },
  locator: { fontFamily: Font.body, fontSize: 13, color: c.blueLabel },
  opponent: { fontFamily: Font.black, fontSize: 24, color: c.text, letterSpacing: -0.4, marginTop: 1 },
  resultTag: { fontFamily: Font.black, fontSize: 15 },
  score: { fontFamily: Font.displaySemi, fontSize: 20, color: c.text, marginTop: 1, fontVariant: ['tabular-nums'] },
  countdownPill: { backgroundColor: Brand.goldTint, borderWidth: 1, borderColor: Brand.goldBorder, borderRadius: 8, paddingHorizontal: 10, paddingVertical: 5 },
  countdownText: { fontFamily: Font.bodyBold, fontSize: 12, color: Brand.gold },
  head: { marginTop: 20, marginBottom: 8 },
  table: { backgroundColor: c.card, borderWidth: 1, borderColor: c.border, borderRadius: 16, paddingHorizontal: 16 },
  tableRow: { flexDirection: 'row', alignItems: 'center', gap: 16, paddingVertical: 13, borderBottomWidth: 1, borderBottomColor: c.border },
  tableLabel: { flex: 0.8, fontSize: 13, color: c.textSecondary, fontFamily: Font.bodyMed },
  tableValue: { flex: 2, fontSize: 14, color: c.text, textAlign: 'right', fontFamily: Font.bodySemi },
  note: { textAlign: 'center', marginTop: 16, fontSize: 12, color: c.textMuted, lineHeight: 18, fontFamily: Font.body },
  reportBtn: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 6, marginTop: 24, paddingVertical: 8 },
  reportText: { fontSize: 12.5, color: c.textMuted, fontFamily: Font.bodyMed },

  // Scouting report. Same card language as Game Info above so it reads as one sheet.
  scoutLede: { fontFamily: Font.displaySemi, fontSize: 16, lineHeight: 23, color: c.text, marginBottom: 12 },
  scoutCard: {
    backgroundColor: c.card,
    borderColor: c.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 14,
    marginBottom: 10,
  },
  scoutRecord: { fontFamily: Font.bodyBold, fontSize: 12, letterSpacing: 0.6, color: Brand.gold, marginBottom: 6 },
  scoutTopic: { fontFamily: Font.displaySemi, fontSize: 14.5, color: c.text, marginBottom: 5 },
  scoutBody: { fontFamily: Font.body, fontSize: 13.5, lineHeight: 20, color: c.textSecondary },
  scoutNote: { fontFamily: Font.body, fontSize: 11.5, lineHeight: 17, color: c.textMuted, marginTop: 4 },
});
