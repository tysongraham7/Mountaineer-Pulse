import { Ionicons } from '@expo/vector-icons';
import { LinearGradient } from 'expo-linear-gradient';
import { useEffect, useState } from 'react';
import { Modal, Pressable, ScrollView, Share, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { GameLive, gameStarted } from '@/components/game-live';
import { ReportModal } from '@/components/report-modal';
import { Matchup, ScoutingReport, scoutShareText } from '@/components/scouting-report';
import { SectionLabel, SportIcon } from '@/components/ui';
import { Brand, Font, Gradients, surfaces } from '@/constants/brand';
import { trackFeature } from '@/lib/analytics';
import { countdownLabel, easternDateLong, easternTime } from '@/lib/eastern';
import { supabase } from '@/lib/supabase';
import { Game } from '@/lib/types';
import { useGameSummary } from '@/lib/use-game-summary';
import { useLiveGame } from '@/lib/use-live-game';

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
  // Counted here rather than at the call sites so a tap from Scores, the home card, and a
  // kickoff alert all land in the same bucket -- and so a new way in gets counted for free.
  // Keyed on the id, not the object: one count per game opened, however many times the
  // sheet re-renders while it's up.
  const openGameId = game?.id;
  useEffect(() => { if (openGameId) trackFeature('game_sheet_open'); }, [openGameId]);
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
  const matchup = `${wvuHome ? 'vs' : 'at'} ${opponent}`;
  const final =
    game?.status === 'final' && game.home_points != null && game.away_points != null;
  const wvuPts = wvuHome ? game?.home_points : game?.away_points;
  const oppPts = wvuHome ? game?.away_points : game?.home_points;
  const won = final && (wvuPts ?? 0) > (oppPts ?? 0);

  const iso = game?.start_date ?? null;
  const kickoff = iso ? easternTime(iso) : null;
  const countdown = iso && !final ? countdownLabel(iso) : null;

  // The scoreboard line, from the same cheap feed the home card uses. Only football has an
  // ESPN event id on the row, and only football has a play-by-play worth showing; every
  // other sport falls through to the countdown and the scouting report as before.
  const liveId = game?.sport_id === 'football' ? (game.espn_event_id ?? null) : null;
  const live = useLiveGame(liveId, iso, wvuHome, 'WVU', opponent.slice(0, 4).toUpperCase());
  // The box score and play-by-play, on a slow tick. Lives here rather than in GameLive
  // because whether the game has started decides where the scouting report goes: at the
  // bottom of the sheet before kickoff, in a tab beside the box score after it.
  const summaryState = useGameSummary(liveId, wvuHome, !!game);
  const started = gameStarted(liveId, live, summaryState.summary);

  const onShare = async () => {
    if (!scout) return;
    trackFeature('scout_share');
    try {
      await Share.share({ message: scoutShareText(scout, matchup) });
    } catch {
      // User dismissed the sheet, or the OS refused it. Nothing to recover from.
    }
  };

  const rows: [string, string][] = [];
  if (iso) rows.push(['Date', easternDateLong(iso)]);
  // A null kickoff is a real state, not missing data — say so rather than print
  // the midnight placeholder the feed uses for an unannounced start.
  rows.push(['Time', kickoff ?? 'To be announced']);
  // Where to watch, right under when. Once the window is picked both arrive together, so
  // a known time with no network is rare and the row just stays out rather than saying
  // "To be announced" twice. Dropped for a final: the channel a played game was on is
  // trivia, and the table above a box score should be short.
  if (game?.broadcast && !final) rows.push(['Watch', game.broadcast]);
  if (game?.venue) rows.push(['Venue', game.venue]);
  rows.push(['Site', wvuHome ? 'Home' : 'Away']);
  if (game?.season_type === 'exhibition') rows.push(['Game', 'Exhibition']);
  if (game?.week != null) rows.push(['Week', String(game.week)]);

  return (
    <Modal visible={!!game} animationType="slide" onRequestClose={onClose}>
      <View style={{ flex: 1, backgroundColor: c.bg }}>
        {game && (
          <>
          {/* The blue hero IS the header: it owns the safe area, the back button and the
              share button, and it stays put while the sheet scrolls. There used to be a
              plain bar above it repeating "vs UT Martin" — pinned so the back button
              couldn't scroll away under a long scouting report. Pinning the hero itself
              keeps that without saying the opponent's name twice. */}
          <LinearGradient
            colors={Gradients.hero}
            start={{ x: 0.2, y: 0 }}
            end={{ x: 0.9, y: 1 }}
            style={[styles.hero, { paddingTop: insets.top + 6 }]}>
            <View style={styles.heroBar}>
              <Pressable onPress={onClose} hitSlop={12} style={styles.circleBtn}>
                <Ionicons name="chevron-back" size={20} color={c.text} />
              </Pressable>
              <SectionLabel style={styles.sportLabel as never}>
                {SPORT_LABEL[game.sport_id] ?? game.sport_id}
              </SectionLabel>
              {/* Shares the scouting report, so it appears only once there is one. The
                  spacer keeps the sport label centered until then. */}
              {scout ? (
                <Pressable onPress={onShare} hitSlop={12} style={styles.circleBtn}>
                  <Ionicons name="share-outline" size={18} color={c.text} />
                </Pressable>
              ) : (
                <View style={{ width: 32, height: 32 }} />
              )}
            </View>

            <View style={styles.heroBody}>
              <View style={styles.tile}>
                <SportIcon sport={game.sport_id} size={24} color={Brand.gold} />
              </View>
              <View style={{ flex: 1 }}>
                <Text style={styles.locator}>{wvuHome ? 'vs' : 'at'}</Text>
                <Text style={styles.opponent} numberOfLines={1}>{opponent}</Text>
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

          <ScrollView contentContainerStyle={{ paddingBottom: 40 }}>
            <View style={{ paddingHorizontal: 20 }}>
              {/* Everything that only exists once the ball is snapped: score, box score,
                  play-by-play, team stats — and the scouting report, as a tab, so it
                  isn't the tail of every other tab. */}
              {started && (
                <GameLive
                  game={game}
                  live={live}
                  summaryState={summaryState}
                  scout={scout ? <ScoutingReport scout={scout} /> : undefined}
                />
              )}

              {/* The one thing in a preview a fan has to act on BEFORE leaving the house,
                  so it sits above the report rather than inside it. Home games only —
                  an away game's promo belongs to the other school. */}
              {!!game.theme && (
                <View style={styles.themeCard}>
                  <Ionicons name="shirt-outline" size={16} color={Brand.gold} />
                  <View style={{ flex: 1 }}>
                    <Text style={styles.themeLabel}>GAME DAY THEME</Text>
                    <Text style={styles.themeText}>{game.theme}</Text>
                  </View>
                </View>
              )}

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
                  Kickoff time and network are usually set about two weeks out, once TV picks the window.
                </Text>
              )}

              {/* Before kickoff the report is the sheet's main event and reads inline.
                  Once the game starts it has moved into the tab bar above. */}
              {scout && !started && <ScoutingReport scout={scout} titled />}

              <Pressable style={styles.reportBtn} onPress={() => setReportOpen(true)} hitSlop={8}>
                <Ionicons name="flag-outline" size={13} color={c.textMuted} />
                <Text style={styles.reportText}>Report incorrect info</Text>
              </Pressable>
            </View>
          </ScrollView>
          </>
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
  hero: { paddingHorizontal: 20, paddingBottom: 18 },
  heroBar: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 12 },
  sportLabel: { flex: 1, textAlign: 'center', color: c.blueLabel },
  // A translucent circle rather than the sheet's surface3 one: this sits on the gradient,
  // and a near-black disc on WVU blue looks like a hole.
  circleBtn: {
    width: 32,
    height: 32,
    borderRadius: 16,
    backgroundColor: 'rgba(255,255,255,0.10)',
    borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.14)',
    alignItems: 'center',
    justifyContent: 'center',
  },
  heroBody: { flexDirection: 'row', alignItems: 'center', gap: 14, marginTop: 12 },
  tile: { width: 48, height: 48, borderRadius: 13, backgroundColor: Brand.goldTint, borderWidth: 1, borderColor: Brand.goldBorder, alignItems: 'center', justifyContent: 'center' },
  locator: { fontFamily: Font.body, fontSize: 13, color: c.blueLabel },
  opponent: { fontFamily: Font.black, fontSize: 24, color: c.text, letterSpacing: -0.4, marginTop: 1 },
  resultTag: { fontFamily: Font.black, fontSize: 15 },
  score: { fontFamily: Font.displaySemi, fontSize: 20, color: c.text, marginTop: 1, fontVariant: ['tabular-nums'] },
  countdownPill: { backgroundColor: Brand.goldTint, borderWidth: 1, borderColor: Brand.goldBorder, borderRadius: 8, paddingHorizontal: 10, paddingVertical: 5 },
  countdownText: { fontFamily: Font.bodyBold, fontSize: 12, color: Brand.gold },
  head: { marginTop: 20, marginBottom: 8 },
  themeCard: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 11,
    marginTop: 18,
    paddingVertical: 12,
    paddingHorizontal: 14,
    borderRadius: 14,
    backgroundColor: Brand.goldTint,
    borderWidth: 1,
    borderColor: Brand.goldBorder,
  },
  themeLabel: { fontFamily: Font.bodyBold, fontSize: 9.5, letterSpacing: 1, color: Brand.gold },
  themeText: { fontFamily: Font.displaySemi, fontSize: 14.5, color: c.text, marginTop: 3, lineHeight: 20 },
  table: { backgroundColor: c.card, borderWidth: 1, borderColor: c.border, borderRadius: 16, paddingHorizontal: 16 },
  tableRow: { flexDirection: 'row', alignItems: 'center', gap: 16, paddingVertical: 13, borderBottomWidth: 1, borderBottomColor: c.border },
  tableLabel: { flex: 0.8, fontSize: 13, color: c.textSecondary, fontFamily: Font.bodyMed },
  tableValue: { flex: 2, fontSize: 14, color: c.text, textAlign: 'right', fontFamily: Font.bodySemi },
  note: { textAlign: 'center', marginTop: 16, fontSize: 12, color: c.textMuted, lineHeight: 18, fontFamily: Font.body },
  reportBtn: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 6, marginTop: 24, paddingVertical: 8 },
  reportText: { fontSize: 12.5, color: c.textMuted, fontFamily: Font.bodyMed },
});
