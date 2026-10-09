// Stats (Team tab): WVU's stat leaderboards for this season, any past season, careers and best single
// seasons, plus team stats and the year-by-year record.
//
// Everything is ranked by the pipeline (sync_stat_archive.py) into stat_leaders, including
// qualification floors for rate stats, so this screen never sorts or filters a leaderboard
// itself — two places computing "who qualifies" would eventually disagree. The boards, their
// titles and their groups come from the rows too, so a new board ships without an app update.
import { Ionicons } from '@expo/vector-icons';
import { useEffect, useMemo, useRef, useState } from 'react';
import { Image, Modal, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';

import { PlayerProfile } from '@/components/player-profile';
import { ListRowSkeleton, SkeletonList } from '@/components/skeleton';
import { SheetHeader } from '@/components/ui';
import { Brand, Font, surfaces } from '@/constants/brand';
import { trackFeature } from '@/lib/analytics';
import { normName, playerFullName } from '@/lib/names';
import { supabase } from '@/lib/supabase';
import { Player } from '@/lib/types';

const c = surfaces(true);

type LeaderRow = {
  board: string;
  board_title: string;
  board_group: string;
  board_order: number;
  hero: boolean;
  rank: number;
  player_key: string;
  player_name: string;
  jersey: string | null;
  photo_url: string | null;
  position: string | null;
  display: string;
  detail: string | null;
};
type Board = { key: string; title: string; group: string; hero: boolean; rows: LeaderRow[] };
type TeamStat = { stat: string; label: string; grp: string; ord: number; wvu: string | null; opp: string | null };
type SeasonRecord = {
  season: number;
  total_wins: number | null;
  total_losses: number | null;
  ties: number | null;
  conference: string | null;
  conf_wins: number | null;
  conf_losses: number | null;
};

type BookRow = {
  list_key: string;
  title: string;
  grp: string;
  ord: number;
  rank: number;
  player_name: string;
  display: string;
  detail: string | null;
  source: string;
  through: number;
};

type Pane = 'players' | 'team' | 'records';
type Scope = 'current' | 'year' | 'career' | 'best' | 'history';
type BookScope = 'career' | 'season' | 'game';

const PANES: { id: Pane; label: string }[] = [
  { id: 'players', label: 'Players' },
  { id: 'team', label: 'Team' },
  { id: 'records', label: 'Records' },
];
const BOOK_SCOPES: { id: BookScope; label: string }[] = [
  { id: 'career', label: 'Career' },
  { id: 'season', label: 'Season' },
  { id: 'game', label: 'Game' },
];

const PLAYER_SCOPES: { id: Scope; label: string }[] = [
  { id: 'current', label: 'This Season' },
  { id: 'year', label: 'By Year' },
  { id: 'career', label: 'Career' },
  { id: 'best', label: 'Best Season' },
];
const TEAM_SCOPES: { id: Scope; label: string }[] = [
  { id: 'current', label: 'This Season' },
  { id: 'year', label: 'By Year' },
  { id: 'history', label: 'All Seasons' },
];

const PREVIEW = 5; // rows per board on the hub; the rest are one tap away

const LEADER_COLS =
  'board,board_title,board_group,board_order,hero,rank,player_key,player_name,jersey,photo_url,position,display,detail';

/** Basketball seasons are stored by the year they end: 2026 is the 2025-26 season. */
export function seasonLabel(sport: string, season: number): string {
  return sport === 'mbb' ? `${season - 1}-${String(season).slice(2)}` : String(season);
}

function initials(name: string): string {
  const parts = name.split(/\s+/).filter(Boolean);
  return ((parts[0]?.[0] ?? '') + (parts[parts.length - 1]?.[0] ?? '')).toUpperCase();
}

function Avatar({ row, size }: { row: LeaderRow; size: number }) {
  const [failed, setFailed] = useState(false);
  const box = { width: size, height: size, borderRadius: size / 2 };
  if (row.photo_url && !failed) {
    return (
      <Image
        source={{ uri: row.photo_url }}
        style={[box, styles.avatar]}
        onError={() => setFailed(true)}
      />
    );
  }
  return (
    <View style={[box, styles.avatar, styles.avatarFallback]}>
      <Text style={[styles.avatarText, { fontSize: size * 0.34 }]}>
        {row.jersey != null && row.jersey !== '' ? `#${row.jersey}` : initials(row.player_name)}
      </Text>
    </View>
  );
}

export function StatLeaders({
  sport,
  players,
  refreshKey,
}: {
  sport: string;
  players: Player[];
  refreshKey: number;
}) {
  const [view, setView] = useState<Pane>('players');
  const [scope, setScope] = useState<Scope>('current');
  const [year, setYear] = useState<number | null>(null);
  // season -> games played. One row per season the archive has, so it doubles as the list
  // of seasons there's anything to show for.
  const [seasons, setSeasons] = useState<Map<number, number> | null>(null);
  const [rows, setRows] = useState<LeaderRow[] | null>(null);
  const [teamStats, setTeamStats] = useState<TeamStat[] | null>(null);
  const [records, setRecords] = useState<SeasonRecord[] | null>(null);
  const [bookScope, setBookScope] = useState<BookScope>('career');
  const [book, setBook] = useState<BookRow[] | null>(null);
  const [openBoard, setOpenBoard] = useState<Board | null>(null);
  const [picked, setPicked] = useState<Player | null>(null);
  // Switching back to a scope already seen is instant; the cache empties on pull-to-refresh.
  const cache = useRef(new Map<string, unknown>());

  useEffect(() => {
    cache.current.clear();
  }, [refreshKey]);

  useEffect(() => {
    let live = true;
    setSeasons(null);
    supabase
      .from('team_season_stats')
      .select('season,wvu')
      .eq('sport_id', sport)
      .eq('stat', 'games')
      .then(({ data }) => {
        if (!live) return;
        const m = new Map<number, number>();
        for (const r of data ?? []) m.set(r.season as number, Number(r.wvu) || 0);
        setSeasons(m);
      });
    return () => {
      live = false;
    };
  }, [sport, refreshKey]);

  const seasonList = useMemo(() => [...(seasons?.keys() ?? [])].sort((a, b) => b - a), [seasons]);
  const current = seasonList[0];
  const first = seasonList[seasonList.length - 1];
  // By Year opens on last season rather than repeating "This Season".
  const effYear = year != null && seasonList.includes(year) ? year : (seasonList[1] ?? current);
  const effScope: Scope =
    view === 'team'
      ? scope === 'career' || scope === 'best' ? 'history' : scope
      : scope === 'history' ? 'career' : scope;
  const season = effScope === 'current' ? current : effScope === 'year' ? effYear : 0;

  useEffect(() => {
    if (current == null) return;
    let live = true;
    const remember = <T,>(key: string, set: (v: T) => void, run: () => PromiseLike<T>) => {
      const hit = cache.current.get(key) as T | undefined;
      if (hit) {
        set(hit);
        return;
      }
      run().then((v) => {
        cache.current.set(key, v);
        if (live) set(v);
      });
    };

    if (view === 'records') {
      setBook(null);
      remember(`b|${sport}|${bookScope}`, setBook, () =>
        supabase
          .from('record_book')
          .select('list_key,title,grp,ord,rank,player_name,display,detail,source,through')
          .eq('sport_id', sport)
          .eq('scope', bookScope)
          .order('ord')
          .order('rank')
          .then(({ data }) => (data ?? []) as BookRow[]),
      );
    } else if (view === 'players') {
      setRows(null);
      const dbScope = effScope === 'career' || effScope === 'best' ? effScope : 'season';
      remember(`p|${sport}|${dbScope}|${season}`, setRows, () =>
        supabase
          .from('stat_leaders')
          .select(LEADER_COLS)
          .eq('sport_id', sport)
          .eq('scope', dbScope)
          .eq('season', season)
          .order('board_order')
          .order('rank')
          .then(({ data }) => (data ?? []) as LeaderRow[]),
      );
    } else if (effScope === 'history') {
      setRecords(null);
      remember(`r|${sport}`, setRecords, () =>
        supabase
          .from('team_records')
          .select('season,total_wins,total_losses,ties,conference,conf_wins,conf_losses')
          .eq('sport_id', sport)
          .eq('team', 'West Virginia')
          .order('season', { ascending: false })
          .then(({ data }) =>
            ((data ?? []) as SeasonRecord[]).filter(
              (r) => (r.total_wins ?? 0) + (r.total_losses ?? 0) + (r.ties ?? 0) > 0,
            ),
          ),
      );
    } else {
      setTeamStats(null);
      remember(`t|${sport}|${season}`, setTeamStats, () =>
        supabase
          .from('team_season_stats')
          .select('stat,label,grp,ord,wvu,opp')
          .eq('sport_id', sport)
          .eq('season', season)
          .order('ord')
          .then(({ data }) => (data ?? []) as TeamStat[]),
      );
    }
    return () => {
      live = false;
    };
  }, [sport, view, effScope, season, current, bookScope, refreshKey]);

  // Leaders link to a profile only when they're on today's roster; a 2016 linebacker has
  // no page to open. Matched by name: the archive and the roster are different sources.
  const onRoster = useMemo(() => {
    const m = new Map<string, Player>();
    for (const p of players) m.set(normName(playerFullName(p)), p);
    return m;
  }, [players]);
  const profileFor = (r: LeaderRow) => onRoster.get(normName(r.player_name)) ?? null;

  const boards = useMemo(() => {
    const out: Board[] = [];
    for (const r of rows ?? []) {
      let b = out[out.length - 1];
      if (!b || b.key !== r.board) {
        b = { key: r.board, title: r.board_title, group: r.board_group, hero: r.hero, rows: [] };
        out.push(b);
      }
      b.rows.push(r);
    }
    return out;
  }, [rows]);

  if (seasons == null) return <Loading />;
  if (current == null) {
    return <Text style={styles.empty}>No stats on record for this sport yet.</Text>;
  }

  const label = (s: number) => seasonLabel(sport, s);
  const scopes = view === 'players' ? PLAYER_SCOPES : TEAM_SCOPES;
  const games = seasons.get(season);
  const context =
    view === 'records'
      ? bookScope === 'career'
        ? 'WVU record book · all-time career leaders'
        : bookScope === 'season'
          ? 'WVU record book · best single seasons, all-time'
          : 'WVU record book · best single games, all-time'
      : effScope === 'career'
      ? `WVU careers · official stats since ${label(first)}`
      : effScope === 'best'
        ? `Best single seasons since ${label(first)}`
        : effScope === 'history'
          ? 'Every season on record'
          : `${label(season)} season${games ? ` · ${games} games` : ''}`;

  return (
    <View>
      <View style={styles.viewToggle}>
        {PANES.map((v) => {
          const active = view === v.id;
          return (
            <Pressable
              key={v.id}
              onPress={() => {
                trackFeature('leaders_view_switch');
                setView(v.id);
              }}
              style={[styles.viewBtn, active && { backgroundColor: c.surface2 }]}>
              <Text style={[styles.viewText, { color: active ? c.text : c.textMuted }]}>{v.label}</Text>
            </Pressable>
          );
        })}
      </View>

      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.chipRow}>
        {view === 'records'
          ? BOOK_SCOPES.map((s) => {
              const active = bookScope === s.id;
              return (
                <Pressable
                  key={s.id}
                  onPress={() => {
                    trackFeature('leaders_scope_switch');
                    setBookScope(s.id);
                  }}
                  style={[styles.chip, active ? styles.chipOn : styles.chipOff]}>
                  <Text style={[styles.chipText, { color: active ? Brand.onGold : c.textSecondary }]}>{s.label}</Text>
                </Pressable>
              );
            })
          : scopes.map((s) => {
          const active = effScope === s.id;
          return (
            <Pressable
              key={s.id}
              onPress={() => {
                trackFeature('leaders_scope_switch');
                setScope(s.id);
              }}
              style={[styles.chip, active ? styles.chipOn : styles.chipOff]}>
              <Text style={[styles.chipText, { color: active ? Brand.onGold : c.textSecondary }]}>{s.label}</Text>
            </Pressable>
          );
            })}
      </ScrollView>

      {view !== 'records' && effScope === 'year' && (
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.chipRow}>
          {seasonList.map((s) => {
            const active = effYear === s;
            return (
              <Pressable
                key={s}
                onPress={() => setYear(s)}
                style={[styles.yearChip, active ? styles.yearOn : styles.chipOff]}>
                <Text style={[styles.yearText, { color: active ? Brand.gold : c.textSecondary }]}>{label(s)}</Text>
              </Pressable>
            );
          })}
        </ScrollView>
      )}

      <Text style={styles.context}>{context}</Text>

      {view === 'records' ? (
        book == null ? (
          <Loading />
        ) : book.length === 0 ? (
          <Text style={styles.empty}>No record book for this sport yet.</Text>
        ) : (
          <RecordBook sport={sport} rows={book} first={first} profileFor={(n) => onRoster.get(normName(n)) ?? null} onPick={setPicked} />
        )
      ) : view === 'players' ? (
        rows == null ? (
          <Loading />
        ) : boards.length === 0 ? (
          <Text style={styles.empty}>No stats for the {label(season)} season yet.</Text>
        ) : (
          <PlayerBoards
            boards={boards}
            scope={effScope}
            profileFor={profileFor}
            onPick={setPicked}
            onOpen={(b) => {
              trackFeature('leaders_board_open');
              setOpenBoard(b);
            }}
          />
        )
      ) : effScope === 'history' ? (
        records == null ? <Loading /> : <RecordHistory sport={sport} records={records} />
      ) : teamStats == null ? (
        <Loading />
      ) : teamStats.length === 0 ? (
        <Text style={styles.empty}>No team stats for {label(season)} yet.</Text>
      ) : (
        <TeamTable stats={teamStats} />
      )}

      {(effScope === 'career' || effScope === 'best') && view === 'players' && (
        <Text style={styles.footnote}>
          From WVU&apos;s official season stats, which begin in {label(first)}. A career that started
          earlier counts only its seasons from then on.
        </Text>
      )}

      <Modal visible={!!openBoard} animationType="slide" onRequestClose={() => setOpenBoard(null)}>
        <View style={{ flex: 1, backgroundColor: c.bg }}>
          {openBoard && (
            <>
              <SheetHeader title={openBoard.title} onClose={() => setOpenBoard(null)} />
              <ScrollView contentContainerStyle={{ paddingHorizontal: 20, paddingBottom: 40 }}>
                <Text style={styles.context}>{context}</Text>
                {openBoard.rows.map((r, i) => (
                  <LeaderLine
                    key={`${r.player_key}-${i}`}
                    row={r}
                    scope={effScope}
                    size={38}
                    profile={profileFor(r)}
                    onPick={setPicked}
                    divider={i > 0}
                  />
                ))}
              </ScrollView>
              {/* Inside the sheet's Modal so it opens on top of the list, not behind it. */}
              <PlayerProfile player={picked} onClose={() => setPicked(null)} />
            </>
          )}
        </View>
      </Modal>
      <PlayerProfile player={openBoard ? null : picked} onClose={() => setPicked(null)} />
    </View>
  );
}

