import { Ionicons } from '@expo/vector-icons';
import { useEffect, useState } from 'react';
import { Image, Modal, Pressable, ScrollView, StyleSheet, Text, View, useColorScheme } from 'react-native';

import { Brand, surfaces } from '@/constants/brand';
import { supabase } from '@/lib/supabase';
import { Player, PlayerStat } from '@/lib/types';

// Football season currently in progress (its stats fill in once games are played).
const CURRENT_SEASON = 2026;

// Curated, ordered stat lines to surface. Only rows a player actually has are shown.
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
  // baseball — hitting
  ['hitting', 'AVG', 'Batting Avg'],
  ['hitting', 'H', 'Hits'],
  ['hitting', 'RBI', 'RBI'],
  ['hitting', 'R', 'Runs'],
  ['hitting', 'BB', 'Walks'],
  ['hitting', 'SO', 'Strikeouts'],
  // baseball — pitching
  ['pitching', 'ERA', 'ERA'],
  ['pitching', 'IP', 'Innings'],
  ['pitching', 'SO', 'Strikeouts (P)'],
  ['pitching', 'W', 'Wins'],
  ['pitching', 'L', 'Losses'],
  ['pitching', 'SV', 'Saves'],
];

function fullName(p: Player): string {
  return `${p.first_name ?? ''} ${p.last_name ?? ''}`.trim() || 'Player';
}

function hometown(p: Player): string | null {
  const parts = [p.home_city, p.home_state].filter(Boolean);
  return parts.length ? parts.join(', ') : null;
}

