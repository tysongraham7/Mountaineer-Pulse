import { Ionicons } from '@expo/vector-icons';
import * as WebBrowser from 'expo-web-browser';
import { useCallback, useEffect, useState } from 'react';
import {
  ActivityIndicator,
  Image,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { PlayerProfile } from '@/components/player-profile';
import { Brand, Font, surfaces } from '@/constants/brand';
import { supabase } from '@/lib/supabase';
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
    { title: 'Strikeouts (P)', cat: 'pitching', type: 'SO', top: 5 },
    { title: 'Wins', cat: 'pitching', type: 'W', top: 3 },
    { title: 'Saves', cat: 'pitching', type: 'SV', top: 3 },
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
  return new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

// Roster can be viewed for last completed season (the scraped roster) or the
// upcoming season projected from Movement (returners minus departures + signees).
// Season labels differ by sport (fall vs spring vs winter academic year).
const ROSTER_SEASON_LABELS: Record<string, { projected: string; last: string }> = {
  football: { projected: '2026', last: '2025' },
  mbb: { projected: '2026-27', last: '2025-26' },
  baseball: { projected: '2027', last: '2026' },
};

// A projected-incoming player synthesized from a roster move (no photo/jersey yet).
type RosterItem = Player & {
  incoming?: boolean;
  fromSchool?: string | null;
  moveCategory?: string | null;
  note?: string | null;
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
  };
}

