import { Ionicons } from '@expo/vector-icons';
import { router } from 'expo-router';
import * as WebBrowser from 'expo-web-browser';
import { useCallback, useEffect, useState } from 'react';
import {
  Alert,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { GameDetail } from '@/components/game-detail';
import { PulseDetail } from '@/components/pulse-detail';
import { OfflineNotice } from '@/components/offline-notice';
import { BriefingSkeleton, PulseRowSkeleton, Skeleton } from '@/components/skeleton';
import { Card, RidgeMark, SectionLabel, Sparkline, SportIcon, TrendTag, Wordmark } from '@/components/ui';
import { Brand, Font, surfaces } from '@/constants/brand';
import { useAlerts } from '@/lib/alerts';
import { countdownLabel, daysUntil, easternDateShort, easternTime } from '@/lib/eastern';
import { useKickoffCountdown } from '@/lib/use-kickoff';
import { useForegroundRefresh } from '@/lib/use-foreground-refresh';
import { useFavorites } from '@/lib/favorites';
import { supabase } from '@/lib/supabase';
import { Briefing, Game } from '@/lib/types';

const c = surfaces(true);

const SPORT_NAME: Record<string, string> = {
  football: 'Football',
  mbb: "Men's Basketball",
  baseball: 'Baseball',
  // Not a sport — the briefing's athletics-wide section (sponsorships, facilities,
  // conference moves). Only ever appears as a briefing section, never in SPORT_ORDER,
  // so it can't leak into the Pulse rows below.
  program: 'WVU Athletics',
};
const SPORT_ORDER = ['football', 'mbb', 'baseball'];

type Driver = { label: string; delta?: number; kind: string };
type Snapshot = {
  sport_id: string;
  date: string;
  score: number;
  trend: string;
  ranking: number | null;
  explanation: string | null;
  drivers: Driver[] | null;
};
type Rec = { w: number; l: number; season: number };

// A story we interrupted people for. `summary` is written by the pipeline in our own words
// (see notify_news.py) so the news is readable here rather than behind the source's paywall.
type Breaking = {
  id: string;
  sport_id: string | null;
  headline: string;
  /** Written by the pipeline once it knows more than the source's teaser headline did.
   *  Null means it learned nothing extra, so the source's own headline stands. */
  summary_headline: string | null;
  source_name: string | null;
  url: string;
  summary: string | null;
  summary_section: string | null;
  notified_at: string | null;
};

// Outer bound on how long a breaking card can sit on the home screen. The real retirement
// rule is the next briefing (see `breaking` below) — this only catches the case where the
// briefing fails to run for a day, so a card can't get stranded there indefinitely.
const BREAKING_HOURS = 36;

// Where the change shows up in the app, for the "see it in the app" button. Matches the
// `summary_section` values notify_news.py writes.
// Which sub-view of the Team tab the story is reflected in. The Team tab opens on football's
// roster by default, so a basketball story has to say so explicitly or the button lands the
// reader on the wrong team with no hint of where to go next.
const SECTION_MODE: Record<string, string> = { movement: 'movement', roster: 'roster' };

function sectionButton(section: string, sport: string | null): { label: string; href: string } | null {
  const sportName = sport ? SPORT_TAG[sport] : null;
  if (section === 'scores') return { label: 'See the score', href: '/scores' };
  const mode = SECTION_MODE[section];
  if (!mode) return null;
  const what = mode === 'movement' ? 'roster moves' : 'roster';
  return {
    label: sportName ? `See ${sportName.toLowerCase()} ${what}` : `See the ${what}`,
    // Falls back to football only when the story has no sport, which is what the tab would
    // have shown anyway — never a silent wrong-team landing for a story that does have one.
    href: `/team?sport=${sport ?? 'football'}&mode=${mode}`,
  };
}

// A record is shown only while its season is actually being played. Out of season it's
// last year's news sitting under today's Pulse — WVU football read "4–8 · 2025" all
// summer. A sport qualifies if it has played a game in the last STALE_RECORD_DAYS; the
// longest in-season gap is a football bye at ~14 days, so 45 clears every real break
// while still hiding a season that has ended. Each sport lights up again on its own,
// the day after its opener, with no season-window table to maintain.
const STALE_RECORD_DAYS = 45;

function todayLabel() {
  return new Date().toLocaleDateString('en-US', {
    weekday: 'long',
    month: 'long',
    day: 'numeric',
  });
}

// Resample a sport's dated snapshots into ~30 daily points over the past month
// (carry-forward on quiet days), so the preview sparkline is a consistent 1-month timeline.
const DAY = 86400000;
function monthSeries(snaps: { date: string; score: number }[]): number[] {
  if (!snaps.length) return [];
  const parsed = snaps.map((s) => ({ t: new Date(s.date).getTime(), score: s.score }));
  const anchor = parsed[parsed.length - 1].t;
  const out: number[] = [];
  for (let i = 29; i >= 0; i--) {
    const st = anchor - i * DAY;
    let score: number | null = null;
    for (let j = parsed.length - 1; j >= 0; j--) {
      if (parsed[j].t <= st) {
        score = parsed[j].score;
        break;
      }
    }
    if (score != null) out.push(score);
  }
  return out;
}

export default function PulseScreen() {
  const insets = useSafeAreaInsets();
  const [snaps, setSnaps] = useState<Record<string, Snapshot>>({});
  const [records, setRecords] = useState<Record<string, Rec>>({});
  const [series, setSeries] = useState<Record<string, { date: string; score: number }[]>>({});
  const [briefing, setBriefing] = useState<Briefing | null>(null);
  const [breaking, setBreaking] = useState<Breaking | null>(null);
  const [nextGame, setNextGame] = useState<Game | null>(null);
  const [gameOpen, setGameOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [selectedSport, setSelectedSport] = useState<string | null>(null);
  const { favorites } = useFavorites();
  const { alertsOn, busy: bellBusy, enable, disable } = useAlerts();

  // The header bell doubles as a status light: filled/gold = alerts on, outline = off.
  // Tapping enables (priming the iOS prompt) or turns them back off; if permission was
  // denied at the OS level, point the user to Settings instead of silently failing.
  const toggleBell = async () => {
    if (bellBusy) return;
    if (alertsOn) {
      await disable();
    } else {
      const on = await enable();
      if (!on) {
        Alert.alert(
          'Turn on alerts',
          'Enable notifications for Mountaineer Pulse in your device Settings to get the morning briefing and breaking WVU news.',
        );
      }
    }
  };
  const orderedSports = [...SPORT_ORDER].sort(
    (a, b) => (favorites.includes(b) ? 1 : 0) - (favorites.includes(a) ? 1 : 0),
  );

  const load = useCallback(async () => {
    try {
    const [snapRes, briefingRes, gamesRes, nextRes, breakingRes] = await Promise.all([
      supabase.from('pulse_snapshots').select('*').order('date', { ascending: true }),
      supabase.from('daily_briefings').select('*').order('date', { ascending: false }).limit(1),
      // Only the last ~13 months: enough to cover any season in progress, and a record
      // older than that is never displayed anyway (see STALE_RECORD_DAYS). Avoids pulling
      // every finished game WVU has ever played on each home-screen load.
      supabase
        .from('games')
        .select('sport_id,season,home_points,away_points,is_wvu_home,start_date')
        .eq('status', 'final')
        .gte('start_date', new Date(Date.now() - 400 * 86400 * 1000).toISOString()),
      // Filtered by DATE, not just status: four baseball games from last March are still
      // marked 'scheduled', and ordering non-final games by date would have made a game
      // five months past the "next" one. A few are fetched so a game already under way
      // today still wins over tomorrow's.
      supabase
        .from('games')
        .select('*')
        .neq('status', 'final')
        .gte('start_date', new Date(Date.now() - 36 * 3600 * 1000).toISOString())
        .order('start_date', { ascending: true })
        .limit(5),
      // The story we last interrupted people for, while it's still recent. Shown at the top
      // of the home screen so it reaches everyone — including the people who never tapped
      // the notification, or never had alerts on in the first place.
      supabase
        .from('news_items')
        .select('id,sport_id,headline,summary_headline,source_name,url,summary,summary_section,notified_at')
        .not('notified_at', 'is', null)
        .gte('notified_at', new Date(Date.now() - BREAKING_HOURS * 3600 * 1000).toISOString())
        .order('notified_at', { ascending: false })
        .limit(1),
    ]);
    if (snapRes.error) throw snapRes.error; // no connection → show the offline state

    const brief = (briefingRes.data?.[0] as Briefing) ?? null;
    setBriefing(brief);

    // Retire the card once a briefing written AFTER the alert exists — at that point the
    // briefing below is carrying the same story, and leaving both up says it twice on one
    // screen. In practice a 5pm alert clears at the next 7am briefing.
    const hit = (breakingRes.data?.[0] as Breaking) ?? null;
    const supersededBy = brief?.generated_at ? new Date(brief.generated_at).getTime() : 0;
    const alertedAt = hit?.notified_at ? new Date(hit.notified_at).getTime() : 0;
    setBreaking(hit && alertedAt > supersededBy ? hit : null);

    const latest: Record<string, Snapshot> = {};
    const ser: Record<string, { date: string; score: number }[]> = {};
    for (const s of (snapRes.data ?? []) as Snapshot[]) {
      latest[s.sport_id] = s; // ascending → ends on newest
      (ser[s.sport_id] = ser[s.sport_id] || []).push({ date: s.date, score: s.score });
    }
    setSnaps(latest);
    setSeries(ser);

    // Win–loss for each sport's most recent season, kept only while that season is live.
    const games = (gamesRes.data ?? []) as {
      sport_id: string;
      season: number;
      home_points: number;
      away_points: number;
      is_wvu_home: boolean;
      start_date: string | null;
    }[];
    const rec: Record<string, Rec> = {};
    const latestSeason: Record<string, number> = {};
    const lastPlayed: Record<string, number> = {};
    for (const g of games) latestSeason[g.sport_id] = Math.max(latestSeason[g.sport_id] ?? 0, g.season);
    for (const g of games) {
      if (g.season !== latestSeason[g.sport_id]) continue;
      const wvu = g.is_wvu_home ? g.home_points : g.away_points;
      const opp = g.is_wvu_home ? g.away_points : g.home_points;
      const r = (rec[g.sport_id] = rec[g.sport_id] || { w: 0, l: 0, season: g.season });
      if ((wvu ?? 0) > (opp ?? 0)) r.w += 1;
      else r.l += 1;
      const t = g.start_date ? new Date(g.start_date).getTime() : 0;
      lastPlayed[g.sport_id] = Math.max(lastPlayed[g.sport_id] ?? 0, t);
    }
    // Drop any sport whose season has gone quiet, so the offseason shows no record at all
    // rather than last year's. Filtering here keeps the render free of the rule.
    const staleBefore = Date.now() - STALE_RECORD_DAYS * 86400 * 1000;
    for (const sport of Object.keys(rec)) {
      if ((lastPlayed[sport] ?? 0) < staleBefore) delete rec[sport];
    }
    setRecords(rec);
    // The first game that hasn't finished in Eastern terms — daysUntil is 0 all day on
    // game day, so the card keeps showing the game while it's being played.
    setNextGame(
      ((nextRes.data ?? []) as Game[]).find((g) => g.start_date && daysUntil(g.start_date) >= 0) ?? null,
    );
    setLoadError(false);
    } catch {
      setLoadError(true); // keep any data we already have; just flag the failure
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  // Refetch when the app returns to the foreground (e.g. tapping the morning-briefing
  // notification) so it never shows yesterday's briefing until a manual pull-to-refresh.
  useForegroundRefresh(load);

  // Is the briefing we're showing actually today's? Compared on LOCAL calendar date —
  // `new Date('2026-07-31')` parses as UTC midnight and reads as the previous day in
  // Eastern, which is the same trap that made the Pulse chart look a day behind.
  const now = new Date();
  const todayISO = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(
    now.getDate(),
  ).padStart(2, '0')}`;
  const briefingDay = (briefing?.date ?? '').slice(0, 10);
  const briefingStale = !!briefingDay && briefingDay !== todayISO;
  const briefingDateLabel = briefingStale
    ? (() => {
        const [y, m, d] = briefingDay.split('-').map(Number);
        return new Date(y, m - 1, d).toLocaleDateString(undefined, {
          month: 'short',
          day: 'numeric',
        });
      })()
    : '';

  const body = (
    <View style={{ flex: 1, backgroundColor: c.bg, paddingTop: insets.top + 10 }}>
      {/* Header — pinned above the scroll (stays put like the Team tab) */}
      <View style={styles.header}>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 10 }}>
          <RidgeMark size={34} />
          <View>
            <Wordmark size={17} />
            <Text style={styles.headerSub}>{todayLabel()} · Morgantown</Text>
          </View>
        </View>
        <Pressable
          onPress={toggleBell}
          disabled={bellBusy}
          hitSlop={10}
          style={({ pressed }) => [
            styles.bell,
            alertsOn && { backgroundColor: Brand.goldTint, borderColor: Brand.goldBorder },
            pressed && { opacity: 0.7 },
          ]}>
          <Ionicons
            name={alertsOn ? 'notifications' : 'notifications-outline'}
            size={17}
            color={alertsOn ? Brand.gold : c.textSecondary}
          />
        </Pressable>
      </View>

      <ScrollView
        style={{ backgroundColor: c.bg }}
        contentContainerStyle={styles.content}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={() => {
              setRefreshing(true);
              load();
            }}
            tintColor={Brand.gold}
          />
        }>
      {loading ? (
        <View>
          <View style={{ marginTop: 16 }}>
            <BriefingSkeleton />
          </View>
          <View style={styles.sectionRow}>
            <Skeleton width={150} height={18} radius={5} />
          </View>
          <View style={{ gap: 10 }}>
            <PulseRowSkeleton />
            <PulseRowSkeleton />
            <PulseRowSkeleton />
          </View>
        </View>
      ) : loadError && Object.keys(snaps).length === 0 ? (
        <OfflineNotice onRetry={() => { setLoading(true); load(); }} />
      ) : (
        <>
      {/* Breaking news, above everything. It's the newest thing on the screen and the only
          thing someone may have been interrupted for — it outranks even the next game. Gone
          on its own after BREAKING_HOURS. */}
      {breaking && (
        <BreakingCard
          item={breaking}
          onOpenSource={() => WebBrowser.openBrowserAsync(breaking.url)}
          onGoToSection={(route) => router.navigate(route as '/')}
        />
      )}

      {/* Next game. Sits above the briefing because it's the only thing here about what
          hasn't happened yet — everything below reports on what has. */}
      {nextGame && <NextGameCard game={nextGame} onOpen={() => setGameOpen(true)} />}

      {/* Daily briefing — per-sport sections when available, else plain text.
          We deliberately still show the most recent briefing when this morning's hasn't
          landed (better than an empty card), but we date it: the header above says
          "today", so an unlabelled stale briefing reads as today's news. */}
      {briefing && (
        <Card style={styles.briefing}>
          <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' }}>
            <SectionLabel>Daily Briefing</SectionLabel>
            {briefingStale ? <Text style={styles.briefStale}>{briefingDateLabel}</Text> : null}
          </View>
          {briefing.sections?.sections?.length ? (
            <>
              {briefing.sections.intro ? (
                <Text style={styles.briefingIntro}>{briefing.sections.intro}</Text>
              ) : null}
              {briefing.sections.sections.map((sec) => (
                <View key={sec.sport} style={styles.briefSport}>
                  <View style={styles.briefSportHead}>
                    <SportIcon sport={sec.sport} size={15} color={Brand.gold} />
                    <Text style={styles.briefSportName}>{SPORT_NAME[sec.sport] ?? sec.sport}</Text>
                  </View>
                  {sec.items.map((it, i) => (
                    <View key={i} style={styles.briefItem}>
                      <View style={styles.briefBullet} />
                      <View style={{ flex: 1 }}>
                        <Text style={styles.briefTopic}>{it.topic}</Text>
                        <Text style={styles.briefBody}>{it.body}</Text>
                      </View>
                    </View>
                  ))}
                </View>
              ))}
            </>
          ) : (
            <Text style={styles.briefingBody}>{briefing.content}</Text>
          )}
        </Card>
      )}

      {/* Program pulse */}
      <View style={styles.sectionRow}>
        <Text style={styles.sectionTitle}>Program Pulse</Text>
      </View>

      {orderedSports.map((sport) => {
        const s = snaps[sport];
        const rec = records[sport];
        const meta: string[] = [];
        if (rec) meta.push(`${rec.w}–${rec.l} · ${rec.season}`);
        if (s?.ranking) meta.push(`#${s.ranking}`);
        const scoreColor = (s?.score ?? 0) >= 60 ? Brand.gold : c.text;
        const sser = monthSeries(series[sport] ?? []);
        // Day-over-day change (today vs the prior point) — arrow shows only if it moved.
        const sdelta = sser.length >= 2 ? sser[sser.length - 1] - sser[sser.length - 2] : 0;
        const lineColor = sdelta > 0 ? Brand.green : sdelta < 0 ? Brand.red : c.textSecondary;
        const goldTile = sport !== 'mbb';
        return (
          <Pressable
            key={sport}
            onPress={() => setSelectedSport(sport)}
            style={({ pressed }) => [styles.sportCard, { opacity: pressed ? 0.75 : 1 }]}>
            <View
              style={[
                styles.tile,
                goldTile
                  ? { backgroundColor: Brand.goldTint, borderColor: Brand.goldBorder }
                  : { backgroundColor: 'rgba(159,180,206,0.07)', borderColor: 'rgba(159,180,206,0.14)' },
              ]}>
              <SportIcon sport={sport} size={22} color={goldTile ? Brand.gold : c.blueLabel} />
            </View>
            <View style={{ flex: 1 }}>
              <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
                {favorites.includes(sport) && <Ionicons name="star" size={13} color={Brand.gold} />}
                <Text style={styles.sportName}>{SPORT_NAME[sport]}</Text>
                {meta.length > 0 && <Text style={styles.sportMeta}>{meta.join(' · ')}</Text>}
              </View>
              {s?.drivers && s.drivers.length > 0 && (
                <View style={styles.driverRow}>
                  {s.drivers.slice(0, 2).map((d, i) => {
                    const pos = (d.delta ?? 0) >= 0;
                    // Ranking is a neutral status chip; everything else (incl. news)
                    // is colored by its signed delta — so bad news reads red.
                    const neutral = d.kind === 'rank';
                    return (
                      <View
                        key={i}
                        style={[
                          styles.driverChip,
                          {
                            backgroundColor: neutral
                              ? c.surface2
                              : pos
                                ? Brand.greenTint
                                : Brand.redTint,
                          },
                        ]}>
                        <Text
                          style={{
                            fontFamily: Font.bodyBold,
                            fontSize: 10,
                            color: neutral ? c.textSecondary : pos ? Brand.green : Brand.red,
                          }}>
                          {d.label}
                        </Text>
                      </View>
                    );
                  })}
                </View>
              )}
            </View>
            <Sparkline data={sser} color={lineColor} width={56} height={30} />
            <View style={{ alignItems: 'flex-end', minWidth: 40 }}>
              <Text style={[styles.sportScore, { color: scoreColor }]}>{s ? s.score : '—'}</Text>
              {s && sdelta !== 0 && (
                <View style={{ marginTop: 2 }}>
                  <TrendTag trend={sdelta > 0 ? 'up' : 'down'} delta={sdelta} />
                </View>
              )}
            </View>
          </Pressable>
        );
      })}

      <Text style={styles.footer}>Tap a program to see its Pulse over time, day by day.</Text>
        </>
      )}
      </ScrollView>
    </View>
  );

  return (
    <>
      {body}
      <PulseDetail sport={selectedSport} onClose={() => setSelectedSport(null)} />
      <GameDetail game={gameOpen ? nextGame : null} onClose={() => setGameOpen(false)} />
    </>
  );
}