export function PlayerProfile({ player, onClose }: { player: Player | null; onClose: () => void }) {
  const dark = useColorScheme() === 'dark';
  const c = surfaces(dark);

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

  const bio: { label: string; value: string }[] = [];
  if (player) {
    if (player.position) bio.push({ label: 'Position', value: player.position });
    if (player.jersey != null) bio.push({ label: 'Number', value: `#${player.jersey}` });
    if (player.class_display) bio.push({ label: 'Class', value: player.class_display });
    if (player.height_display) bio.push({ label: 'Height', value: player.height_display });
    if (player.weight) bio.push({ label: 'Weight', value: `${player.weight} lb` });
    const town = hometown(player);
    if (town) bio.push({ label: 'Hometown', value: town });
  }

  // Pivot stat lines into a season table.
  const lookup = new Map<string, string>();
  const seasonSet = new Set<number>();
  const teamBySeason = new Map<number, string>(); // which school the player was at that year
  for (const s of stats) {
    lookup.set(`${s.category}|${s.stat_type}|${s.season}`, s.stat ?? '');
    seasonSet.add(s.season);
    if (s.team) teamBySeason.set(s.season, s.team);
  }
  const hasHistory = seasonSet.size > 0;
  seasonSet.add(CURRENT_SEASON); // always show the current season column
  const seasons = [...seasonSet].sort((a, b) => a - b);
  const hasPrevSchool = [...teamBySeason.values()].some((t) => t !== 'West Virginia');
  const presentRows = STAT_ROWS.filter(([cat, type]) =>
    seasons.some((yr) => lookup.has(`${cat}|${type}|${yr}`)),
  );
  // Only nudge "fills in at kickoff" when the current season truly has no data
  // (true for football's upcoming year; baseball's 2026 is already complete).
  const currentHasData = presentRows.some(([cat, type]) => lookup.has(`${cat}|${type}|${CURRENT_SEASON}`));

  return (
    <Modal visible={!!player} animationType="slide" onRequestClose={onClose}>
      <View style={{ flex: 1, backgroundColor: c.bg }}>
        <View style={[styles.header, { backgroundColor: Brand.blue }]}>
          <Pressable onPress={onClose} hitSlop={12}>
            <Ionicons name="close" size={26} color="#fff" />
          </Pressable>
        </View>

        {player && (
          <ScrollView contentContainerStyle={styles.content}>
            <View style={styles.hero}>
              {player.photo_url ? (
                <Image source={{ uri: player.photo_url }} style={styles.photo} />
              ) : (
                <View style={[styles.photo, styles.photoFallback, { backgroundColor: Brand.blue }]}>
                  <Text style={styles.photoInitials}>
                    {(player.first_name?.[0] ?? '') + (player.last_name?.[0] ?? '')}
                  </Text>
                </View>
              )}
              {player.jersey != null && (
                <Text style={[styles.jersey, { color: Brand.gold }]}>#{player.jersey}</Text>
              )}
              <Text style={[styles.name, { color: c.text }]}>{fullName(player)}</Text>
              <Text style={[styles.sub, { color: c.textSecondary }]}>
                {[player.position, player.class_display].filter(Boolean).join(' · ')}
              </Text>
            </View>

            <View style={[styles.statCard, { backgroundColor: c.card, borderColor: c.border }]}>
              {bio.map((s, i) => (
                <View
                  key={s.label}
                  style={[
                    styles.statRow,
                    { borderBottomColor: c.border, borderBottomWidth: i === bio.length - 1 ? 0 : 1 },
                  ]}>
                  <Text style={[styles.statLabel, { color: c.textSecondary }]}>{s.label}</Text>
                  <Text style={[styles.statValue, { color: c.text }]}>{s.value}</Text>
                </View>
              ))}
            </View>

            {/* Season stats */}
            {presentRows.length > 0 ? (
              <>
                <Text style={[styles.sectionHead, { color: c.text }]}>Stats by Season</Text>
                <View style={[styles.statCard, { backgroundColor: c.card, borderColor: c.border }]}>
                  <View style={[styles.tableRow, { borderBottomColor: c.border }]}>
                    <Text style={[styles.tableLabel, styles.tableHeadText, { color: c.textSecondary }]} />
                    {seasons.map((yr) => {
                      const tm = teamBySeason.get(yr);
                      const prev = !!tm && tm !== 'West Virginia';
                      return (
                        <View key={yr} style={styles.tableHeadCell}>
                          <Text style={[styles.tableHeadText, { color: Brand.gold, textAlign: 'right' }]}>{yr}</Text>
                          {prev && (
                            <Text style={[styles.headSchool, { color: c.textSecondary }]} numberOfLines={2}>
                              {tm}
                            </Text>
                          )}
                        </View>
                      );
                    })}
                  </View>
                  {presentRows.map(([cat, type, label], i) => (
                    <View
                      key={`${cat}|${type}`}
                      style={[
                        styles.tableRow,
                        { borderBottomColor: c.border, borderBottomWidth: i === presentRows.length - 1 ? 0 : 1 },
                      ]}>
                      <Text style={[styles.tableLabel, { color: c.text }]}>{label}</Text>
                      {seasons.map((yr) => {
                        const v = lookup.get(`${cat}|${type}|${yr}`);
                        return (
                          <Text key={yr} style={[styles.tableCell, { color: v ? c.text : c.textSecondary }]}>
                            {v ?? '—'}
                          </Text>
                        );
                      })}
                    </View>
                  ))}
                </View>
                {(hasPrevSchool || !currentHasData) && (
                  <Text style={[styles.note, { color: c.textSecondary }]}>
                    {[
                      hasPrevSchool ? 'Seasons labeled with a school are stats from before WVU.' : '',
                      currentHasData ? '' : `${CURRENT_SEASON} fills in once the season kicks off.`,
                    ]
                      .filter(Boolean)
                      .join(' ')}
                  </Text>
                )}
              </>
            ) : (
              <Text style={[styles.note, { color: c.textSecondary }]}>
                {loadingStats
                  ? 'Loading stats…'
                  : hasHistory
                  ? 'No season stats on record.'
                  : `No prior stats — ${CURRENT_SEASON} numbers begin at kickoff.`}
              </Text>
            )}
          </ScrollView>
        )}
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  header: { paddingTop: 54, paddingBottom: 12, paddingHorizontal: 18 },
  content: { padding: 20, paddingBottom: 40 },
  hero: { alignItems: 'center', marginBottom: 20 },
  photo: { width: 128, height: 128, borderRadius: 64, backgroundColor: '#0002' },
  photoFallback: { alignItems: 'center', justifyContent: 'center' },
  photoInitials: { color: '#fff', fontSize: 40, fontWeight: '900' },
  jersey: { fontSize: 16, fontWeight: '900', marginTop: 10 },
  name: { fontSize: 26, fontWeight: '900', marginTop: 4, textAlign: 'center' },
  sub: { fontSize: 15, fontWeight: '600', marginTop: 4 },
  statCard: { borderWidth: 1, borderRadius: 14, paddingHorizontal: 16 },
  statRow: { flexDirection: 'row', justifyContent: 'space-between', paddingVertical: 14 },
  statLabel: { fontSize: 14, fontWeight: '600' },
  statValue: { fontSize: 15, fontWeight: '800' },
  sectionHead: { fontSize: 18, fontWeight: '800', marginTop: 22, marginBottom: 10 },
  tableRow: { flexDirection: 'row', alignItems: 'center', paddingVertical: 12, borderBottomWidth: 1 },
  tableLabel: { flex: 1, fontSize: 14, fontWeight: '600' },
  tableCell: { width: 64, fontSize: 15, fontWeight: '800', textAlign: 'right' },
  tableHeadCell: { width: 64, alignItems: 'flex-end' },
  headSchool: { fontSize: 9, fontWeight: '700', textAlign: 'right', marginTop: 1 },
  tableHeadText: { fontSize: 13, fontWeight: '900', letterSpacing: 0.5 },
  note: { textAlign: 'center', marginTop: 18, fontSize: 12 },
});
