import { useState } from 'react';
import { ActivityIndicator, Image, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';

import { Brand, Font, surfaces } from '@/constants/brand';
import { trackFeature } from '@/lib/analytics';
import { BOX_LABEL, DriveItem, GameSummary, PlayItem, periodLabel } from '@/lib/game-summary';
import { useGameSummary } from '@/lib/use-game-summary';
import { LiveGame } from '@/lib/live-game-parse';
import { Game } from '@/lib/types';

const c = surfaces(true);

/**
 * The scoreboard, box score, play-by-play and team stats for a game that has started.
 *
 * Two feeds, on purpose. The scoreboard line reads from the live card's poll — 2.3 KB every
 * twenty seconds — because a score that lags reads as broken. Everything below it comes
 * from the 178 KB summary on a 90-second tick, because a tackle count that lags by a minute
 * reads as fine, and polling that fast would cost tens of megabytes an hour. See
 * use-game-summary.ts.
 *
 * The whole block renders nothing before kickoff: there is no box score for a game that
 * hasn't happened, and an empty table is worse than the countdown it would replace.
 */

const TABS = [
  { id: 'summary', label: 'Summary' },
  { id: 'box', label: 'Box Score' },
  { id: 'plays', label: 'Plays' },
  { id: 'team', label: 'Team Stats' },
] as const;

type TabId = (typeof TABS)[number]['id'];

export function GameLive({ game, live }: { game: Game; live: LiveGame | null }) {
  const [tab, setTab] = useState<TabId>('summary');
  const eventId = game.espn_event_id ?? null;
  const wvuHome = !!game.is_wvu_home;
  const { summary, loading, failed, refresh } = useGameSummary(eventId, wvuHome, true);

  if (!eventId) return null;

  // Before the first snap there is nothing here worth a tab bar.
  const started = live ? live.state !== 'pre' : summary?.state !== 'pre';
  if (!started && !summary) return null;
  if (summary && summary.state === 'pre') return null;

  // The scoreboard prefers the fast feed and falls back to the summary, so the header is
  // populated on the very first render rather than after the 178 KB round trip.
  const wvuScore = live?.wvuScore ?? summary?.wvuScore ?? null;
  const oppScore = live?.oppScore ?? summary?.oppScore ?? null;
  const detail = live?.detail || summary?.detail || '';
  const isLive = (live?.state ?? summary?.state) === 'in';

  return (
    <View>
      <Scoreboard
        summary={summary}
        game={game}
        wvuScore={wvuScore}
        oppScore={oppScore}
        detail={detail}
        isLive={isLive}
        downDistance={live?.downDistance ?? null}
        fieldPosition={live?.fieldPosition ?? null}
      />

      <View style={styles.tabs}>
        {TABS.map((t) => {
          const on = tab === t.id;
          return (
            <Pressable
              key={t.id}
              onPress={() => { trackFeature('game_tab_switch'); setTab(t.id); }}
              style={[styles.tab, on && styles.tabOn]}>
              <Text style={[styles.tabText, { color: on ? Brand.onGold : c.textSecondary }]}>
                {t.label}
              </Text>
            </Pressable>
          );
        })}
      </View>

      {loading && !summary ? (
        <View style={styles.loading}>
          <ActivityIndicator color={Brand.gold} />
        </View>
      ) : failed && !summary ? (
        <Pressable onPress={refresh} style={styles.card} hitSlop={8}>
          <Text style={styles.empty}>
            Couldn&apos;t reach the live feed. Tap to try again.
          </Text>
        </Pressable>
      ) : !summary ? null : (
        <>
          {tab === 'summary' && <SummaryTab s={summary} live={live} />}
          {tab === 'box' && <BoxTab s={summary} />}
          {tab === 'plays' && <PlaysTab s={summary} />}
          {tab === 'team' && <TeamTab s={summary} />}
        </>
      )}
    </View>
  );
}

/* ---------------- scoreboard ---------------- */

function Scoreboard({
  summary,
  game,
  wvuScore,
  oppScore,
  detail,
  isLive,
  downDistance,
  fieldPosition,
}: {
  summary: GameSummary | null;
  game: Game;
  wvuScore: number | null;
  oppScore: number | null;
  detail: string;
  isLive: boolean;
  downDistance: string | null;
  fieldPosition: string | null;
}) {
  const wvuHome = !!game.is_wvu_home;
  const wvuName = summary?.wvuName ?? 'WVU';
  const oppName = summary?.oppName ?? (wvuHome ? game.away_team : game.home_team);
  const leading = (wvuScore ?? 0) > (oppScore ?? 0);
  const trailing = (oppScore ?? 0) > (wvuScore ?? 0);

  return (
    <View style={styles.board}>
      <View style={styles.boardRow}>
        <Side
          name={wvuName}
          logo={summary?.wvuLogo ?? null}
          score={wvuScore}
          dim={trailing}
        />
        <View style={styles.boardMid}>
          {isLive && (
            <View style={styles.liveRow}>
              <View style={styles.liveDot} />
              {/* Not "LIVE": ESPN trails the broadcast by about half a minute, and the
                  broadcast trails the stadium. Same wording as the home card. */}
              <Text style={styles.liveWord}>TRACKING</Text>
            </View>
          )}
          <Text style={styles.clock}>{detail || '—'}</Text>
          {!!downDistance && <Text style={styles.down}>{downDistance}</Text>}
          {!!fieldPosition && <Text style={styles.ball}>{fieldPosition}</Text>}
        </View>
        <Side
          name={oppName}
          logo={summary?.oppLogo ?? null}
          score={oppScore}
          dim={leading}
          right
        />
      </View>

      {/* Quarter-by-quarter, once there is more than one to compare. */}
      {summary && summary.wvuLine.length > 1 && (
        <View style={styles.lineTable}>
          <View style={styles.lineRow}>
            <Text style={[styles.lineTeam, styles.lineHead]} />
            {summary.wvuLine.map((_, i) => (
              <Text key={i} style={[styles.lineCell, styles.lineHead]}>{periodLabel(i + 1)}</Text>
            ))}
            <Text style={[styles.lineCell, styles.lineHead]}>T</Text>
          </View>
          <LineRow abbr={summary.wvuAbbr} line={summary.wvuLine} total={summary.wvuScore} bold />
          <LineRow abbr={summary.oppAbbr} line={summary.oppLine} total={summary.oppScore} />
        </View>
      )}
    </View>
  );
}

function Side({
  name,
  logo,
  score,
  dim,
  right,
}: {
  name: string;
  logo: string | null;
  score: number | null;
  dim: boolean;
  right?: boolean;
}) {
  return (
    <View style={[styles.side, right && { alignItems: 'flex-end' }]}>
      {logo ? (
        <Image source={{ uri: logo }} style={styles.logo} resizeMode="contain" />
      ) : (
        <View style={styles.logo} />
      )}
      <Text style={styles.sideName} numberOfLines={1}>{name}</Text>
      <Text style={[styles.sideScore, dim && { color: c.textSecondary }]}>
        {score ?? '—'}
      </Text>
    </View>
  );
}

function LineRow({
  abbr,
  line,
  total,
  bold,
}: {
  abbr: string;
  line: string[];
  total: number | null;
  bold?: boolean;
}) {
  return (
    <View style={styles.lineRow}>
      <Text style={[styles.lineTeam, bold && { color: Brand.gold }]}>{abbr}</Text>
      {line.map((v, i) => (
        <Text key={i} style={styles.lineCell}>{v}</Text>
      ))}
      <Text style={[styles.lineCell, styles.lineTotal]}>{total ?? '—'}</Text>
    </View>
  );
}

/* ---------------- tabs ---------------- */

function SummaryTab({ s, live }: { s: GameSummary; live: LiveGame | null }) {
  // Between drives — halftime, after a punt, at the final — there is no current one, and
  // the drive that just ended is the thing worth showing. Labeled for which it is, because
  // "Current Drive" over a finished kneel-down at halftime is how this read before.
  const currentDrive = s.drives.find((d) => d.current);
  const shownDrive = currentDrive ?? s.drives[0] ?? null;
  const lastPlay = live?.lastPlay || s.drives[0]?.plays.slice(-1)[0]?.text || null;

  return (
    <View>
      {shownDrive && (
        <>
          <Label>{currentDrive ? 'Current Drive' : 'Last Drive'}</Label>
          <View style={styles.card}>
            <View style={styles.scoreHeadRow}>
              <Text style={styles.driveTeam}>{shownDrive.team}</Text>
              {!currentDrive && !!shownDrive.result && (
                <Text style={[styles.driveResult, shownDrive.isScore && { color: Brand.gold }]}>
                  {shownDrive.result}
                </Text>
              )}
            </View>
            <Text style={styles.driveDesc}>
              {shownDrive.description || (currentDrive ? 'Just started' : '')}
            </Text>
          </View>
        </>
      )}

      {!!lastPlay && (
        <>
          <Label>Last Play</Label>
          <View style={styles.card}>
            <Text style={styles.playText}>{lastPlay}</Text>
          </View>
        </>
      )}

      <Label>Scoring</Label>
      {s.scoringPlays.length === 0 ? (
        <View style={styles.card}>
          <Text style={styles.empty}>No scoring yet.</Text>
        </View>
      ) : (
        s.scoringPlays.map((p) => (
          <View key={p.id} style={styles.card}>
            <View style={styles.scoreHeadRow}>
              <Text style={styles.playWhen}>
                {periodLabel(p.period)}{p.clock ? ` · ${p.clock}` : ''}
              </Text>
              <Text style={styles.runningScore}>
                {s.wvuAbbr} {p.wvuScore ?? '—'} · {s.oppAbbr} {p.oppScore ?? '—'}
              </Text>
            </View>
            <Text style={styles.playText}>{p.text}</Text>
          </View>
        ))
      )}
    </View>
  );
}

function BoxTab({ s }: { s: GameSummary }) {
  if (!s.box.length) {
    return <View style={styles.card}><Text style={styles.empty}>No box score yet.</Text></View>;
  }
  return (
    <View>
      {s.box.map((t) => (
        <View key={t.team}>
          <Label>{t.isWvu ? 'West Virginia' : t.team}</Label>
          {t.categories.length === 0 ? (
            <View style={styles.card}><Text style={styles.empty}>Nothing recorded yet.</Text></View>
          ) : (
            t.categories.map((cat) => (
              <View key={cat.name} style={styles.statBlock}>
                <Text style={styles.statTitle}>{BOX_LABEL[cat.name] ?? cat.name}</Text>
                {/* Ten defensive columns do not fit a phone; the name column stays put and
                    the numbers scroll under it. */}
                <ScrollView horizontal showsHorizontalScrollIndicator={false}>
                  <View>
                    <View style={styles.statRow}>
                      <Text style={[styles.statName, styles.statHead]}>PLAYER</Text>
                      {cat.labels.map((l, i) => (
                        <Text key={i} style={[styles.statCell, styles.statHead]}>{l}</Text>
                      ))}
                    </View>
                    {cat.athletes.map((a, i) => (
                      <View
                        key={`${a.name}-${i}`}
                        style={[styles.statRow, i === cat.athletes.length - 1 && { borderBottomWidth: 0 }]}>
                        <Text style={styles.statName} numberOfLines={1}>{a.name}</Text>
                        {cat.labels.map((_, j) => (
                          <Text key={j} style={styles.statCell}>{a.stats[j] ?? '—'}</Text>
                        ))}
                      </View>
                    ))}
                  </View>
                </ScrollView>
              </View>
            ))
          )}
        </View>
      ))}
    </View>
  );
}

function PlaysTab({ s }: { s: GameSummary }) {
  if (!s.hasPlays) {
    return <View style={styles.card}><Text style={styles.empty}>No plays yet.</Text></View>;
  }
  return (
    <View>
      {s.drives.map((d) => <Drive key={d.id} drive={d} s={s} />)}
    </View>
  );
}

function Drive({ drive, s }: { drive: DriveItem; s: GameSummary }) {
  // The current drive and the one that just ended open by default; older ones stay shut so
  // a four-hour game isn't a mile of scrolling to reach what just happened.
  const [open, setOpen] = useState(drive.current || drive.isScore);
  return (
    <View style={styles.driveBlock}>
      <Pressable onPress={() => setOpen((v) => !v)} style={styles.driveHead} hitSlop={6}>
        <View style={[styles.driveBar, { backgroundColor: drive.isWvu ? Brand.gold : c.border }]} />
        <View style={{ flex: 1 }}>
          <Text style={styles.driveTeam}>
            {drive.team}
            {drive.current ? ' · in progress' : ''}
          </Text>
          <Text style={styles.driveDesc}>{drive.description}</Text>
        </View>
        <Text style={[styles.driveResult, drive.isScore && { color: Brand.gold }]}>
          {drive.result}
        </Text>
      </Pressable>
      {open &&
        drive.plays.map((p) => <Play key={p.id} play={p} s={s} />)}
    </View>
  );
}

function Play({ play, s }: { play: PlayItem; s: GameSummary }) {
  return (
    <View style={[styles.playRow, play.scoringPlay && styles.playScoring]}>
      <View style={styles.playMeta}>
        <Text style={styles.playWhen}>
          {periodLabel(play.period)}{play.clock ? ` ${play.clock}` : ''}
        </Text>
        {!!play.downDistance && (
          <Text style={styles.playDown} numberOfLines={1}>{play.downDistance}</Text>
        )}
      </View>
      <View style={{ flex: 1 }}>
        <Text style={styles.playText}>{play.text}</Text>
        {play.scoringPlay && (
          <Text style={styles.runningScore}>
            {s.wvuAbbr} {play.wvuScore ?? '—'} · {s.oppAbbr} {play.oppScore ?? '—'}
          </Text>
        )}
      </View>
    </View>
  );
}

function TeamTab({ s }: { s: GameSummary }) {
  if (!s.teamStats.length) {
    return <View style={styles.card}><Text style={styles.empty}>No team stats yet.</Text></View>;
  }
  return (
    <View style={styles.table}>
      <View style={styles.tRow}>
        <Text style={[styles.tCell, styles.tHead, { color: Brand.gold }]}>{s.wvuAbbr}</Text>
        <Text style={[styles.tLabel, styles.tHead]} />
        <Text style={[styles.tCell, styles.tHead]}>{s.oppAbbr}</Text>
      </View>
      {s.teamStats.map((r, i) => (
        <View key={r.label} style={[styles.tRow, i === s.teamStats.length - 1 && { borderBottomWidth: 0 }]}>
          <Text style={[styles.tCell, { color: Brand.gold }]}>{r.wvu || '—'}</Text>
          <Text style={styles.tLabel}>{r.label}</Text>
          <Text style={styles.tCell}>{r.opp || '—'}</Text>
        </View>
      ))}
    </View>
  );
}

function Label({ children }: { children: string }) {
  return <Text style={styles.label}>{children.toUpperCase()}</Text>;
}

const styles = StyleSheet.create({
  board: { backgroundColor: c.card, borderWidth: 1, borderColor: c.border, borderRadius: 16, padding: 16, marginTop: 4 },
  boardRow: { flexDirection: 'row', alignItems: 'center' },
  boardMid: { flex: 1.1, alignItems: 'center', paddingHorizontal: 6 },
  side: { flex: 1, alignItems: 'flex-start' },
  logo: { width: 34, height: 34, marginBottom: 5 },
  sideName: { fontFamily: Font.bodySemi, fontSize: 11.5, color: c.textSecondary },
  sideScore: { fontFamily: Font.black, fontSize: 32, color: c.text, letterSpacing: -1, fontVariant: ['tabular-nums'] },
  liveRow: { flexDirection: 'row', alignItems: 'center', gap: 5, marginBottom: 3 },
  liveDot: { width: 7, height: 7, borderRadius: 4, backgroundColor: Brand.red },
  liveWord: { fontFamily: Font.bodyBold, fontSize: 9, letterSpacing: 1, color: Brand.red },
  clock: { fontFamily: Font.bodyBold, fontSize: 13, color: c.text, textAlign: 'center' },
  down: { fontFamily: Font.bodySemi, fontSize: 12, color: Brand.gold, marginTop: 3, textAlign: 'center' },
  ball: { fontFamily: Font.body, fontSize: 11.5, color: c.textSecondary, marginTop: 1, textAlign: 'center' },

  lineTable: { marginTop: 14, borderTopWidth: 1, borderTopColor: c.border, paddingTop: 8 },
  lineRow: { flexDirection: 'row', alignItems: 'center', paddingVertical: 3 },
  lineTeam: { width: 46, fontFamily: Font.bodyBold, fontSize: 11.5, color: c.textSecondary },
  lineCell: { flex: 1, textAlign: 'center', fontFamily: Font.bodySemi, fontSize: 12.5, color: c.text, fontVariant: ['tabular-nums'] },
  lineHead: { fontFamily: Font.bodyBold, fontSize: 9.5, color: c.textMuted, letterSpacing: 0.6 },
  lineTotal: { color: c.text, fontFamily: Font.bodyBold },

  tabs: { flexDirection: 'row', gap: 5, marginTop: 16 },
  tab: { flex: 1, paddingVertical: 7, borderRadius: 10, alignItems: 'center', justifyContent: 'center', backgroundColor: c.card, borderWidth: 1, borderColor: c.border },
  tabOn: { backgroundColor: Brand.gold, borderColor: Brand.gold },
  tabText: { fontSize: 11.5, fontFamily: Font.bodyBold },

  loading: { paddingVertical: 32, alignItems: 'center' },
  label: { fontFamily: Font.bodyBold, fontSize: 10.5, letterSpacing: 1.2, color: Brand.gold, marginTop: 18, marginBottom: 7 },
  card: { backgroundColor: c.card, borderWidth: 1, borderColor: c.border, borderRadius: 12, padding: 13, marginTop: 8 },
  empty: { fontFamily: Font.body, fontSize: 13, color: c.textSecondary, textAlign: 'center' },

  scoreHeadRow: { flexDirection: 'row', justifyContent: 'space-between', marginBottom: 5 },
  playWhen: { fontFamily: Font.bodyBold, fontSize: 10.5, color: Brand.gold, letterSpacing: 0.4 },
  runningScore: { fontFamily: Font.bodySemi, fontSize: 11, color: c.textSecondary, marginTop: 4, fontVariant: ['tabular-nums'] },
  playText: { fontFamily: Font.body, fontSize: 13, lineHeight: 19, color: c.text },

  statBlock: { marginTop: 10, backgroundColor: c.card, borderWidth: 1, borderColor: c.border, borderRadius: 12, paddingHorizontal: 13, paddingVertical: 10 },
  statTitle: { fontFamily: Font.displaySemi, fontSize: 14, color: c.text, marginBottom: 6 },
  statRow: { flexDirection: 'row', alignItems: 'center', paddingVertical: 7, borderBottomWidth: 1, borderBottomColor: c.border },
  statName: { width: 132, fontFamily: Font.bodyMed, fontSize: 12.5, color: c.text, paddingRight: 8 },
  statCell: { width: 52, textAlign: 'right', fontFamily: Font.bodySemi, fontSize: 12.5, color: c.text, fontVariant: ['tabular-nums'] },
  statHead: { fontFamily: Font.bodyBold, fontSize: 9.5, color: c.textMuted, letterSpacing: 0.6 },

  driveBlock: { marginTop: 10, backgroundColor: c.card, borderWidth: 1, borderColor: c.border, borderRadius: 12, overflow: 'hidden' },
  driveHead: { flexDirection: 'row', alignItems: 'center', gap: 10, padding: 12 },
  driveBar: { width: 3, alignSelf: 'stretch', borderRadius: 2 },
  driveTeam: { fontFamily: Font.displaySemi, fontSize: 13.5, color: c.text },
  driveDesc: { fontFamily: Font.body, fontSize: 11.5, color: c.textSecondary, marginTop: 1 },
  driveResult: { fontFamily: Font.bodyBold, fontSize: 11, color: c.textSecondary, textAlign: 'right', maxWidth: 96 },
  playRow: { flexDirection: 'row', gap: 10, paddingHorizontal: 12, paddingVertical: 9, borderTopWidth: 1, borderTopColor: c.border },
  playScoring: { backgroundColor: Brand.goldTint },
  playMeta: { width: 72 },
  playDown: { fontFamily: Font.body, fontSize: 10.5, color: c.textMuted, marginTop: 2 },

  table: { backgroundColor: c.card, borderWidth: 1, borderColor: c.border, borderRadius: 16, paddingHorizontal: 14, marginTop: 10 },
  tRow: { flexDirection: 'row', alignItems: 'center', paddingVertical: 11, borderBottomWidth: 1, borderBottomColor: c.border },
  tCell: { width: 62, textAlign: 'center', fontFamily: Font.bodyBold, fontSize: 13.5, color: c.text, fontVariant: ['tabular-nums'] },
  tLabel: { flex: 1, textAlign: 'center', fontFamily: Font.body, fontSize: 12, color: c.textSecondary },
  tHead: { fontFamily: Font.bodyBold, fontSize: 10, color: c.textMuted, letterSpacing: 0.6 },
});