function Loading() {
  return (
    <View style={{ marginTop: 12, gap: 8 }}>
      <SkeletonList count={6}>
        <ListRowSkeleton />
      </SkeletonList>
    </View>
  );
}

/** "QB · 101/170", "2015 · 238 car", "2016-19": what sits under a leader's name. */
function subLine(row: LeaderRow, scope: Scope): string {
  const parts = scope === 'best' ? [row.detail] : [row.position, row.detail];
  return parts.filter(Boolean).join(' · ');
}

function PlayerBoards({
  boards,
  scope,
  profileFor,
  onPick,
  onOpen,
}: {
  boards: Board[];
  scope: Scope;
  profileFor: (r: LeaderRow) => Player | null;
  onPick: (p: Player) => void;
  onOpen: (b: Board) => void;
}) {
  // The three headline numbers a fan checks first, lifted out as cards before the full list.
  const heroes = boards.filter((b) => b.hero && b.rows.length > 0).slice(0, 3);
  const groups: { name: string; boards: Board[] }[] = [];
  for (const b of boards) {
    const g = groups[groups.length - 1];
    if (g && g.name === b.group) g.boards.push(b);
    else groups.push({ name: b.group, boards: [b] });
  }

  return (
    <>
      {heroes.length > 0 && (
        <View style={styles.heroRow}>
          {heroes.map((b) => {
            const r = b.rows[0];
            const profile = profileFor(r);
            const sub = scope === 'best' ? (r.detail ?? '').split(' · ')[0] : scope === 'career' ? r.detail : r.position;
            return (
              <Pressable
                key={b.key}
                onPress={() => onOpen(b)}
                style={({ pressed }) => [styles.heroCard, pressed && { opacity: 0.85 }]}>
                <Avatar row={r} size={46} />
                <Text style={styles.heroValue} numberOfLines={1} adjustsFontSizeToFit>
                  {r.display}
                </Text>
                <Text style={styles.heroLabel} numberOfLines={2}>
                  {b.title}
                </Text>
                <Text
                  style={styles.heroName}
                  numberOfLines={1}
                  onPress={profile ? () => onPick(profile) : undefined}>
                  {r.player_name}
                </Text>
                {sub ? (
                  <Text style={styles.heroSub} numberOfLines={1}>
                    {sub}
                  </Text>
                ) : null}
              </Pressable>
            );
          })}
        </View>
      )}

      {groups.map((g) => (
        <View key={g.name}>
          <View style={styles.sectionRow}>
            <View style={styles.goldBar} />
            <Text style={styles.sectionTitle}>{g.name}</Text>
          </View>
          {g.boards.map((b) => (
            <View key={b.key} style={styles.card}>
              <Text style={styles.cardTitle}>{b.title}</Text>
              {b.rows.slice(0, PREVIEW).map((r, i) => (
                <LeaderLine
                  key={`${r.player_key}-${i}`}
                  row={r}
                  scope={scope}
                  size={30}
                  profile={profileFor(r)}
                  onPick={onPick}
                  divider={false}
                />
              ))}
              {b.rows.length > PREVIEW && (
                <Pressable onPress={() => onOpen(b)} hitSlop={6} style={styles.seeAll}>
                  <Text style={styles.seeAllText}>See all {b.rows.length}</Text>
                  <Ionicons name="chevron-forward" size={13} color={Brand.gold} />
                </Pressable>
              )}
            </View>
          ))}
        </View>
      ))}
    </>
  );
}