export default function TeamScreen() {
  const insets = useSafeAreaInsets();

  const [players, setPlayers] = useState<Player[]>([]);
  const [depth, setDepth] = useState<DepthEntry[]>([]);
  const [moves, setMoves] = useState<RosterMove[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [filter, setFilter] = useState<(typeof FILTERS)[number]['id']>('football');
  const [mode, setMode] = useState<(typeof MODES)[number]['id']>('roster');
  const [leaderSeason, setLeaderSeason] = useState<number>(2025);
  const [rosterView, setRosterView] = useState<'projected' | 'last'>('projected');
  const [depthView, setDepthView] = useState<'projected' | 'last'>('projected');
  const [selected, setSelected] = useState<Player | null>(null);

  const load = useCallback(async () => {
    const [pRes, dRes, mRes] = await Promise.all([
      supabase.from('players').select('*'),
      supabase.from('depth_chart').select('*'),
      supabase.from('roster_moves').select('*').order('move_date', { ascending: false }),
    ]);
    setPlayers((pRes.data ?? []) as Player[]);
    setDepth((dRes.data ?? []) as DepthEntry[]);
    setMoves((mRes.data ?? []) as RosterMove[]);
    setLoading(false);
    setRefreshing(false);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  if (loading) {
    return (
      <View style={[styles.center, { backgroundColor: c.bg }]}>
        <ActivityIndicator size="large" color={Brand.gold} />
        <Text style={{ color: c.textSecondary, marginTop: 12 }}>Loading…</Text>
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
                      {v === 'projected' ? ' · Proj.' : ''}
                    </Text>
                  </Pressable>
                );
              })}
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
                      {v === 'projected' ? ' · Proj.' : ''}
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
  c,
  onPick,
  showHeader,
}: {
  sport: string;
  players: Player[];
  moves: RosterMove[];
  projected: boolean;
  c: ReturnType<typeof surfaces>;
  onPick: (p: Player) => void;
  showHeader: boolean;
}) {
  const projLabel = ROSTER_SEASON_LABELS[sport]?.projected ?? '';
  let returning: Player[] = players;
  let incoming: RosterItem[] = [];
  if (projected) {
    const departed = new Set(
      moves.filter((m) => m.direction === 'out').map((m) => normName(m.player_name)),
    );
    const inMoves = moves.filter((m) => m.direction === 'in');
    const incomingNames = new Set(inMoves.map((m) => normName(m.player_name)));
    // Returning = current roster minus departures minus anyone counted as incoming
    // (the scrape may already list new arrivals — don't show them in both sections).
    returning = players.filter((p) => {
      const k = normName(playerFullName(p));
      return !departed.has(k) && !incomingNames.has(k);
    });
    // Incoming: reuse the scraped roster record (photo/jersey) when it exists, else synth.
    const rosterByName = new Map(players.map((p) => [normName(playerFullName(p)), p]));
    incoming = inMoves.map((m) => {
      const rp = rosterByName.get(normName(m.player_name));
      return rp
        ? { ...rp, incoming: true, fromSchool: m.other_school, moveCategory: m.category, note: m.notes }
        : synthFromMove(m, sport);
    });
  }
  const sorted = [...returning].sort((a, b) => (a.jersey ?? 999) - (b.jersey ?? 999));
  const incSorted = [...incoming].sort((a, b) => playerFullName(a).localeCompare(playerFullName(b)));

  return (
    <>
      {showHeader && <SectionTitle text={SPORT_LABEL[sport]} color={c.text} />}
      {sorted.length === 0 && incSorted.length === 0 ? (
        <Text style={[styles.empty, { color: c.textSecondary }]}>
          {sport === 'baseball' ? 'Baseball roster isn’t available yet.' : 'No roster loaded.'}
        </Text>
      ) : (
        <>
          {projected && (
            <Text style={[styles.rosterNote, { color: c.textSecondary }]}>
              Projected {projLabel} · {sorted.length} returning + {incSorted.length} incoming
            </Text>
          )}
          {sorted.map((p) => (
            <RosterRow key={p.id} player={p} c={c} onPick={onPick} />
          ))}
          {incSorted.length > 0 && (
            <>
              <Text style={[styles.incomingLabel, { color: Brand.gold }]}>INCOMING FOR {projLabel}</Text>
              {incSorted.map((p) => (
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
      </View>
      {player.incoming ? (
        <View style={[styles.incTag, { borderColor: Brand.win }]}>
          <Text style={[styles.incTagText, { color: Brand.win }]}>
            {(player.moveCategory && CATEGORY_LABEL[player.moveCategory]) || 'New'}
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
        // Insert a big position-group header (Running Backs, Receivers, …) whenever
        // the group changes. Positions with no group (basketball/baseball) stay flat.
        let lastGroup: string | undefined;
        return (
          <View key={unit || 'x'}>
            {unit ? <Text style={styles.unitLabel}>{unit.toUpperCase()}</Text> : null}
            {slotList.map(([order, ps]) => {
              const group = FB_GROUP[ps[0].position];
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

// Grouped sections for the Movement page. In = green, Out = red (via MoveCard).
const MOVE_SECTIONS: { title: string; match: (m: RosterMove) => boolean }[] = [
  { title: 'Transfers In', match: (m) => m.direction === 'in' && m.category === 'transfer' },
  { title: 'JUCO Signees', match: (m) => m.direction === 'in' && m.category === 'juco' },
  { title: 'High School Signees', match: (m) => m.direction === 'in' && (m.category === 'hs' || m.category === 'recruit') },
  { title: 'Transfers Out', match: (m) => m.direction === 'out' && m.category === 'transfer' },
  {
    title: 'Out of Eligibility',
    match: (m) => m.direction === 'out' && (m.category === 'eligibility' || m.category === 'graduation' || m.category === 'draft'),
  },
];

function MovementView({ moves, c, showTag }: { moves: RosterMove[]; c: ReturnType<typeof surfaces>; showTag: boolean }) {
  const sections = MOVE_SECTIONS.map((s) => ({ title: s.title, items: moves.filter(s.match) })).filter(
    (s) => s.items.length > 0,
  );
  if (sections.length === 0) {
    return <Text style={[styles.empty, { color: c.textSecondary }]}>No moves logged yet.</Text>;
  }
  return (
    <>
      {sections.map((s) => (
        <View key={s.title}>
          <View style={styles.moveSectionRow}>
            <Text style={styles.sectionTitle}>{s.title}</Text>
            <View style={[styles.countPill, { backgroundColor: c.surface2 }]}>
              <Text style={[styles.countText, { color: c.textSecondary }]}>{s.items.length}</Text>
            </View>
          </View>
          {s.items.map((m) => (
            <MoveCard key={m.id} move={m} c={c} showTag={showTag} />
          ))}
        </View>
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
        <View style={[styles.dirBadge, { backgroundColor: isIn ? Brand.greenTint : Brand.redTint }]}>
          <Ionicons name={isIn ? 'arrow-down' : 'arrow-up'} size={11} color={accent} />
          <Text style={[styles.dirText, { color: accent }]}>{isIn ? 'IN' : 'OUT'}</Text>
        </View>
        {move.category && CATEGORY_LABEL[move.category] && (
          <View style={[styles.catTag, { backgroundColor: c.surface2 }]}>
            <Text style={[styles.catText, { color: c.textSecondary }]}>{CATEGORY_LABEL[move.category]}</Text>
          </View>
        )}
        {showTag && move.sport_id && SPORT_TAG[move.sport_id] && (
          <View style={styles.tag}>
            <Text style={styles.tagText}>{SPORT_TAG[move.sport_id]}</Text>
          </View>
        )}
        <Text style={[styles.status, { color: c.textSecondary }]}>
          {move.status ?? ''} · {formatDate(move.move_date)}
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
    return <ActivityIndicator style={{ marginTop: 30 }} color={Brand.gold} />;
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
  groupLabel: { fontFamily: Font.display, fontSize: 16, color: c.text, letterSpacing: -0.2, marginTop: 16, marginBottom: 8 },
  depthCard: { flexDirection: 'row', alignItems: 'flex-start', gap: 14, borderWidth: 1, borderRadius: 16, padding: 14, marginBottom: 8 },
  depthPos: { width: 54, fontSize: 13, fontFamily: Font.black, color: Brand.gold, paddingTop: 3 },
  depthPlayerRow: { flexDirection: 'row', alignItems: 'center', gap: 10, paddingVertical: 5 },
  depthRank: { width: 20, height: 20, borderRadius: 6, alignItems: 'center', justifyContent: 'center' },
  depthRankText: { fontSize: 12, fontFamily: Font.bodyBold },
  depthName: { fontSize: 14, fontFamily: Font.bodySemi },
  depthNoteLine: { fontSize: 11, marginTop: 2, lineHeight: 15, fontFamily: Font.body },
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
  player: { fontSize: 14, fontFamily: Font.displaySemi },
  school: { fontSize: 13, fontFamily: Font.bodyMed, marginTop: 3 },
  notes: { fontSize: 12, marginTop: 4, lineHeight: 17, color: c.textSecondary, fontFamily: Font.body },
  source: { fontSize: 11, marginTop: 6, fontFamily: Font.bodyMed },
  footer: { textAlign: 'center', marginTop: 16, fontSize: 12, color: c.textMuted, fontFamily: Font.body },
});
