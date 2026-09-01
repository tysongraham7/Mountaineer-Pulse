/**
 * Rehearse the game-day card against a real, finished game.
 *
 * The problem this solves: the live card can only be exercised for about three hours a week,
 * during the one window where being wrong is most expensive and least fixable. notify_games.py
 * has `--at` for the same reason — there is no way to rehearse a Saturday on a Tuesday unless
 * you build one.
 *
 * So: walk a completed game's real play-by-play from ESPN, feed each play through the SAME
 * parseLive() the app ships, and print the card's three lines for every one. Anything the
 * parser gets wrong — a backwards yard line, a down that survives into a final score, a
 * possession flip it misses on a punt — shows up here as a wrong line of text.
 *
 * Usage (no build step; Node 24 strips the types). `.mts` so node treats it as a module
 * without a "type" field in package.json, which Expo's own tooling reads:
 *     node scripts/rehearse-live.mts                 # last completed WVU game
 *     node scripts/rehearse-live.mts <espnEventId>   # a specific game
 *     node scripts/rehearse-live.mts <id> --all      # every play, not a sample
 *
 * Node prints a MODULE_TYPELESS_PACKAGE_JSON warning about the imported .ts file on every
 * run. It is noise, not a failure — the fix it suggests is adding "type": "module" to
 * package.json, which would break Expo's own CommonJS config files. Ignore it.
 */

import { parseLive, type ParseOpts, type Situation } from '../src/lib/live-game-parse.ts';

const CFB = 'sports.core.api.espn.com/v2/sports/football/leagues/college-football';
const CORE = `https://${CFB}`;
const SITE = 'https://site.api.espn.com/apis/site/v2/sports/football/college-football';
const WVU = '277';

/** ESPN 403s browser-impersonating agents; an honest one is allowed. See sync_espn.py. */
const UA = { 'User-Agent': 'MountaineerPulse/1.0 (+https://github.com/tysongraham/mountaineer-pulse)' };

async function get(url: string): Promise<any> {
  const r = await fetch(url.replace(/^http:/, 'https:'), { headers: UA });
  if (!r.ok) throw new Error(`HTTP ${r.status} for ${url}`);
  return r.json();
}

/**
 * A team's short name for display. The schedule endpoint offers shortDisplayName; the summary
 * header does not, and carries `location` ("Kansas") instead — so a lookup by event id printed
 * a whole game as "Opponent" until this checked both.
 */
function shortName(team: any): string {
  return team?.shortDisplayName ?? team?.location ?? team?.displayName ?? 'Opponent';
}

/** Most recent completed WVU football game, so the script works with no arguments. */
async function lastCompletedGame(): Promise<{ id: string; name: string; wvuHome: boolean; opp: string }> {
  for (const season of [new Date().getFullYear(), new Date().getFullYear() - 1]) {
    const data = await get(`${SITE}/teams/${WVU}/schedule?season=${season}`);
    const done = (data.events ?? []).filter((e: any) => e.competitions[0].status.type.completed);
    if (!done.length) continue;
    const ev = done[done.length - 1];
    const comp = ev.competitions[0];
    const home = comp.competitors.find((c: any) => c.homeAway === 'home');
    const away = comp.competitors.find((c: any) => c.homeAway === 'away');
    const wvuHome = String(home.team.id) === WVU;
    return {
      id: String(ev.id),
      name: ev.name,
      wvuHome,
      opp: shortName((wvuHome ? away : home).team),
    };
  }
  throw new Error('No completed WVU football game found in the last two seasons.');
}

/**
 * Every play of the game, in order. Paged because a football game is ~180 plays and the core
 * API hands them back 25 at a time.
 */
async function allPlays(eventId: string): Promise<any[]> {
  const base = `${CORE}/events/${eventId}/competitions/${eventId}/plays`;
  const first = await get(`${base}?limit=100`);
  const pages = [first];
  for (let page = 2; page <= (first.pageCount ?? 1); page++) {
    pages.push(await get(`${base}?limit=100&page=${page}`));
  }
  return pages.flatMap((p) => p.items ?? []);
}

/**
 * Reconstruct the `situation` resource as it would have looked right after this play.
 *
 * ESPN only serves the CURRENT situation, so a finished game has exactly one — useless for a
 * replay. But a play's `end` block holds the same four fields the situation carries (down,
 * distance, yard line, and the team that ended up with the ball), which is precisely the state
 * the next snap starts from. Rebuilding it here is what lets a November game stand in for a
 * live one.
 */
function situationAfter(play: any): Situation {
  const end = play.end ?? {};
  return {
    down: end.down,
    distance: end.distance,
    yardLine: end.yardLine,
    isRedZone: typeof end.yardsToEndzone === 'number' && end.yardsToEndzone <= 20,
    possession: end.team?.$ref,
    lastPlay: { $ref: play.$ref },
  };
}