const SPORT_TAG: Record<string, string> = { football: 'Football', mbb: 'Basketball', baseball: 'Baseball' };

/**
 * The story we last pushed an alert about, for as long as it's still news.
 *
 * This exists because tapping a notification used to dead-end. You'd read "WVU Basketball
 * player is no longer with the program" on your lock screen, open the app, and be left to
 * work out on your own that the story lived behind a headline on the News tab, which is
 * itself just a link to a paywall. Someone who installed the app yesterday had no chance.
 *
 * So the news comes to the reader instead: the actual story, in our own words, on the first
 * screen they see — with the source one tap away for anyone who wants it, and a pointer to
 * wherever in the app the change is reflected.
 *
 * It also reaches everyone who never tapped the alert, and everyone who has notifications
 * turned off entirely. That's most people, and they were getting nothing before.
 */
function BreakingCard({ item, onOpenSource, onGoToSection }: {
  item: Breaking;
  onOpenSource: () => void;
  onGoToSection: (route: string) => void;
}) {
  const jump = sectionButton(item.summary_section ?? '', item.sport_id);
  return (
    <Card style={styles.breaking}>
      <View style={styles.breakingTop}>
        <View style={styles.breakingPill}>
          <Text style={styles.breakingPillText}>BREAKING</Text>
        </View>
        <Text style={styles.breakingWhen}>
          {item.notified_at ? relativeHours(item.notified_at) : ''}
        </Text>
      </View>

      {/* Ours when we have it: the source's is often a teaser written to sell a
          subscription, and by the time the summary is written we know the actual news. */}
      <Text style={styles.breakingHeadline}>{item.summary_headline || item.headline}</Text>

      {/* Our own summary. Without it the card is just the headline again, which is the
          problem this card was built to solve. */}
      {item.summary ? <Text style={styles.breakingBody}>{item.summary}</Text> : null}

      <View style={styles.breakingActions}>
        {jump ? (
          <Pressable
            onPress={() => onGoToSection(jump.href)}
            style={({ pressed }) => [styles.breakingBtn, pressed && { opacity: 0.75 }]}>
            <Text style={styles.breakingBtnText}>{jump.label}</Text>
            <Ionicons name="arrow-forward" size={13} color={Brand.onGold} />
          </Pressable>
        ) : null}
        {/* Says where the tap goes. "Read more" would hide that this leaves the app. */}
        <Pressable
          onPress={onOpenSource}
          style={({ pressed }) => [styles.breakingLink, pressed && { opacity: 0.75 }]}>
          <Text style={styles.breakingLinkText}>
            Full story at {item.source_name ?? 'the source'}
          </Text>
          <Ionicons name="open-outline" size={13} color={Brand.gold} />
        </Pressable>
      </View>
    </Card>
  );
}