function LeaderLine({
  row,
  scope,
  size,
  profile,
  onPick,
  divider,
}: {
  row: LeaderRow;
  scope: Scope;
  size: number;
  profile: Player | null;
  onPick: (p: Player) => void;
  divider: boolean;
}) {
  const podium = row.rank === 1;
  const sub = subLine(row, scope);
  const body = (
    <View style={[styles.line, divider && styles.lineDivider]}>
      <Text style={[styles.rank, { color: podium ? Brand.gold : c.textMuted }]}>{row.rank}</Text>
      <Avatar row={row} size={size} />
      <View style={{ flex: 1, minWidth: 0 }}>
        <Text style={styles.name} numberOfLines={1}>
          {row.player_name}
        </Text>
        {sub ? (
          <Text style={styles.sub} numberOfLines={1}>
            {sub}
          </Text>
        ) : null}
      </View>
      <Text style={[styles.value, { color: podium ? Brand.gold : c.text }]}>{row.display}</Text>
      {/* Space held on every row so values line up whether or not the row opens a profile. */}
      <View style={styles.chevron}>
        {profile && <Ionicons name="chevron-forward" size={13} color={c.textMuted} />}
      </View>
    </View>
  );
  if (!profile) return body;
  return (
    <Pressable onPress={() => onPick(profile)} style={({ pressed }) => pressed && { opacity: 0.7 }}>
      {body}
    </Pressable>
  );
}