function statusAt(play: any, final: boolean): Record<string, unknown> {
  const period = play.period?.number ?? 0;
  return {
    period,
    displayClock: play.clock?.displayValue ?? '',
    type: final
      ? { state: 'post', shortDetail: 'Final', description: 'Final' }
      : { state: 'in', shortDetail: `Q${period}`, description: `${period} Quarter` },
  };
}

const main = async () => {
  const args = process.argv.slice(2);
  const showAll = args.includes('--all');
  const explicitId = args.find((a) => /^\d+$/.test(a));

  const game = explicitId
    ? { id: explicitId, name: `event ${explicitId}`, wvuHome: true, opp: 'Opponent' }
    : await lastCompletedGame();

  if (explicitId) {
    // Resolve the sides properly rather than assuming, since scores are read by home/away.
    const summary = await get(`${SITE}/summary?event=${explicitId}`);
    const comp = summary.header?.competitions?.[0];
    const home = comp?.competitors?.find((c: any) => c.homeAway === 'home');
    const away = comp?.competitors?.find((c: any) => c.homeAway === 'away');
    game.wvuHome = String(home?.team?.id) === WVU;
    game.opp = shortName((game.wvuHome ? away : home)?.team);
    game.name = `${away?.team?.displayName} at ${home?.team?.displayName}`;
  }

  const opts: ParseOpts = { wvuHome: game.wvuHome, wvuAbbr: 'WVU', oppAbbr: game.opp };
  console.log(`\n  ${game.name}`);
  console.log(`  ESPN event ${game.id} — WVU is ${game.wvuHome ? 'home' : 'away'}\n`);

  const plays = await allPlays(game.id);
  console.log(`  ${plays.length} plays\n${'-'.repeat(78)}`);

  // A sample by default: the opening drive, a middle stretch, and the finish. Enough to see
  // both halves and both teams with the ball without 180 lines of output.
  const picked = showAll
    ? plays.map((_, i) => i)
    : [...plays.keys()].filter(
        (i) => i < 6 || (i > plays.length / 2 && i < plays.length / 2 + 6) || i >= plays.length - 6,
      );

  for (const i of picked) {
    // Mark where the sample skipped ahead, so a gap in the clock doesn't read as a bug.
    if (!showAll && i > 0 && !picked.includes(i - 1)) console.log(`  ${'.'.repeat(20)}`);
    const play = plays[i];
    const final = i === plays.length - 1;
    const card = parseLive(statusAt(play, final), situationAfter(play), play, opts);

    const score =
      card.wvuScore === null ? '—' : `WVU ${card.wvuScore} · ${game.opp} ${card.oppScore}`;
    // Mirrors the card's own guard: the whole situation line is suppressed without a down,
    // so a coin toss can't surface a bare "· Red zone" with nothing to attach it to. Keeping
    // the two in step is the point — a rehearsal that renders differently proves nothing.
    const possession =
      card.wvuHasBall === null ? null : card.wvuHasBall ? 'WVU ball' : `${game.opp} ball`;
    const situation = card.downDistance
      ? [
          possession,
          [card.downDistance, card.fieldPosition ? `at ${card.fieldPosition}` : null]
            .filter(Boolean)
            .join(' '),
        ]
          .filter(Boolean)
          .join(' · ') + (card.isRedZone ? '  · Red zone' : '')
      : '';

    console.log(
      `\n  [${card.detail}${card.clock ? ' ' + card.clock : ''}]  ${score}` +
        `${situation.trim() ? `\n  ${situation}` : ''}` +
        `\n  ${(card.lastPlay ?? '').slice(0, 96)}`,
    );
  }

  // The one assertion worth making automatically: the final score the card would show has to
  // match the score ESPN reports for the game. If the home/away mapping is inverted, every
  // other line above still looks plausible and this is the line that catches it.
  const summary = await get(`${SITE}/summary?event=${game.id}`);
  const comps = summary.header?.competitions?.[0]?.competitors ?? [];
  const truth = comps.find((c: any) => String(c.team.id) === WVU)?.score;
  const last = parseLive(
    statusAt(plays[plays.length - 1], true),
    situationAfter(plays[plays.length - 1]),
    plays[plays.length - 1],
    opts,
  );
  console.log(`\n${'-'.repeat(78)}`);
  const ok = truth != null && Number(truth) === last.wvuScore;
  console.log(
    `  WVU final: card says ${last.wvuScore}, ESPN says ${truth}  ${ok ? '[OK]' : '[MISMATCH]'}\n`,
  );
  if (!ok) process.exitCode = 1;
};

main().catch((e) => {
  console.error(`\n[X] ${e.message}\n`);
  process.exitCode = 1;
});
