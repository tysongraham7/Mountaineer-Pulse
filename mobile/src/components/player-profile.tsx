import { Ionicons } from '@expo/vector-icons';
import { LinearGradient } from 'expo-linear-gradient';
import { useEffect, useState } from 'react';
import { Image, Modal, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { SectionLabel } from '@/components/ui';
import { Brand, Font, Gradients, surfaces } from '@/constants/brand';
import { supabase } from '@/lib/supabase';
import { Player, PlayerStat } from '@/lib/types';

const c = surfaces(true);
const CURRENT_SEASON = 2026;

const STAT_ROWS: [string, string, string][] = [
  ['passing', 'YDS', 'Passing Yds'],
  ['passing', 'TD', 'Passing TD'],
  ['passing', 'INT', 'INT Thrown'],
  ['passing', 'PCT', 'Completion %'],
  ['rushing', 'CAR', 'Carries'],
  ['rushing', 'YDS', 'Rushing Yds'],
  ['rushing', 'TD', 'Rushing TD'],
  ['receiving', 'REC', 'Receptions'],
  ['receiving', 'YDS', 'Receiving Yds'],
  ['receiving', 'TD', 'Receiving TD'],
  ['defensive', 'TOT', 'Tackles'],
  ['defensive', 'TFL', 'Tackles for Loss'],
  ['defensive', 'SACKS', 'Sacks'],
  ['defensive', 'PD', 'Pass Deflections'],
  ['interceptions', 'INT', 'Interceptions'],
  ['kicking', 'FGM', 'FG Made'],
  ['kicking', 'FGA', 'FG Att'],
  ['kicking', 'PTS', 'Points'],
  ['punting', 'NO', 'Punts'],
  ['punting', 'YPP', 'Yds / Punt'],
  ['hitting', 'AVG', 'Batting Avg'],
  ['hitting', 'H', 'Hits'],
  ['hitting', 'RBI', 'RBI'],
  ['hitting', 'R', 'Runs'],
  ['hitting', 'BB', 'Walks'],
  ['hitting', 'SO', 'Strikeouts'],
  ['pitching', 'ERA', 'ERA'],
  ['pitching', 'IP', 'Innings'],
  ['pitching', 'SO', 'Strikeouts (P)'],
  ['pitching', 'W', 'Wins'],
  ['pitching', 'L', 'Losses'],
  ['pitching', 'SV', 'Saves'],
  ['basketball', 'PPG', 'Points / G'],
  ['basketball', 'RPG', 'Rebounds / G'],
  ['basketball', 'APG', 'Assists / G'],
  ['basketball', 'SPG', 'Steals / G'],
  ['basketball', 'BPG', 'Blocks / G'],
  ['basketball', 'MPG', 'Minutes / G'],
  ['basketball', 'FG%', 'FG %'],
  ['basketball', '3P%', '3PT %'],
  ['basketball', 'FT%', 'FT %'],
  ['basketball', 'GP', 'Games'],
  ['basketball', 'GS', 'Starts'],
];

function fullName(p: Player): string {
  return `${p.first_name ?? ''} ${p.last_name ?? ''}`.trim() || 'Player';
}
function hometown(p: Player): string | null {
  const parts = [p.home_city, p.home_state].filter(Boolean);
  return parts.length ? parts.join(', ') : null;
}
const SPORT_LABEL: Record<string, string> = { football: 'Football', mbb: "Men's Basketball", baseball: 'Baseball' };

type ProfilePlayer = Player & { incoming?: boolean; note?: string | null; fromSchool?: string | null };

export function PlayerProfile({ player, onClose }: { player: ProfilePlayer | null; onClose: () => void }) {
  const insets = useSafeAreaInsets();
  const [stats, setStats] = useState<PlayerStat[]>([]);
  const [loadingStats, setLoadingStats] = useState(false);

  useEffect(() => {
    if (!player) return;
    setStats([]);
    setLoadingStats(true);
    supabase
      .from('player_stats')
      .select('*')
      .eq('player_id', player.id)
      .then(({ data }) => {
        setStats((data ?? []) as PlayerStat[]);
        setLoadingStats(false);
      });
  }, [player]);

  const subParts: string[] = [];
  if (player) {
    if (player.jersey != null) subParts.push(`#${player.jersey}`);
    if (player.position) subParts.push(player.position);
    if (player.class_display) subParts.push(player.class_display);
    if (player.height_display) subParts.push(player.height_display);
    if (player.weight) subParts.push(`${player.weight} lb`);
  }
  const originParts: string[] = [];
  if (player) {
    const town = hometown(player);
    if (town) originParts.push(town);
    if (player.fromSchool) originParts.push(`via ${player.fromSchool}`);
  }

  const lookup = new Map<string, string>();
  const seasonSet = new Set<number>();
  const teamBySeason = new Map<number, string>();
  for (const s of stats) {
    lookup.set(`${s.category}|${s.stat_type}|${s.season}`, s.stat ?? '');
    seasonSet.add(s.season);
    if (s.team) teamBySeason.set(s.season, s.team);
  }
  const hasHistory = seasonSet.size > 0;
  seasonSet.add(CURRENT_SEASON);
  const seasons = [...seasonSet].sort((a, b) => a - b);
  const hasPrevSchool = [...teamBySeason.values()].some((t) => t !== 'West Virginia');
  const presentRows = STAT_ROWS.filter(([cat, type]) => seasons.some((yr) => lookup.has(`${cat}|${type}|${yr}`)));
  const currentHasData = presentRows.some(([cat, type]) => lookup.has(`${cat}|${type}|${CURRENT_SEASON}`));

  return (
    <Modal visible={!!player} animationType="slide" onRequestClose={onClose}>
      <View style={{ flex: 1, backgroundColor: c.bg }}>
        {player && (
          <ScrollView contentContainerStyle={{ paddingBottom: 40 }}>
            {/* Gradient hero header */}
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
                  {[SPORT_LABEL[player.sport_id] ?? '', player.position].filter(Boolean).join(' · ')}
                </SectionLabel>
                <View style={styles.circleBtn} />
              </View>

              <View style={styles.heroBody}>
                {player.photo_url ? (
                  <Image source={{ uri: player.photo_url }} style={styles.photo} />
                ) : (
                  <View style={[styles.photo, styles.photoFallback]}>
                    <Text style={styles.photoInitials}>
                      {(player.first_name?.[0] ?? '') + (player.last_name?.[0] ?? '')}
                    </Text>
                  </View>
                )}
                <View style={{ flex: 1 }}>
                  <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                    <Text style={styles.name}>{fullName(player)}</Text>
                    {player.incoming && (
                      <View style={styles.inTag}>
                        <Text style={styles.inTagText}>↓ IN</Text>
                      </View>
                    )}
                  </View>
                  {subParts.length > 0 && <Text style={styles.heroSub}>{subParts.join(' · ')}</Text>}
                  {originParts.length > 0 && <Text style={styles.heroSub}>{originParts.join(' · ')}</Text>}
                </View>
              </View>
            </LinearGradient>

            <View style={{ paddingHorizontal: 20 }}>
              {/* Season stats */}
              {presentRows.length > 0 ? (
                <>
                  <SectionLabel tone="muted" style={styles.head as never}>Stats by Season</SectionLabel>
                  <View style={styles.table}>
                    <View style={[styles.tableRow, styles.tableHeadRow]}>
                      <Text style={[styles.tableLabel, styles.headText]} />
                      {seasons.map((yr) => {
                        const tm = teamBySeason.get(yr);
                        const prev = !!tm && tm !== 'West Virginia';
                        return (
                          <View key={yr} style={styles.headCell}>
                            <Text style={[styles.headText, { color: Brand.gold, textAlign: 'right' }]}>{yr}</Text>
                            {prev && (
                              <Text style={styles.headSchool} numberOfLines={2}>{tm}</Text>
                            )}
                          </View>
                        );
                      })}
                    </View>
                    {presentRows.map(([cat, type, label], i) => (
                      <View key={`${cat}|${type}`} style={[styles.tableRow, i === presentRows.length - 1 && { borderBottomWidth: 0 }]}>
                        <Text style={styles.tableLabel}>{label}</Text>
                        {seasons.map((yr) => {
                          const v = lookup.get(`${cat}|${type}|${yr}`);
                          return (
                            <Text key={yr} style={[styles.tableCell, { color: v ? c.text : c.textMuted }]}>
                              {v ?? '—'}
                            </Text>
                          );
                        })}
                      </View>
                    ))}
                  </View>
                  {(hasPrevSchool || !currentHasData) && (
                    <Text style={styles.note}>
                      {[
                        hasPrevSchool ? 'Seasons labeled with a school are stats from before WVU.' : '',
                        currentHasData ? '' : `${CURRENT_SEASON} fills in once the season kicks off.`,
                      ]
                        .filter(Boolean)
                        .join(' ')}
                    </Text>
                  )}
                </>
              ) : player.incoming && (player.note || player.fromSchool) ? (
                <>
                  <SectionLabel tone="muted" style={styles.head as never}>Before WVU</SectionLabel>
                  <View style={[styles.card, { paddingVertical: 16 }]}>
                    {player.fromSchool ? <Text style={styles.beforeSchool}>{player.fromSchool}</Text> : null}
                    {player.note ? (
                      <Text style={styles.beforeLine}>{player.note}</Text>
                    ) : (
                      <Text style={[styles.note, { textAlign: 'left', marginTop: 0 }]}>
                        Stats not available for this player's previous school.
                      </Text>
                    )}
                  </View>
                  <Text style={styles.note}>Last-season production before transferring (per On3 / SI reports).</Text>
                </>
              ) : (
                <Text style={styles.note}>
                  {loadingStats
                    ? 'Loading stats…'
                    : hasHistory
                      ? 'No season stats on record.'
                      : player.sport_id === 'football'
                        ? `No prior stats — ${CURRENT_SEASON} numbers begin at kickoff.`
                        : 'No stats on record yet.'}
                </Text>
              )}
            </View>
          </ScrollView>
        )}
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  hero: { paddingHorizontal: 20, paddingBottom: 20 },
  heroTop: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  circleBtn: { width: 32, height: 32, borderRadius: 16, backgroundColor: 'rgba(255,255,255,0.08)', alignItems: 'center', justifyContent: 'center' },
  heroBody: { flexDirection: 'row', alignItems: 'center', gap: 16, marginTop: 16 },
  photo: { width: 76, height: 76, borderRadius: 38, borderWidth: 2, borderColor: Brand.gold, backgroundColor: c.card },
  photoFallback: { alignItems: 'center', justifyContent: 'center' },
  photoInitials: { color: Brand.gold, fontSize: 24, fontFamily: Font.black },
  name: { fontFamily: Font.black, fontSize: 24, color: c.text, letterSpacing: -0.4 },
  inTag: { backgroundColor: 'rgba(75,201,126,0.15)', borderRadius: 6, paddingHorizontal: 8, paddingVertical: 3 },
  inTagText: { color: Brand.green, fontSize: 10, fontFamily: Font.bodyBold },
  heroSub: { fontSize: 13, color: c.blueLabel, marginTop: 3, fontFamily: Font.body },
  head: { marginTop: 20, marginBottom: 8 },
  card: { backgroundColor: c.card, borderWidth: 1, borderColor: c.border, borderRadius: 16, paddingHorizontal: 18 },
  table: { backgroundColor: c.card, borderWidth: 1, borderColor: c.border, borderRadius: 16, paddingHorizontal: 16, overflow: 'hidden' },
  tableRow: { flexDirection: 'row', alignItems: 'center', paddingVertical: 11, borderBottomWidth: 1, borderBottomColor: c.border },
  tableHeadRow: { borderBottomColor: c.border },
  tableLabel: { flex: 1.4, fontSize: 13, color: c.text, fontFamily: Font.bodyMed },
  tableCell: { flex: 1, fontSize: 13, color: c.text, textAlign: 'right', fontFamily: Font.bodySemi, fontVariant: ['tabular-nums'] },
  headCell: { flex: 1, alignItems: 'flex-end' },
  headText: { fontSize: 11, color: Brand.gold, fontFamily: Font.bodyBold, letterSpacing: 0.5 },
  headSchool: { fontSize: 9, color: c.textMuted, textAlign: 'right', marginTop: 1, fontFamily: Font.body },
  beforeSchool: { fontSize: 13, color: Brand.gold, fontFamily: Font.displaySemi, marginBottom: 6 },
  beforeLine: { fontSize: 15, color: c.text, lineHeight: 22, fontFamily: Font.body },
  note: { textAlign: 'center', marginTop: 16, fontSize: 12, color: c.textMuted, lineHeight: 18, fontFamily: Font.body },
});