/**
 * The all-time lists. No headshots: most of these names predate the website, and a column of
 * blank circles beside Jerry West says less than his name does. The source line matters more
 * here than anywhere else in the app — these numbers come from WVU's books, then the archive.
 */
function RecordBook({
  sport,
  rows,
  first,
  profileFor,
  onPick,
}: {
  sport: string;
  rows: BookRow[];
  first: number;
  profileFor: (name: string) => Player | null;
  onPick: (p: Player) => void;
}) {
  const groups: { name: string; lists: { key: string; title: string; rows: BookRow[] }[] }[] = [];
  for (const r of rows) {
    let g = groups[groups.length - 1];
    if (!g || g.name !== r.grp) {
      g = { name: r.grp, lists: [] };
      groups.push(g);
    }
    let l = g.lists[g.lists.length - 1];
    if (!l || l.key !== r.list_key) {
      l = { key: r.list_key, title: r.title, rows: [] };
      g.lists.push(l);
    }
    l.rows.push(r);
  }
  const { source, through } = rows[0];
  return (
    <>
      {groups.map((g) => (
        <View key={g.name}>
          <View style={styles.sectionRow}>
            <View style={styles.goldBar} />
            <Text style={styles.sectionTitle}>{g.name}</Text>
          </View>
          {g.lists.map((l) => (
            <View key={l.key} style={styles.card}>
              <Text style={styles.cardTitle}>{l.title}</Text>
              {l.rows.map((r, i) => {
                const profile = profileFor(r.player_name);
                const body = (
                  <View style={[styles.line, i > 0 && styles.lineDivider]}>
                    <Text style={[styles.rank, { color: r.rank === 1 ? Brand.gold : c.textMuted }]}>{r.rank}</Text>
                    <View style={{ flex: 1, minWidth: 0 }}>
                      <Text style={styles.name} numberOfLines={1}>
                        {r.player_name}
                      </Text>
                      {r.detail ? (
                        <Text style={styles.sub} numberOfLines={1}>
                          {r.detail}
                        </Text>
                      ) : null}
                    </View>
                    <Text style={[styles.value, { color: r.rank === 1 ? Brand.gold : c.text }]}>{r.display}</Text>
                    <View style={styles.chevron}>
                      {profile && <Ionicons name="chevron-forward" size={13} color={c.textMuted} />}
                    </View>
                  </View>
                );
                return profile ? (
                  <Pressable key={`${r.player_name}-${i}`} onPress={() => onPick(profile)}>
                    {body}
                  </Pressable>
                ) : (
                  <View key={`${r.player_name}-${i}`}>{body}</View>
                );
              })}
            </View>
          ))}
        </View>
      ))}
      <Text style={styles.footnote}>
        Lists through {seasonLabel(sport, through)} from the {source}. Every season since{' '}
        {seasonLabel(sport, first)} is added nightly from WVU&apos;s official stats, so a new record shows
        up here the morning after it&apos;s set.
      </Text>
    </>
  );
}