function relativeHours(iso: string): string {
  const mins = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (mins < 60) return `${Math.max(1, mins)}m ago`;
  const hrs = Math.round(mins / 60);
  return hrs < 24 ? `${hrs}h ago` : 'Yesterday';
}

/**
 * The next game, as a hook rather than a schedule row: who, when, where, how soon.
 * Tapping opens the same detail sheet the Scores tab uses.
 */
function NextGameCard({ game, onOpen }: { game: Game; onOpen: () => void }) {
  const iso = game.start_date ?? '';
  const home = !!game.is_wvu_home;
  const opponent = (home ? game.away_team : game.home_team).replace(
    /\s+(Mountaineers|Tar Heels|Trojans|Bears|Cowboys|Cyclones|Wildcats|Bearcats|Horned Frogs|Highlanders|Thundering Herd|Nittany Lions)$/i,
    '',
  );
  const { live, underway } = useKickoffCountdown(iso || null);
  const days = iso ? daysUntil(iso) : 1;
  // "Game day" is the last 24 hours, not the calendar date — a 12:00 kickoff is closer
  // at 11pm the night before than at 12:01am on a day that still counts as "Today".
  const isGameDay = days === 0 || !!live || underway;
  const kickoff = iso ? easternTime(iso) : null;
  // A kickoff the feed hasn't been given yet is stored as midnight Eastern; easternTime
  // returns null for it rather than printing "12:00 AM".
  const when = [iso ? easternDateShort(iso) : '', kickoff ?? 'Time TBA'].filter(Boolean).join(' · ');

  return (
    <Pressable onPress={onOpen} style={({ pressed }) => [pressed && { opacity: 0.75 }]}>
      <Card style={[styles.nextGame, isGameDay && styles.nextGameToday] as never}>
        <View style={styles.nextGameTop}>
          <SectionLabel>{isGameDay ? 'Game Day' : 'Next Up'}</SectionLabel>
          <View style={[styles.countPill, isGameDay && { backgroundColor: Brand.gold }]}>
            <Text
              style={[
                styles.countText,
                isGameDay && { color: '#0B1220' },
                // Seconds change every tick; fixed-width digits stop the pill twitching.
                !!live && { fontVariant: ['tabular-nums'] },
              ]}>
              {live ?? (underway ? 'Underway' : iso ? countdownLabel(iso) ?? '' : '')}
            </Text>
          </View>
        </View>

        <View style={styles.nextGameBody}>
          <View style={styles.nextGameTile}>
            <SportIcon sport={game.sport_id} size={22} color={Brand.gold} />
          </View>
          <View style={{ flex: 1 }}>
            <Text style={styles.nextGameOpp} numberOfLines={1}>
              <Text style={styles.nextGameVs}>{home ? 'vs ' : 'at '}</Text>
              {opponent}
            </Text>
            <Text style={styles.nextGameMeta} numberOfLines={1}>
              {when}
            </Text>
          </View>
          <Text style={styles.nextGameChevron}>›</Text>
        </View>

        <Text style={styles.nextGameWhere} numberOfLines={1}>
          {[game.venue, SPORT_TAG[game.sport_id] ?? game.sport_id].filter(Boolean).join(' · ')}
        </Text>
      </Card>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  center: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  content: { paddingHorizontal: 20, paddingBottom: 40 },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 20,
    paddingVertical: 8,
    marginBottom: 6,
  },
  headerSub: { fontFamily: Font.body, fontSize: 11, color: c.textMuted, marginTop: 3 },
  bell: {
    width: 34,
    height: 34,
    borderRadius: 17,
    backgroundColor: c.surface3,
    borderWidth: 1,
    borderColor: c.border,
    alignItems: 'center',
    justifyContent: 'center',
  },
  // Gold border rather than a gold fill: this card sits directly above the Next Up card, and
  // two solid gold blocks in a row make neither one read as urgent.
  breaking: { padding: 18, marginTop: 16, gap: 10, borderColor: Brand.gold, borderWidth: 1.5 },
  breakingTop: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  breakingPill: { backgroundColor: Brand.gold, borderRadius: 999, paddingHorizontal: 10, paddingVertical: 3 },
  breakingPillText: { fontFamily: Font.bodyBold, fontSize: 10, color: Brand.onGold, letterSpacing: 1 },
  breakingWhen: { fontFamily: Font.body, fontSize: 11.5, color: c.textMuted },
  breakingHeadline: { fontFamily: Font.display, fontSize: 18, color: c.text, lineHeight: 24, letterSpacing: -0.3 },
  breakingBody: { fontFamily: Font.body, fontSize: 14.5, color: c.textSecondary, lineHeight: 21 },
  breakingActions: { flexDirection: 'row', alignItems: 'center', flexWrap: 'wrap', gap: 10, marginTop: 2 },
  breakingBtn: { flexDirection: 'row', alignItems: 'center', gap: 6, backgroundColor: Brand.gold, borderRadius: 12, paddingHorizontal: 14, paddingVertical: 9 },
  breakingBtnText: { fontFamily: Font.displaySemi, fontSize: 13.5, color: Brand.onGold },
  breakingLink: { flexDirection: 'row', alignItems: 'center', gap: 5, paddingVertical: 9 },
  breakingLinkText: { fontFamily: Font.bodySemi, fontSize: 13, color: Brand.gold },
  nextGame: { padding: 18, marginTop: 16, gap: 14 },
  // Game day earns the gold edge; every other day stays quiet so it means something.
  nextGameToday: { borderColor: Brand.goldBorder, backgroundColor: Brand.goldTint },
  nextGameTop: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  countPill: { backgroundColor: Brand.goldTint, borderWidth: 1, borderColor: Brand.goldBorder, borderRadius: 8, paddingHorizontal: 9, paddingVertical: 4 },
  countText: { fontFamily: Font.bodyBold, fontSize: 11.5, color: Brand.gold, letterSpacing: 0.2 },
  nextGameBody: { flexDirection: 'row', alignItems: 'center', gap: 13 },
  nextGameTile: { width: 44, height: 44, borderRadius: 12, backgroundColor: Brand.goldTint, borderWidth: 1, borderColor: Brand.goldBorder, alignItems: 'center', justifyContent: 'center' },
  nextGameOpp: { fontFamily: Font.black, fontSize: 21, color: c.text, letterSpacing: -0.4 },
  nextGameVs: { fontFamily: Font.body, fontSize: 15, color: c.textSecondary, letterSpacing: 0 },
  nextGameMeta: { fontFamily: Font.bodySemi, fontSize: 13, color: Brand.gold, marginTop: 3 },
  nextGameChevron: { fontSize: 22, color: c.textMuted },
  nextGameWhere: { fontFamily: Font.body, fontSize: 12, color: c.textMuted },
  briefing: { padding: 18, marginTop: 16 },
  briefStale: { fontFamily: Font.body, fontSize: 11.5, color: c.textMuted, letterSpacing: 0.2 },
  briefingBody: { fontFamily: Font.body, fontSize: 14, lineHeight: 21, color: c.textSecondary, marginTop: 8 },
  briefingIntro: { fontFamily: Font.bodyMed, fontSize: 14, lineHeight: 21, color: c.text, marginTop: 10 },
  briefSport: { marginTop: 16 },
  briefSportHead: { flexDirection: 'row', alignItems: 'center', gap: 7, marginBottom: 8 },
  briefSportName: { fontFamily: Font.display, fontSize: 14, color: Brand.gold, letterSpacing: 0.2 },
  briefItem: { flexDirection: 'row', gap: 9, marginBottom: 10 },
  briefBullet: { width: 5, height: 5, borderRadius: 3, backgroundColor: Brand.gold, marginTop: 7 },
  briefTopic: { fontFamily: Font.bodyBold, fontSize: 13.5, color: c.text, marginBottom: 2 },
  briefBody: { fontFamily: Font.body, fontSize: 13, lineHeight: 19, color: c.textSecondary },
  sectionRow: { flexDirection: 'row', alignItems: 'center', marginTop: 22, marginBottom: 10 },
  sectionTitle: { fontFamily: Font.display, fontSize: 18, color: c.text, letterSpacing: -0.3 },
  sportCard: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    backgroundColor: c.card,
    borderWidth: 1,
    borderColor: c.border,
    borderRadius: 18,
    padding: 14,
    marginBottom: 10,
  },
  tile: { width: 44, height: 44, borderRadius: 12, borderWidth: 1, alignItems: 'center', justifyContent: 'center' },
  sportName: { fontFamily: Font.display, fontSize: 15, color: c.text },
  sportMeta: { fontFamily: Font.body, fontSize: 11, color: c.textMuted },
  driverRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 5, marginTop: 7 },
  driverChip: { paddingHorizontal: 8, paddingVertical: 3, borderRadius: 999 },
  sportScore: { fontFamily: Font.black, fontSize: 30, lineHeight: 32 },
  footer: { textAlign: 'center', marginTop: 16, fontSize: 12, color: c.textMuted, fontFamily: Font.body },
});
