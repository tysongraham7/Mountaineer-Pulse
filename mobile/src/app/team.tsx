import { Ionicons } from '@expo/vector-icons';
import { useLocalSearchParams } from 'expo-router';
import * as WebBrowser from 'expo-web-browser';
import { useCallback, useEffect, useState } from 'react';
import {
  Image,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { OfflineNotice } from '@/components/offline-notice';
import { PlayerProfile } from '@/components/player-profile';
import { ListRowSkeleton, SkeletonList } from '@/components/skeleton';
import { Brand, Font, surfaces } from '@/constants/brand';
import { supabase } from '@/lib/supabase';
import { useForegroundRefresh } from '@/lib/use-foreground-refresh';
import { DepthEntry, Player, RosterMove } from '@/lib/types';

const c = surfaces(true);

const FILTERS = [
  { id: 'football', label: 'Football' },
  { id: 'mbb', label: 'Basketball' },
  { id: 'baseball', label: 'Baseball' },
] as const;

const MODES = [
  { id: 'roster', label: 'Roster' },
  { id: 'depth', label: 'Depth' },
  { id: 'movement', label: 'Movement' },
  { id: 'leaders', label: 'Leaders' },
] as const;

// Completed seasons we have stats for, per sport.
const LEADER_SEASONS_BY_SPORT: Record<string, number[]> = {
  football: [2025, 2024],
  baseball: [2026],
  mbb: [2026], // 2025-26 season
};

// Leaderboards per sport. `asc` = lower is better (ERA); `qual*` gates rate stats
// by a minimum (e.g. AVG needs enough at-bats) so tiny samples don't top the board.
type Board = {
  title: string;
  cat: string;
  type: string;
  top: number;
  asc?: boolean;
  qualCat?: string;
  qualType?: string;
  qualMin?: number;
};

const LEADERBOARDS_BY_SPORT: Record<string, Board[]> = {
  football: [
    { title: 'Passing Yards', cat: 'passing', type: 'YDS', top: 3 },
    { title: 'Rushing Yards', cat: 'rushing', type: 'YDS', top: 3 },
    { title: 'Receiving Yards', cat: 'receiving', type: 'YDS', top: 3 },
    { title: 'Receptions', cat: 'receiving', type: 'REC', top: 3 },
    { title: 'Total Tackles', cat: 'defensive', type: 'TOT', top: 5 },
    { title: 'Tackles for Loss', cat: 'defensive', type: 'TFL', top: 3 },
    { title: 'Sacks', cat: 'defensive', type: 'SACKS', top: 3 },
    { title: 'Interceptions', cat: 'interceptions', type: 'INT', top: 3 },
    { title: 'Kicking Points', cat: 'kicking', type: 'PTS', top: 3 },
  ],
  baseball: [
    { title: 'Batting Average', cat: 'hitting', type: 'AVG', top: 5, qualCat: 'hitting', qualType: 'AB', qualMin: 60 },
    { title: 'Hits', cat: 'hitting', type: 'H', top: 5 },
    { title: 'RBI', cat: 'hitting', type: 'RBI', top: 5 },
    { title: 'Runs', cat: 'hitting', type: 'R', top: 5 },
    { title: 'Walks', cat: 'hitting', type: 'BB', top: 3 },
    { title: 'ERA', cat: 'pitching', type: 'ERA', top: 5, asc: true, qualCat: 'pitching', qualType: 'IP', qualMin: 20 },
    { title: 'Wins', cat: 'pitching', type: 'W', top: 3 },
  ],
  mbb: [
    { title: 'Points / G', cat: 'basketball', type: 'PPG', top: 5 },
    { title: 'Rebounds / G', cat: 'basketball', type: 'RPG', top: 5 },
    { title: 'Assists / G', cat: 'basketball', type: 'APG', top: 5 },
    { title: 'Steals / G', cat: 'basketball', type: 'SPG', top: 3 },
    { title: 'Blocks / G', cat: 'basketball', type: 'BPG', top: 3 },
    { title: '3-Pointers Made', cat: 'basketball', type: '3PM', top: 5 },
    { title: '3PT %', cat: 'basketball', type: '3P%', top: 5, qualCat: 'basketball', qualType: '3PA', qualMin: 30 },
    { title: 'FG %', cat: 'basketball', type: 'FG%', top: 5, qualCat: 'basketball', qualType: 'FGA', qualMin: 75 },
  ],
};

const SPORT_LABEL: Record<string, string> = {
  football: 'Football',
  mbb: "Men's Basketball",
  baseball: 'Baseball',
};
const SPORT_TAG: Record<string, string> = { football: 'FB', mbb: 'MBB', baseball: 'BSB' };

const STATUS_META: Record<string, { label: string; color: string }> = {
  questionable: { label: 'Q', color: '#c98a00' },
  doubtful: { label: 'D', color: '#b4530e' },
  out: { label: 'OUT', color: Brand.loss },
};

// Football depth: individual positions roll up into a big position-group label.
const FB_GROUP: Record<string, string> = {
  QB: 'Quarterbacks',
  RB: 'Running Backs', FB: 'Running Backs',
  SE: 'Receivers', FL: 'Receivers', SLOT: 'Receivers',
  TE: 'Tight Ends',
  LT: 'Offensive Line', LG: 'Offensive Line', C: 'Offensive Line', RG: 'Offensive Line', RT: 'Offensive Line',
  DE: 'Defensive Line', DT: 'Defensive Line', NT: 'Defensive Line', BAN: 'Defensive Line',
  MIKE: 'Linebackers', OLB: 'Linebackers',
  CB1: 'Cornerbacks', CB2: 'Cornerbacks',
  FS: 'Safety', SS: 'Safety', NKL: 'Safety',
  PK: 'Specialists', P: 'Specialists', LS: 'Specialists',
};

const CATEGORY_LABEL: Record<string, string> = {
  transfer: 'Transfer',
  juco: 'JUCO',
  hs: 'High School',
  recruit: 'High School',
  eligibility: 'Out of Elig.',
  graduation: 'Out of Elig.',
  draft: 'Draft',
};

function formatDate(iso: string | null): string {
  if (!iso) return '';
  // Split the parts instead of `new Date(iso)`: a bare 'YYYY-MM-DD' parses as UTC
  // midnight, which renders as the PREVIOUS day in Eastern — the same off-by-one
  // that made the Pulse chart look a day behind.
  const [y, m, d] = iso.slice(0, 10).split('-').map(Number);
  if (!y || !m || !d) return '';
  return new Date(y, m - 1, d).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

// Roster can be viewed for last completed season (the scraped roster) or the
// upcoming season projected from Movement (returners minus departures + signees).
// Season labels differ by sport (fall vs spring vs winter academic year).
const ROSTER_SEASON_LABELS: Record<string, { projected: string; last: string }> = {
  football: { projected: '2026', last: '2025' },
  mbb: { projected: '2026-27', last: '2025-26' },
  baseball: { projected: '2027', last: '2026' },
};

// Whether the upcoming roster is still a projection. Football's 2026 team is settled now —
// camp is open and the depth chart is real — so calling it "Proj." undersells it. Basketball
// and baseball are still months out and genuinely projected.
const PROJECTED_SPORTS = new Set(['mbb', 'baseball']);

// A projected-incoming player synthesized from a roster move (no photo/jersey yet).
type RosterItem = Player & {
  incoming?: boolean;
  // Won his eligibility back and is on the team again. Distinct from `incoming`: he is not
  // arriving from anywhere, so the row must not read "from —" or borrow the newcomer label
  // (which for category 'eligibility' says "Out of Elig." — the exact opposite of the truth).
  returned?: boolean;
  departed?: boolean;
  fromSchool?: string | null;
  moveCategory?: string | null;
  note?: string | null;
  alert?: string | null;
};

function normName(n: string): string {
  return (n || '')
    .toLowerCase()
    .replace(/[.'-]/g, ' ')
    .replace(/\b(jr|sr|ii|iii|iv|v)\b/g, '')
    .replace(/\s+/g, ' ')
    .trim();
}

function playerFullName(p: Player): string {
  return `${p.first_name ?? ''} ${p.last_name ?? ''}`.trim();
}

/**
 * Copy a list, keeping the first entry per player id.
 *
 * Player id is the React key for every roster row, so a repeat is a rendering error,
 * not just a cosmetic one — React warns and may drop or duplicate the row. Two
 * roster_moves rows naming the same player resolve to the same scraped player here
 * (it happened with Jaire Rawlison, listed once by hand and once by the portal feed),
 * and a schedule glitch upstream shouldn't be able to surface as a red screen.
 */
function byId(list: RosterItem[]): RosterItem[] {
  const seen = new Set<string>();
  const out: RosterItem[] = [];
  for (const p of list) {
    if (seen.has(p.id)) continue;
    seen.add(p.id);
    out.push(p);
  }
  return out;
}

function synthFromMove(m: RosterMove, sport: string): RosterItem {
  const parts = (m.player_name || '').trim().split(/\s+/);
  const first = parts.shift() ?? '';
  return {
    id: `in_${m.id}`,
    sport_id: sport,
    season: null,
    first_name: first,
    last_name: parts.join(' '),
    jersey: null,
    position: m.position,
    height: null,
    weight: null,
    height_display: null,
    class_display: m.class_year || null,
    home_city: null,
    home_state: null,
    photo_url: null,
    incoming: true,
    fromSchool: m.other_school,
    moveCategory: m.category,
    note: m.notes,
    alert: m.alert,
  };
}

export default function TeamScreen() {
  const insets = useSafeAreaInsets();

  const [players, setPlayers] = useState<Player[]>([]);
  const [depth, setDepth] = useState<DepthEntry[]>([]);
  const [moves, setMoves] = useState<RosterMove[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  // Set when something deep-linked here — a breaking-news card sending you to the roster
  // change it's about. Without them this screen always opened on football's roster, so a
  // basketball story sent you to the wrong team and left you to find it yourself.
  const params = useLocalSearchParams<{ sport?: string; mode?: string }>();
  const linkedSport = FILTERS.find((f) => f.id === params.sport)?.id;
  const linkedMode = MODES.find((m) => m.id === params.mode)?.id;

  const [filter, setFilter] = useState<(typeof FILTERS)[number]['id']>(linkedSport ?? 'football');
  const [mode, setMode] = useState<(typeof MODES)[number]['id']>(linkedMode ?? 'roster');

  // The tab stays mounted, so arriving a second time with different params has to move the
  // controls — the initial state above only applies to the very first render.
  useEffect(() => {
    if (linkedSport) setFilter(linkedSport);
    if (linkedMode) setMode(linkedMode);
  }, [linkedSport, linkedMode]);
  const [leaderSeason, setLeaderSeason] = useState<number>(2025);
  const [rosterView, setRosterView] = useState<'projected' | 'last'>('projected');
  // One query drives every roster section on screen, so searching with the sport filter on
  // "All" looks through football, basketball and baseball at once. The roster is already
  // loaded in memory, so this is a plain array filter — no query, no loading state.
  const [rosterQuery, setRosterQuery] = useState('');
  const [depthView, setDepthView] = useState<'projected' | 'last'>('projected');
  const [selected, setSelected] = useState<Player | null>(null);

  const load = useCallback(async () => {
    const [pRes, dRes, mRes] = await Promise.all([
      // Columns are explicit so the (large) bio text doesn't ride along with every
      // roster load — the profile fetches it on open instead. Kept as one literal:
      // concatenating the string defeats the client's column-type inference.
      supabase.from('players').select('id,sport_id,season,first_name,last_name,jersey,position,height,weight,height_display,class_display,home_city,home_state,photo_url'),
      supabase.from('depth_chart').select('*'),
      supabase.from('roster_moves').select('*').order('move_date', { ascending: false }),
    ]);
    if (pRes.error && mRes.error) {
      setLoadError(true);
    } else {
      setPlayers((pRes.data ?? []) as Player[]);
      setDepth((dRes.data ?? []) as DepthEntry[]);
      setMoves((mRes.data ?? []) as RosterMove[]);
      setLoadError(false);
    }
    setLoading(false);
    setRefreshing(false);
  }, []);

  useEffect(() => {
    load();
  }, [load]);
  useForegroundRefresh(load);

  if (loading) {
    return (
      <View style={{ flex: 1, backgroundColor: c.bg, paddingTop: insets.top + 10 }}>
        <View style={styles.screenHeader}>
          <Text style={styles.screenTitle}>Team</Text>
        </View>
        <View style={{ paddingHorizontal: 20, marginTop: 10 }}>
          <SkeletonList count={8}>
            <ListRowSkeleton />
          </SkeletonList>
        </View>
      </View>
    );
  }

  if (loadError && players.length === 0 && moves.length === 0) {
    return (
      <View style={{ flex: 1, backgroundColor: c.bg, paddingTop: insets.top + 10 }}>
        <View style={styles.screenHeader}>
          <Text style={styles.screenTitle}>Team</Text>
        </View>
        <OfflineNotice onRetry={() => { setLoading(true); load(); }} />
      </View>
    );
  }

  const sports = [filter];
  const visibleMoves = moves.filter((m) => m.sport_id === filter);
  const leaderSeasonList = LEADER_SEASONS_BY_SPORT[filter] ?? [];
  const effLeaderSeason = leaderSeasonList.includes(leaderSeason) ? leaderSeason : leaderSeasonList[0];

  return (
    <View style={{ flex: 1, backgroundColor: c.bg, paddingTop: insets.top + 10 }}>
      <View style={styles.screenHeader}>
        <Text style={styles.screenTitle}>Team</Text>
      </View>

      {/* Roster / Depth Chart / Movement / Leaders segmented control */}
      <View style={styles.segment}>
        {MODES.map((m) => {
          const active = mode === m.id;
          return (
            <Pressable
              key={m.id}
              onPress={() => setMode(m.id)}
              style={[styles.segBtn, active ? { backgroundColor: Brand.gold } : { backgroundColor: c.card, borderWidth: 1, borderColor: c.border }]}>
              <Text style={[styles.segText, { color: active ? Brand.onGold : c.textSecondary }]}>
                {m.label}
              </Text>
            </Pressable>
          );
        })}
      </View>

      {mode === 'leaders' ? (
        <>
          <View style={styles.filterRow}>
            {FILTERS.map((f) => {
              const active = filter === f.id;
              return (
                <Pressable
                  key={f.id}
                  onPress={() => setFilter(f.id)}
                  style={[styles.chip, { backgroundColor: active ? Brand.gold : c.card, borderColor: active ? Brand.gold : c.border }]}>
                  <Text style={[styles.chipText, { color: active ? Brand.onGold : c.textSecondary }]}>{f.label}</Text>
                </Pressable>
              );
            })}
          </View>
          {leaderSeasonList.length > 1 && (
            <View style={styles.filterRow}>
              {leaderSeasonList.map((yr) => {
                const active = effLeaderSeason === yr;
                return (
                  <Pressable
                    key={yr}
                    onPress={() => setLeaderSeason(yr)}
                    style={[styles.chip, { backgroundColor: active ? Brand.gold : c.card, borderColor: active ? Brand.gold : c.border }]}>
                    <Text style={[styles.chipText, { color: active ? Brand.onGold : c.textSecondary }]}>{yr} Season</Text>
                  </Pressable>
                );
              })}
            </View>
          )}
        </>
      ) : (
        <>
          <View style={styles.filterRow}>
            {FILTERS.map((f) => {
              const active = filter === f.id;
              return (
                <Pressable
                  key={f.id}
                  onPress={() => setFilter(f.id)}
                  style={[styles.chip, { backgroundColor: active ? Brand.gold : c.card, borderColor: active ? Brand.gold : c.border }]}>
                  <Text style={[styles.chipText, { color: active ? Brand.onGold : c.textSecondary }]}>{f.label}</Text>
                </Pressable>
              );
            })}
          </View>
          {mode === 'roster' && (
            <View style={styles.filterRow}>
              {(['projected', 'last'] as const).map((v) => {
                const active = rosterView === v;
                const label = ROSTER_SEASON_LABELS[filter]?.[v] ?? '';
                return (
                  <Pressable
                    key={v}
                    onPress={() => setRosterView(v)}
                    style={[styles.chip, { backgroundColor: active ? Brand.gold : c.card, borderColor: active ? Brand.gold : c.border }]}>
                    <Text style={[styles.chipText, { color: active ? Brand.onGold : c.textSecondary }]}>
                      {label}
                      {v === 'projected' && PROJECTED_SPORTS.has(filter) ? ' · Proj.' : ''}
                    </Text>
                  </Pressable>
                );
              })}
            </View>
          )}
          {mode === 'roster' && (
            <View style={[styles.searchWrap, { backgroundColor: c.card, borderColor: c.border }]}>
              <Ionicons name="search" size={15} color={c.textMuted} />
              <TextInput
                value={rosterQuery}
                onChangeText={setRosterQuery}
                placeholder="Search name, number, or position"
                placeholderTextColor={c.textMuted}
                autoCorrect={false}
                autoCapitalize="none"
                returnKeyType="search"
                clearButtonMode="never"
                style={[styles.searchInput, { color: c.text }]}
              />
              {rosterQuery.length > 0 && (
                // Explicit clear button rather than iOS's built-in one, so Android gets it too.
                <Pressable onPress={() => setRosterQuery('')} hitSlop={10}>
                  <Ionicons name="close-circle" size={16} color={c.textMuted} />
                </Pressable>
              )}
            </View>
          )}
          {mode === 'depth' && filter === 'baseball' && (
            <View style={styles.filterRow}>
              {(['projected', 'last'] as const).map((v) => {
                const active = depthView === v;
                const label = ROSTER_SEASON_LABELS.baseball[v];
                return (
                  <Pressable
                    key={v}
                    onPress={() => setDepthView(v)}
                    style={[styles.chip, { backgroundColor: active ? Brand.gold : c.card, borderColor: active ? Brand.gold : c.border }]}>
                    <Text style={[styles.chipText, { color: active ? Brand.onGold : c.textSecondary }]}>
                      {label}
                      {v === 'projected' && PROJECTED_SPORTS.has(filter) ? ' · Proj.' : ''}
                    </Text>
                  </Pressable>
                );
              })}
            </View>
          )}
        </>
      )}

      <ScrollView
        contentContainerStyle={styles.content}
        refreshControl={
          <RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} tintColor={Brand.gold} />
        }>
        {mode === 'roster' &&
          sports.map((sp) => (
            <RosterSection
              key={sp}
              sport={sp}
              players={players.filter((p) => p.sport_id === sp)}
              moves={moves.filter((m) => m.sport_id === sp)}
              projected={rosterView === 'projected'}
              query={rosterQuery}
              c={c}
              onPick={setSelected}
              showHeader={false}
            />
          ))}

        {mode === 'depth' &&
          sports.map((sp) => {
            let entries = depth.filter((d) => d.sport_id === sp);
            if (sp === 'baseball') {
              const yr = depthView === 'projected' ? 2027 : 2026;
              entries = entries.filter((d) => d.season === yr);
            }
            return <DepthChartSection key={sp} sport={sp} entries={entries} c={c} showHeader={false} />;
          })}

        {mode === 'movement' && <MovementView moves={visibleMoves} c={c} showTag={false} />}

        {mode === 'leaders' && <LeadersView sport={filter} season={effLeaderSeason} c={c} />}
      </ScrollView>

      <PlayerProfile player={selected} onClose={() => setSelected(null)} />
    </View>
  );
}

/* ---------------- Roster ---------------- */

function RosterSection({
  sport,
  players,
  moves,
  projected,
  query,
  c,
  onPick,
  showHeader,
}: {
  sport: string;
  players: Player[];
  moves: RosterMove[];
  projected: boolean;
  query: string;
  c: ReturnType<typeof surfaces>;
  onPick: (p: Player) => void;
  showHeader: boolean;
}) {
  const projLabel = ROSTER_SEASON_LABELS[sport]?.projected ?? '';
  // "Projected 2026" reads as guesswork for a football team that has already reported to camp.
  const projWord = PROJECTED_SPORTS.has(sport) ? 'Projected ' : '';
  const lastLabel = ROSTER_SEASON_LABELS[sport]?.last ?? '';
  // The scraped roster is already the UPCOMING season, so a TRUE freshman on it is a
  // brand-new arrival (this year's HS class), not a last-year player. Redshirt freshmen
  // (R-Fr.) were on last year's team. After stripping spaces/dots/hyphens a true freshman
  // starts with "fr" while "R-Fr." becomes "rfr" — so startsWith('fr') separates them.
  const isNewFreshman = (p: Player) => {
    const cd = (p.class_display || '').toLowerCase().replace(/[\s.\-]/g, '');
    return cd.startsWith('fr');
  };
  const inMoves = moves.filter((m) => m.direction === 'in');
  // An eligibility return is NOT a newcomer. The player was on last year's team and won his
  // year back, so he belongs with the returners — listing him under Incoming reads as an
  // outside addition, and with no previous school the card would say "from —". Separated
  // here so both the roster split below and `incomingNames` treat him as a returner.
  const isEligibilityReturn = (m: RosterMove) => m.category === 'eligibility';
  const returnMoves = inMoves.filter(isEligibilityReturn);
  const newcomerMoves = inMoves.filter((m) => !isEligibilityReturn(m));
  const incomingNames = new Set(newcomerMoves.map((m) => normName(m.player_name)));
  let returning: Player[] = players;
  let incoming: RosterItem[] = [];
  let departed: RosterItem[] = [];
  if (projected) {
    const departedSet = new Set(
      // 'draft-pending' = drafted but decision not final — still on the roster, not departed.
      moves.filter((m) => m.direction === 'out' && m.category !== 'draft-pending').map((m) => normName(m.player_name)),
    );
    // Returning = current roster minus departures, minus curated incoming, minus this
    // year's true freshmen (they belong in Incoming).
    returning = players.filter((p) => {
      const k = normName(playerFullName(p));
      return !departedSet.has(k) && !incomingNames.has(k) && !isNewFreshman(p);
    });
    // Incoming: curated moves (reuse the scraped record for photo/jersey when it
    // exists, else synth) PLUS the true-freshman class that isn't already curated.
    const rosterByName = new Map(players.map((p) => [normName(playerFullName(p)), p]));
    // Eligibility returns rejoin the returning list. The official roster scrape often lags a
    // court ruling by weeks — Brenen Lorient was reported returning on 2026-08-12 and was
    // still absent from wvusports.com — so synthesize anyone it hasn't picked up yet, and
    // skip those it has to avoid listing the same player twice.
    returning = [
      ...returning,
      ...(returnMoves
        .filter((m) => !rosterByName.has(normName(m.player_name)))
        .map((m) => ({ ...synthFromMove(m, sport), incoming: false, returned: true,
                       fromSchool: null })) as Player[]),
    ];
    const curatedIncoming: RosterItem[] = newcomerMoves.map((m) => {
      const rp = rosterByName.get(normName(m.player_name));
      return rp
        ? { ...rp, incoming: true, fromSchool: m.other_school, moveCategory: m.category, note: m.notes, alert: m.alert }
        : synthFromMove(m, sport);
    });
    const freshmenIncoming: RosterItem[] = players
      .filter((p) => {
        const k = normName(playerFullName(p));
        return isNewFreshman(p) && !departedSet.has(k) && !incomingNames.has(k);
      })
      .map((p) => ({ ...p, incoming: true, fromSchool: null, moveCategory: 'hs', note: null, alert: null }));
    incoming = [...curatedIncoming, ...freshmenIncoming];
  } else {
    // LAST season's team: the scrape is the upcoming roster, so strip this year's
    // newcomers (incoming transfers + true freshmen), then add back the players who
    // have since left (out-moves) — together that's who suited up last season.
    returning = players.filter((p) => {
      const k = normName(playerFullName(p));
      return !incomingNames.has(k) && !isNewFreshman(p);
    });
    const returningNames = new Set(returning.map((p) => normName(playerFullName(p))));
    departed = moves
      .filter((m) => m.direction === 'out' && m.category !== 'draft-pending' && !returningNames.has(normName(m.player_name)))
      .map((m) => ({ ...synthFromMove(m, sport), incoming: false, departed: true, moveCategory: m.category }));
  }
  // Football's scraped roster hands out jersey numbers to the incoming class too, so
  // returners and newcomers belong in one numbered list — the way a program prints it,
  // and the only way a late arrival is findable without knowing to scroll to a section.
  // Basketball and baseball newcomers are mostly synthesized from moves with no number
  // yet, so a jersey sort would strand them all at the bottom; those keep the split.
  // One numbered list rather than Returning/Incoming sections. Football reads best by jersey
  // (the scrape numbers newcomers too); basketball newcomers are mostly synthesized from moves
  // with no number yet, so a jersey sort would strand them all at the bottom — sort by name.
  const combineIntoOne = projected && (sport === 'football' || sport === 'mbb');
  // Jersey numbers repeat in football (one offense, one defense), so name breaks the tie.
  const byJersey = (a: RosterItem, b: RosterItem) =>
    (a.jersey ?? 999) - (b.jersey ?? 999) || playerFullName(a).localeCompare(playerFullName(b));

  // Matches a name, a jersey number (with or without the "#"), a position, or a class.
  // Substring rather than prefix so "brown" finds "Kevin Brown" and "qb" finds every
  // quarterback; typing "41" finds #41 without competing with players born in '41.
  const needle = query.trim().toLowerCase();
  const matches = (p: RosterItem) =>
    !needle ||
    [
      playerFullName(p),
      p.position ?? '',
      p.class_display ?? '',
      p.jersey != null ? `#${p.jersey}` : '',
    ]
      .join(' ')
      .toLowerCase()
      .includes(needle);

  const sorted = byId(returning).filter(matches).sort((a, b) => (a.jersey ?? 999) - (b.jersey ?? 999));
  const incSorted = byId(incoming).filter(matches).sort((a, b) => playerFullName(a).localeCompare(playerFullName(b)));
  const depSorted = byId(departed).filter(matches).sort((a, b) => playerFullName(a).localeCompare(playerFullName(b)));
  // Numbered order for both, the way a program prints a roster. Anyone without a number yet
  // (a newcomer synthesized from a move, before the official roster assigns one) falls to the
  // bottom via the 999 fallback in byJersey, with name breaking ties.
  const combined: RosterItem[] = combineIntoOne
    ? byId([...returning, ...incoming]).filter(matches).sort(byJersey)
    : [];
  const visibleCount = combineIntoOne
    ? combined.length
    : sorted.length + incSorted.length + depSorted.length;

  return (
    <>
      {showHeader && <SectionTitle text={SPORT_LABEL[sport]} color={c.text} />}
      {visibleCount === 0 ? (
        <Text style={[styles.empty, { color: c.textSecondary }]}>
          {/* Naming the sport matters while searching: with the filter on "All" this renders
              once per sport, so "no match" needs to say which roster came up empty. */}
          {needle
            ? `${SPORT_LABEL[sport]} — no players match “${query.trim()}”.`
            : sport === 'baseball'
              ? 'Baseball roster isn’t available yet.'
              : 'No roster loaded.'}
        </Text>
      ) : (
        <>
          <Text style={[styles.rosterNote, { color: c.textSecondary }]}>
            {needle
              ? `${visibleCount} ${visibleCount === 1 ? 'match' : 'matches'} in ${SPORT_LABEL[sport]}`
              : combineIntoOne
                ? `${projWord}${projLabel} · ${combined.length} players · ${incSorted.length} new`
                : projected
                  ? `${projWord}${projLabel} · ${sorted.length} returning + ${incSorted.length} incoming`
                  : `${lastLabel} roster · ${sorted.length} returning + ${depSorted.length} departed`}
          </Text>
          {(combineIntoOne ? combined : sorted).map((p) => (
            <RosterRow key={p.id} player={p} c={c} onPick={onPick} />
          ))}
          {!combineIntoOne && incSorted.length > 0 && (
            <>
              <Text style={[styles.incomingLabel, { color: Brand.gold }]}>INCOMING FOR {projLabel}</Text>
              {incSorted.map((p) => (
                <RosterRow key={p.id} player={p} c={c} onPick={onPick} />
              ))}
            </>
          )}
          {depSorted.length > 0 && (
            <>
              <Text style={[styles.incomingLabel, { color: Brand.loss }]}>DEPARTED AFTER {lastLabel}</Text>
              {depSorted.map((p) => (
                <RosterRow key={p.id} player={p} c={c} onPick={onPick} />
              ))}
            </>
          )}
        </>
      )}
    </>
  );
}

function RosterRow({ player, c, onPick }: { player: RosterItem; c: ReturnType<typeof surfaces>; onPick: (p: Player) => void }) {
  const name = `${player.first_name ?? ''} ${player.last_name ?? ''}`.trim();
  const meta = [player.position, player.class_display].filter(Boolean).join(' · ');
  return (
    <Pressable
      onPress={() => onPick(player)}
      style={({ pressed }) => [styles.rosterRow, { backgroundColor: c.card, borderColor: c.border, opacity: pressed ? 0.7 : 1 }]}>
      {player.photo_url ? (
        <Image source={{ uri: player.photo_url }} style={styles.avatar} />
      ) : (
        <View style={[styles.avatar, styles.avatarFallback, { backgroundColor: player.incoming ? Brand.win : Brand.blue }]}>
          <Text style={styles.avatarText}>{(player.first_name?.[0] ?? '') + (player.last_name?.[0] ?? '')}</Text>
        </View>
      )}
      <Text style={[styles.jersey, { color: c.textSecondary }]}>{player.jersey != null ? `#${player.jersey}` : ''}</Text>
      <View style={{ flex: 1 }}>
        <Text style={[styles.playerName, { color: c.text }]} numberOfLines={1}>{name}</Text>
        <Text style={[styles.playerMeta, { color: c.textSecondary }]} numberOfLines={1}>
          {meta}
          {player.incoming && player.fromSchool ? `  ·  from ${player.fromSchool}` : ''}
        </Text>
        {player.alert ? (
          <View style={styles.alertPill}>
            <Ionicons name="warning-outline" size={11} color={Brand.gold} />
            <Text style={styles.alertText} numberOfLines={3}>{player.alert}</Text>
          </View>
        ) : null}
      </View>
      {player.returned ? (
        <View style={[styles.incTag, { borderColor: Brand.gold }]}>
          <Text style={[styles.incTagText, { color: Brand.gold }]}>Returning</Text>
        </View>
      ) : player.incoming ? (
        <View style={[styles.incTag, { borderColor: Brand.win }]}>
          <Text style={[styles.incTagText, { color: Brand.win }]}>
            {(player.moveCategory && CATEGORY_LABEL[player.moveCategory]) || 'New'}
          </Text>
        </View>
      ) : player.departed ? (
        <View style={[styles.incTag, { borderColor: Brand.loss }]}>
          <Text style={[styles.incTagText, { color: Brand.loss }]}>
            {(player.moveCategory && CATEGORY_LABEL[player.moveCategory]) || 'Left'}
          </Text>
        </View>
      ) : (
        <Text style={{ color: c.textSecondary }}>›</Text>
      )}
    </Pressable>
  );
}

/* ---------------- Depth Chart ---------------- */

function DepthChartSection({
  sport,
  entries,
  c,
  showHeader,
}: {
  sport: string;
  entries: DepthEntry[];
  c: ReturnType<typeof surfaces>;
  showHeader: boolean;
}) {
  if (entries.length === 0) {
    return (
      <>
        {showHeader && <SectionTitle text={SPORT_LABEL[sport]} color={c.text} />}
        <Text style={[styles.empty, { color: c.textSecondary }]}>
          {sport === 'football' ? 'Depth chart not loaded yet.' : 'Depth chart not available yet.'}
        </Text>
      </>
    );
  }

  // Group by unit → position, preserving pos_order.
  const byUnit = new Map<string, DepthEntry[]>();
  for (const e of entries) {
    const u = e.unit ?? '';
    if (!byUnit.has(u)) byUnit.set(u, []);
    byUnit.get(u)!.push(e);
  }
  const minOrder = (arr: DepthEntry[]) => Math.min(...arr.map((x) => x.pos_order ?? 0));
  const units = [...byUnit.entries()].sort((a, b) => minOrder(a[1]) - minOrder(b[1]));

  return (
    <>
      {showHeader && <SectionTitle text={SPORT_LABEL[sport]} color={c.text} />}
      <Text style={[styles.depthNote, { color: c.textSecondary }]}>
        Projected lineup · updates with injuries & roster moves
      </Text>
      {units.map(([unit, list]) => {
        // Group by pos_order so each slot is its own card. Same-order entries
        // stack (e.g. football 1st/2nd string); distinct orders render separately
        // (each hitter, and now each pitcher, gets an individual card).
        const slots = new Map<number, DepthEntry[]>();
        for (const e of list) {
          const key = e.pos_order ?? 0;
          if (!slots.has(key)) slots.set(key, []);
          slots.get(key)!.push(e);
        }
        const slotList = [...slots.entries()].sort((a, b) => a[0] - b[0]);
        // The big position-group headers (Offensive Line, Specialists, …) are a
        // FOOTBALL-only concept. Basketball/baseball positions (C, P) must not get
        // filed under them, so only football rolls positions up into groups.
        const isFootball = sport === 'football';
        // Football keeps its big Offense/Defense/Special Teams unit banners.
        // Other sports: show the unit as a small section label, and drop the
        // redundant "Projected Lineup" one (the italic note above already says it).
        const showUnit = !!unit && (isFootball || unit.toLowerCase() !== 'projected lineup');
        let lastGroup: string | undefined;
        return (
          <View key={unit || 'x'}>
            {showUnit ? (
              <Text style={isFootball ? styles.unitLabel : styles.unitLabelSm}>{unit.toUpperCase()}</Text>
            ) : null}
            {slotList.map(([order, ps]) => {
              const group = isFootball ? FB_GROUP[ps[0].position] : undefined;
              const header = group && group !== lastGroup;
              if (group) lastGroup = group;
              return (
                <View key={order}>
                  {header ? <Text style={styles.groupLabel}>{group}</Text> : null}
                  <DepthPositionCard position={ps[0].position} players={ps} c={c} />
                </View>
              );
            })}
          </View>
        );
      })}
    </>
  );
}

function DepthPositionCard({
  position,
  players,
  c,
}: {
  position: string;
  players: DepthEntry[];
  c: ReturnType<typeof surfaces>;
}) {
  const ordered = [...players].sort((a, b) => a.rank - b.rank);
  const starterOut = ordered.length > 0 && (ordered[0].status === 'out' || ordered[0].status === 'doubtful');
  const projIdx = ordered.findIndex((p) => p.status !== 'out' && p.status !== 'doubtful');

  return (
    <View style={[styles.depthCard, { backgroundColor: c.card, borderColor: c.border }]}>
      <Text style={styles.depthPos}>{position}</Text>
      <View style={{ flex: 1 }}>
        {ordered.map((p, i) => {
          const isProj = starterOut && i === projIdx;
          const meta = p.status && p.status !== 'active' ? STATUS_META[p.status] : null;
          const struck = p.status === 'out';
          const starter = i === 0; // the #1 spot — gold like the design
          return (
            <View key={p.id} style={styles.depthPlayerRow}>
              <View style={[styles.depthRank, starter ? { backgroundColor: Brand.gold } : { backgroundColor: c.surface2 }]}>
                <Text style={[styles.depthRankText, { color: starter ? Brand.onGold : c.textSecondary }]}>{i + 1}</Text>
              </View>
              <View style={{ flex: 1 }}>
                <Text
                  style={[
                    styles.depthName,
                    { color: struck ? c.textSecondary : c.text },
                    struck && { textDecorationLine: 'line-through' },
                    isProj && { color: Brand.gold, fontWeight: '800' },
                  ]}
                  numberOfLines={1}>
                  {p.player_name}
                  {p.class_year ? (
                    <Text style={{ color: c.textSecondary, fontWeight: '400' }}> · {p.class_year}</Text>
                  ) : null}
                </Text>
                {p.note ? (
                  <Text style={[styles.depthNoteLine, { color: c.textSecondary }]} numberOfLines={2}>
                    {p.note}
                  </Text>
                ) : null}
                {p.alert ? (
                  <View style={styles.alertPill}>
                    <Ionicons name="warning-outline" size={11} color={Brand.gold} />
                    <Text style={styles.alertText} numberOfLines={3}>{p.alert}</Text>
                  </View>
                ) : null}
              </View>
              {isProj && <Text style={styles.projTag}>proj. start</Text>}
              {meta && (
                <View style={[styles.statusBadge, { backgroundColor: meta.color }]}>
                  <Text style={styles.statusText}>{meta.label}</Text>
                </View>
              )}
            </View>
          );
        })}
      </View>
    </View>
  );
}

/* ---------------- Movement ---------------- */

// What kind of move this is, phrased for the card badge. Movement is ordered by DATE, not
// grouped by type, so this label is the only thing telling you what happened — it has to be
// specific and directional on its own ("Transfer Out", not "Transfer").
function moveLabel(m: RosterMove): string {
  const cat = m.category ?? '';
  if (m.direction === 'in') {
    if (cat === 'transfer') return 'Transfer In';
    if (cat === 'juco') return 'JUCO Signee';
    if (cat === 'hs' || cat === 'recruit') return 'HS Signee';
    // A player whose eligibility came BACK (court ruling, waiver) and who is on the
    // roster again — the mirror of the 'out' case below, not a generic addition.
    if (cat === 'eligibility') return 'Eligibility Return';
    return 'Addition';
  }
  if (cat === 'transfer') return 'Transfer Out';
  if (cat === 'draft') return 'Drafted';
  if (cat === 'draft-pending') return 'Draft Pending';
  if (cat === 'eligibility' || cat === 'graduation') return 'Out of Eligibility';
  return 'Departure';
}

function MovementView({ moves, c, showTag }: { moves: RosterMove[]; c: ReturnType<typeof surfaces>; showTag: boolean }) {
  // Newest first. Grouping by category buried the news: a signing that happened today sat
  // below months of older moves just because it was a JUCO one. ISO 'YYYY-MM-DD' sorts
  // lexicographically the same as chronologically, so no Date parsing (and no timezone risk).
  const sorted = [...moves].sort((a, b) => {
    const da = a.move_date ?? '';
    const db = b.move_date ?? '';
    if (da !== db) return db.localeCompare(da);
    return (a.player_name ?? '').localeCompare(b.player_name ?? '');
  });
  if (sorted.length === 0) {
    return <Text style={[styles.empty, { color: c.textSecondary }]}>No moves logged yet.</Text>;
  }
  return (
    <>
      <View style={styles.moveSectionRow}>
        <Text style={styles.sectionTitle}>Most recent first</Text>
        <View style={[styles.countPill, { backgroundColor: c.surface2 }]}>
          <Text style={[styles.countText, { color: c.textSecondary }]}>{sorted.length}</Text>
        </View>
      </View>
      {sorted.map((m) => (
        <MoveCard key={m.id} move={m} c={c} showTag={showTag} />
      ))}
    </>
  );
}

function MoveCard({
  move,
  c,
  showTag,
}: {
  move: RosterMove;
  c: ReturnType<typeof surfaces>;
  showTag: boolean;
}) {
  const isIn = move.direction === 'in';
  const accent = isIn ? Brand.win : Brand.loss;
  const body = (
    <View style={[styles.moveCard, { backgroundColor: c.card, borderColor: c.border, borderLeftColor: accent }]}>
      <View style={styles.cardHead}>
        {/* One chip, not two: the arrow carries direction by color and the text says
            exactly what happened. Since the list is date-ordered rather than grouped,
            this badge is what tells you a card is a signing vs. a departure. */}
        <View style={[styles.dirBadge, { backgroundColor: isIn ? Brand.greenTint : Brand.redTint }]}>
          <Ionicons name={isIn ? 'arrow-down' : 'arrow-up'} size={11} color={accent} />
          <Text style={[styles.dirText, { color: accent }]}>{moveLabel(move)}</Text>
        </View>
        {showTag && move.sport_id && SPORT_TAG[move.sport_id] && (
          <View style={styles.tag}>
            <Text style={styles.tagText}>{SPORT_TAG[move.sport_id]}</Text>
          </View>
        )}
        <Text style={[styles.status, { color: c.textMuted }]}>
          {move.status ? `${move.status} · ` : ''}
          <Text style={styles.moveDate}>{formatDate(move.move_date)}</Text>
        </Text>
      </View>

      <Text style={[styles.player, { color: c.text }]}>
        {move.player_name}
        {move.position ? <Text style={{ color: c.textSecondary }}> · {move.position}</Text> : null}
        {move.class_year ? <Text style={{ color: c.textSecondary }}> · {move.class_year}</Text> : null}
      </Text>
      {move.other_school ? (
        <Text style={[styles.school, { color: c.text }]}>
          <Text style={{ color: accent, fontWeight: '900' }}>{isIn ? '← from ' : '→ to '}</Text>
          {move.other_school}
        </Text>
      ) : move.direction === 'out' && move.category === 'transfer' ? (
        <Text style={[styles.school, { color: c.textSecondary }]}>→ entered the portal</Text>
      ) : null}
      {move.notes ? <Text style={[styles.notes, { color: c.textSecondary }]}>{move.notes}</Text> : null}
      {move.source_name ? (
        <Text style={[styles.source, { color: c.textSecondary }]}>
          {move.source_url ? 'Source: ' : ''}
          {move.source_name}
          {move.source_url ? ' ↗' : ''}
        </Text>
      ) : null}
    </View>
  );

  if (move.source_url) {
    return <Pressable onPress={() => WebBrowser.openBrowserAsync(move.source_url!)}>{body}</Pressable>;
  }
  return body;
}

/* ---------------- Leaders ---------------- */

type StatLine = { player_id: string; player_name: string | null; category: string; stat_type: string; stat: string | null };
type LeaderEntry = { name: string; display: string; val: number };

function LeadersView({ sport, season, c }: { sport: string; season: number | undefined; c: ReturnType<typeof surfaces> }) {
  const [rows, setRows] = useState<StatLine[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (season == null) {
      setRows([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    supabase
      .from('player_stats')
      .select('player_id,player_name,category,stat_type,stat')
      .eq('sport_id', sport)
      .eq('team', 'West Virginia') // WVU leaders only — never a transfer's old-school stats
      .eq('season', season)
      .then(({ data }) => {
        setRows((data ?? []) as StatLine[]);
        setLoading(false);
      });
  }, [sport, season]);

  if (season == null) {
    return <Text style={[styles.empty, { color: c.textSecondary }]}>Leaders coming soon for this sport.</Text>;
  }
  if (loading) {
    return (
      <View style={{ marginTop: 16, gap: 8 }}>
        <SkeletonList count={6}>
          <ListRowSkeleton />
        </SkeletonList>
      </View>
    );
  }

  // One value map per player, so a board can gate a rate stat by a counting stat.
  const byPlayer = new Map<string, { name: string; vals: Map<string, { num: number; raw: string }> }>();
  for (const r of rows) {
    if (r.stat == null) continue;
    const num = parseFloat(r.stat);
    if (Number.isNaN(num)) continue;
    if (!byPlayer.has(r.player_id)) byPlayer.set(r.player_id, { name: r.player_name ?? '—', vals: new Map() });
    byPlayer.get(r.player_id)!.vals.set(`${r.category}|${r.stat_type}`, { num, raw: r.stat });
  }

  const board = (b: Board): LeaderEntry[] => {
    const out: LeaderEntry[] = [];
    for (const p of byPlayer.values()) {
      const main = p.vals.get(`${b.cat}|${b.type}`);
      if (!main) continue;
      if (b.qualCat && b.qualType) {
        const q = p.vals.get(`${b.qualCat}|${b.qualType}`);
        if (!q || q.num < (b.qualMin ?? 0)) continue;
      }
      if (!b.asc && main.num <= 0) continue; // drop zeros on counting boards
      const display = b.type === 'AVG' ? main.raw.replace(/^0(?=\.)/, '') : main.raw;
      out.push({ name: p.name, display, val: main.num });
    }
    out.sort((x, y) => (b.asc ? x.val - y.val : y.val - x.val));
    return out.slice(0, b.top);
  };

  const boards = (LEADERBOARDS_BY_SPORT[sport] ?? [])
    .map((b) => ({ b, list: board(b) }))
    .filter((x) => x.list.length > 0);

  if (boards.length === 0) {
    return (
      <Text style={[styles.empty, { color: c.textSecondary }]}>No stats for the {season} season yet.</Text>
    );
  }

  return (
    <>
      <Text style={[styles.depthNote, { color: c.textSecondary }]}>
        {season} team leaders · West Virginia {SPORT_LABEL[sport] ?? ''}
      </Text>
      {boards.map(({ b, list }) => (
        <LeaderCard key={b.title} title={b.title} rows={list} c={c} />
      ))}
    </>
  );
}

function LeaderCard({
  title,
  rows,
  c,
}: {
  title: string;
  rows: LeaderEntry[];
  c: ReturnType<typeof surfaces>;
}) {
  return (
    <View style={[styles.leaderCard, { backgroundColor: c.card, borderColor: c.border }]}>
      <Text style={[styles.leaderTitle, { color: c.text }]}>{title}</Text>
      {rows.map((r, i) => (
        <View key={r.name + i} style={styles.leaderRow}>
          <Text style={[styles.leaderRank, { color: i === 0 ? Brand.gold : c.textSecondary }]}>{i + 1}</Text>
          <Text style={[styles.leaderName, { color: c.text }]} numberOfLines={1}>
            {r.name}
          </Text>
          <Text style={[styles.leaderVal, { color: i === 0 ? Brand.gold : c.text }]}>{r.display}</Text>
        </View>
      ))}
    </View>
  );
}

/* ---------------- Shared ---------------- */

function SectionTitle({ text, color }: { text: string; color: string }) {
  return (
    <View style={styles.sectionRow}>
      <View style={styles.goldBar} />
      <Text style={[styles.sectionTitle, { color }]}>{text}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  center: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  content: { paddingHorizontal: 20, paddingBottom: 40 },
  screenHeader: { paddingHorizontal: 20, paddingBottom: 8 },
  screenTitle: { fontFamily: Font.display, fontSize: 24, color: c.text, letterSpacing: -0.4 },
  segment: { flexDirection: 'row', marginHorizontal: 20, marginBottom: 4, gap: 6 },
  segBtn: { flex: 1, paddingVertical: 7, borderRadius: 10, alignItems: 'center' },
  segText: { fontSize: 12, fontFamily: Font.bodyBold },
  filterRow: { flexDirection: 'row', gap: 8, paddingHorizontal: 20, paddingTop: 8, paddingBottom: 4, flexWrap: 'wrap' },
  searchWrap: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    marginHorizontal: 20,
    marginTop: 8,
    paddingHorizontal: 12,
    height: 38,
    borderRadius: 10,
    borderWidth: 1,
  },
  // No vertical padding: on Android a TextInput adds its own, which would push the text
  // off-center inside the fixed-height row above.
  searchInput: { flex: 1, fontFamily: Font.body, fontSize: 14, padding: 0 },
  chip: { paddingHorizontal: 14, paddingVertical: 6, borderRadius: 999, borderWidth: 1 },
  chipText: { fontSize: 12, fontFamily: Font.bodySemi },
  sectionRow: { flexDirection: 'row', alignItems: 'center', marginTop: 16, marginBottom: 8 },
  goldBar: { width: 3, height: 14, borderRadius: 2, backgroundColor: Brand.gold, marginRight: 8 },
  sectionTitle: { fontSize: 12, fontFamily: Font.bodyBold, letterSpacing: 1.4, color: Brand.gold, textTransform: 'uppercase' },
  empty: { fontSize: 14, paddingVertical: 12, color: c.textSecondary, fontFamily: Font.body },
  // roster
  rosterRow: { flexDirection: 'row', alignItems: 'center', gap: 12, borderWidth: 1, borderRadius: 14, padding: 12, marginBottom: 8 },
  avatar: { width: 44, height: 44, borderRadius: 22, backgroundColor: c.surface2 },
  avatarFallback: { alignItems: 'center', justifyContent: 'center' },
  avatarText: { color: c.textSecondary, fontFamily: Font.display, fontSize: 13 },
  jersey: { fontSize: 14, fontFamily: Font.display, width: 34 },
  playerName: { fontSize: 14, fontFamily: Font.displaySemi },
  playerMeta: { fontSize: 12, marginTop: 2, fontFamily: Font.body },
  rosterNote: { fontSize: 11, fontStyle: 'italic', marginTop: 12, marginBottom: 8, color: c.textMuted, fontFamily: Font.body },
  incomingLabel: { fontSize: 11, fontFamily: Font.bodyBold, letterSpacing: 1.4, marginTop: 16, marginBottom: 8 },
  incTag: { borderRadius: 6, paddingHorizontal: 7, paddingVertical: 3 },
  incTagText: { fontSize: 10, fontFamily: Font.bodyBold },
  // depth chart
  depthNote: { fontSize: 11, fontStyle: 'italic', marginTop: 10, marginBottom: 6, color: c.textMuted, fontFamily: Font.body },
  unitLabel: { color: Brand.gold, fontSize: 21, fontFamily: Font.display, letterSpacing: 0.3, marginTop: 24, marginBottom: 4 },
  unitLabelSm: { color: Brand.gold, fontSize: 13, fontFamily: Font.bodyBold, letterSpacing: 1.4, marginTop: 20, marginBottom: 6 },
  groupLabel: { fontFamily: Font.display, fontSize: 16, color: c.text, letterSpacing: -0.2, marginTop: 16, marginBottom: 8 },
  depthCard: { flexDirection: 'row', alignItems: 'flex-start', gap: 14, borderWidth: 1, borderRadius: 16, padding: 14, marginBottom: 8 },
  depthPos: { width: 54, fontSize: 13, fontFamily: Font.black, color: Brand.gold, paddingTop: 3 },
  depthPlayerRow: { flexDirection: 'row', alignItems: 'center', gap: 10, paddingVertical: 5 },
  depthRank: { width: 20, height: 20, borderRadius: 6, alignItems: 'center', justifyContent: 'center' },
  depthRankText: { fontSize: 12, fontFamily: Font.bodyBold },
  depthName: { fontSize: 14, fontFamily: Font.bodySemi },
  depthNoteLine: { fontSize: 11, marginTop: 2, lineHeight: 15, fontFamily: Font.body },
  alertPill: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 5,
    marginTop: 6,
    backgroundColor: Brand.goldTint,
    borderWidth: 1,
    borderColor: Brand.goldBorder,
    borderRadius: 8,
    paddingHorizontal: 8,
    paddingVertical: 5,
  },
  alertText: { flex: 1, fontSize: 11, lineHeight: 15, color: Brand.gold, fontFamily: Font.bodySemi },
  projTag: { color: Brand.gold, fontSize: 10, fontFamily: Font.bodyBold },
  statusBadge: { borderRadius: 5, paddingHorizontal: 6, paddingVertical: 1 },
  statusText: { color: '#fff', fontSize: 10, fontFamily: Font.bodyBold },
  // leaders
  leaderCard: { borderWidth: 1, borderRadius: 16, padding: 16, marginBottom: 10, overflow: 'hidden' },
  leaderTitle: { fontSize: 11, fontFamily: Font.bodyBold, letterSpacing: 1.4, color: Brand.gold, textTransform: 'uppercase', marginBottom: 10 },
  leaderRow: { flexDirection: 'row', alignItems: 'center', gap: 12, paddingVertical: 6 },
  leaderRank: { width: 16, fontSize: 14, fontFamily: Font.black, textAlign: 'center' },
  leaderName: { flex: 1, fontSize: 14, fontFamily: Font.bodySemi },
  leaderVal: { fontSize: 16, fontFamily: Font.display, fontVariant: ['tabular-nums'] },
  // movement
  moveSectionRow: { flexDirection: 'row', alignItems: 'center', marginTop: 18, marginBottom: 10 },
  countPill: { marginLeft: 8, minWidth: 22, paddingHorizontal: 8, paddingVertical: 2, borderRadius: 999, alignItems: 'center' },
  countText: { fontSize: 11, fontFamily: Font.bodyBold },
  moveCard: { backgroundColor: c.card, borderWidth: 1, borderColor: c.border, borderLeftWidth: 3, borderRadius: 14, padding: 14, marginBottom: 8 },
  cardHead: { flexDirection: 'row', alignItems: 'center', gap: 8, marginBottom: 6 },
  dirBadge: { flexDirection: 'row', alignItems: 'center', gap: 3, borderRadius: 6, paddingHorizontal: 7, paddingVertical: 3 },
  dirText: { fontSize: 10, fontFamily: Font.bodyBold },
  tag: { backgroundColor: c.surface2, borderRadius: 6, paddingHorizontal: 7, paddingVertical: 2 },
  tagText: { color: c.textSecondary, fontSize: 10, fontFamily: Font.bodyBold },
  catTag: { borderRadius: 6, paddingHorizontal: 7, paddingVertical: 2 },
  catText: { fontSize: 10, fontFamily: Font.bodyBold },
  status: { fontSize: 11, color: c.textMuted, flex: 1, textAlign: 'right', fontFamily: Font.body },
  // The date is the sort key now, so it reads brighter than the status beside it.
  moveDate: { color: c.text, fontFamily: Font.bodyMed },
  player: { fontSize: 14, fontFamily: Font.displaySemi },
  school: { fontSize: 13, fontFamily: Font.bodyMed, marginTop: 3 },
  notes: { fontSize: 12, marginTop: 4, lineHeight: 17, color: c.textSecondary, fontFamily: Font.body },
  source: { fontSize: 11, marginTop: 6, fontFamily: Font.bodyMed },
  footer: { textAlign: 'center', marginTop: 16, fontSize: 12, color: c.textMuted, fontFamily: Font.body },
});