function TeamTable({ stats }: { stats: TeamStat[] }) {
  const groups: { name: string; rows: TeamStat[] }[] = [];
  for (const s of stats) {
    const g = groups[groups.length - 1];
    if (g && g.name === s.grp) g.rows.push(s);
    else groups.push({ name: s.grp, rows: [s] });
  }
  return (
    <>
      {groups.map((g) => {
        const hasOpp = g.rows.some((r) => r.opp != null);
        return (
          <View key={g.name} style={styles.card}>
            <View style={styles.teamHead}>
              <Text style={[styles.cardTitle, { flex: 1, marginBottom: 0 }]}>{g.name}</Text>
              {hasOpp && (
                <>
                  <Text style={styles.teamCol}>WVU</Text>
                  <Text style={styles.teamCol}>OPP</Text>
                </>
              )}
            </View>
            {g.rows.map((r, i) => (
              <View key={r.stat} style={[styles.teamRow, i > 0 && styles.lineDivider]}>
                <Text style={styles.teamLabel}>{r.label}</Text>
                <Text style={[styles.teamVal, !hasOpp && { width: undefined }]}>{r.wvu ?? '—'}</Text>
                {hasOpp && <Text style={[styles.teamVal, { color: c.textSecondary }]}>{r.opp ?? '—'}</Text>}
              </View>
            ))}
          </View>
        );
      })}
    </>
  );
}

function recordText(w: number | null, l: number | null, t?: number | null): string {
  return `${w ?? 0}-${l ?? 0}${t ? `-${t}` : ''}`;
}

function RecordHistory({ sport, records }: { sport: string; records: SeasonRecord[] }) {
  if (records.length === 0) return <Text style={styles.empty}>No season records yet.</Text>;
  const tot = records.reduce(
    (a, r) => ({ w: a.w + (r.total_wins ?? 0), l: a.l + (r.total_losses ?? 0), t: a.t + (r.ties ?? 0) }),
    { w: 0, l: 0, t: 0 },
  );
  const oldest = records[records.length - 1].season;
  const winning = records.filter((r) => (r.total_wins ?? 0) > (r.total_losses ?? 0)).length;
  // The source skips some early football seasons (1897-1901, 1903, 1918). Saying "since 1896"
  // over a total that leaves them out would overstate it, so the card counts seasons on file
  // and the gaps are named underneath.
  const have = new Set(records.map((r) => r.season));
  const gaps: string[] = [];
  for (let y = oldest; y <= records[0].season; y++) {
    if (have.has(y)) continue;
    let end = y;
    while (end + 1 <= records[0].season && !have.has(end + 1)) end++;
    gaps.push(end > y ? `${seasonLabel(sport, y)}–${seasonLabel(sport, end)}` : seasonLabel(sport, y));
    y = end;
  }
  return (
    <>
      <View style={styles.allTime}>
        <View style={{ flex: 1 }}>
          <Text style={styles.allTimeLabel}>{records.length} SEASONS ON FILE</Text>
          <Text style={styles.allTimeValue}>{recordText(tot.w, tot.l, tot.t)}</Text>
        </View>
        <View style={{ alignItems: 'flex-end' }}>
          <Text style={styles.allTimeLabel}>WINNING SEASONS</Text>
          <Text style={styles.allTimeValue}>
            {winning}
            <Text style={styles.allTimeOf}> of {records.length}</Text>
          </Text>
        </View>
      </View>
      <View style={styles.card}>
        {records.map((r, i) => {
          const w = r.total_wins ?? 0;
          const l = r.total_losses ?? 0;
          const conf = r.conf_wins != null && r.conf_losses != null ? recordText(r.conf_wins, r.conf_losses) : null;
          return (
            <View key={r.season} style={[styles.recRow, i > 0 && styles.lineDivider]}>
              <Text style={styles.recSeason}>{seasonLabel(sport, r.season)}</Text>
              <Text style={[styles.recMain, { color: w > l ? Brand.win : w < l ? Brand.loss : c.text }]}>
                {recordText(r.total_wins, r.total_losses, r.ties)}
              </Text>
              <Text style={styles.recConf} numberOfLines={1}>
                {[conf, r.conference].filter(Boolean).join(' · ')}
              </Text>
            </View>
          );
        })}
      </View>
      <Text style={styles.footnote}>
        Records from {seasonLabel(sport, oldest)} on.
        {gaps.length > 0 ? ` No record on file for ${gaps.join(', ')}.` : ''}
      </Text>
    </>
  );
}

const styles = StyleSheet.create({
  empty: { fontSize: 14, paddingVertical: 12, color: c.textSecondary, fontFamily: Font.body },
  viewToggle: {
    flexDirection: 'row',
    alignSelf: 'flex-start',
    marginTop: 10,
    padding: 3,
    borderRadius: 10,
    backgroundColor: c.card,
    borderWidth: 1,
    borderColor: c.border,
  },
  viewBtn: { paddingHorizontal: 16, paddingVertical: 5, borderRadius: 7 },
  viewText: { fontSize: 12, fontFamily: Font.bodyBold },
  chipRow: { gap: 6, paddingTop: 10 },
  chip: { paddingHorizontal: 11, paddingVertical: 6, borderRadius: 999, borderWidth: 1 },
  chipOn: { backgroundColor: Brand.gold, borderColor: Brand.gold },
  chipOff: { backgroundColor: c.card, borderColor: c.border },
  chipText: { fontSize: 12, fontFamily: Font.bodySemi },
  yearChip: { paddingHorizontal: 12, paddingVertical: 5, borderRadius: 8, borderWidth: 1 },
  yearOn: { backgroundColor: Brand.goldTint, borderColor: Brand.goldBorder },
  yearText: { fontSize: 12, fontFamily: Font.bodyBold, fontVariant: ['tabular-nums'] },
  context: { fontSize: 11, fontStyle: 'italic', marginTop: 12, marginBottom: 4, color: c.textMuted, fontFamily: Font.body },
  footnote: { fontSize: 11, lineHeight: 16, marginTop: 8, color: c.textMuted, fontFamily: Font.body },
  avatar: { backgroundColor: c.surface2 },
  avatarFallback: { alignItems: 'center', justifyContent: 'center' },
  avatarText: { color: c.textSecondary, fontFamily: Font.display },
  // hero cards
  heroRow: { flexDirection: 'row', gap: 8, marginTop: 10 },
  heroCard: {
    flex: 1,
    alignItems: 'center',
    backgroundColor: c.card,
    borderWidth: 1,
    borderColor: c.border,
    borderRadius: 16,
    paddingVertical: 14,
    paddingHorizontal: 8,
  },
  heroValue: { fontFamily: Font.black, fontSize: 22, color: Brand.gold, marginTop: 8, fontVariant: ['tabular-nums'] },
  heroLabel: { fontSize: 9, lineHeight: 12, fontFamily: Font.bodyBold, letterSpacing: 1, color: c.textMuted, textTransform: 'uppercase', textAlign: 'center', marginTop: 2 },
  heroName: { fontSize: 12, fontFamily: Font.bodySemi, color: c.text, marginTop: 6 },
  heroSub: { fontSize: 10.5, fontFamily: Font.body, color: c.textSecondary, marginTop: 1 },
  // boards
  sectionRow: { flexDirection: 'row', alignItems: 'center', marginTop: 18, marginBottom: 8 },
  goldBar: { width: 3, height: 14, borderRadius: 2, backgroundColor: Brand.gold, marginRight: 8 },
  sectionTitle: { fontSize: 12, fontFamily: Font.bodyBold, letterSpacing: 1.4, color: Brand.gold, textTransform: 'uppercase' },
  card: { backgroundColor: c.card, borderWidth: 1, borderColor: c.border, borderRadius: 16, padding: 14, marginBottom: 10 },
  cardTitle: { fontSize: 13, fontFamily: Font.displaySemi, color: c.text, marginBottom: 6 },
  line: { flexDirection: 'row', alignItems: 'center', gap: 10, paddingVertical: 6 },
  lineDivider: { borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: c.borderStrong },
  rank: { width: 18, fontSize: 13, fontFamily: Font.black, textAlign: 'center', fontVariant: ['tabular-nums'] },
  name: { fontSize: 14, fontFamily: Font.bodySemi, color: c.text },
  sub: { fontSize: 11, fontFamily: Font.body, color: c.textSecondary, marginTop: 1 },
  value: { fontSize: 16, fontFamily: Font.display, fontVariant: ['tabular-nums'] },
  chevron: { width: 13, marginLeft: -4 },
  seeAll: { flexDirection: 'row', alignItems: 'center', alignSelf: 'flex-end', gap: 2, marginTop: 4 },
  seeAllText: { fontSize: 12, fontFamily: Font.bodyBold, color: Brand.gold },
  // team table
  teamHead: { flexDirection: 'row', alignItems: 'center', marginBottom: 6 },
  teamCol: { width: 92, textAlign: 'right', fontSize: 10, fontFamily: Font.bodyBold, letterSpacing: 1.1, color: c.textMuted },
  teamRow: { flexDirection: 'row', alignItems: 'center', paddingVertical: 7 },
  teamLabel: { flex: 1, fontSize: 13, fontFamily: Font.body, color: c.textSecondary },
  teamVal: { width: 92, textAlign: 'right', fontSize: 13.5, fontFamily: Font.bodySemi, color: c.text, fontVariant: ['tabular-nums'] },
  // record history
  allTime: {
    flexDirection: 'row',
    alignItems: 'flex-end',
    backgroundColor: c.card,
    borderWidth: 1,
    borderColor: Brand.goldBorder,
    borderRadius: 16,
    padding: 16,
    marginTop: 10,
    marginBottom: 10,
  },
  allTimeLabel: { fontSize: 10, fontFamily: Font.bodyBold, letterSpacing: 1.2, color: Brand.gold },
  allTimeValue: { fontSize: 24, fontFamily: Font.black, color: c.text, marginTop: 4, fontVariant: ['tabular-nums'] },
  allTimeOf: { fontSize: 13, fontFamily: Font.bodySemi, color: c.textSecondary },
  recRow: { flexDirection: 'row', alignItems: 'center', gap: 12, paddingVertical: 8 },
  recSeason: { width: 62, fontSize: 13, fontFamily: Font.bodyBold, color: c.text, fontVariant: ['tabular-nums'] },
  recMain: { width: 64, fontSize: 14, fontFamily: Font.display, fontVariant: ['tabular-nums'] },
  recConf: { flex: 1, fontSize: 12, fontFamily: Font.body, color: c.textSecondary, textAlign: 'right' },
});
