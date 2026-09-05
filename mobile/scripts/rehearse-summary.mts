/**
 * Rehearse the game sheet's box score, play-by-play and team stats against a real game.
 *
 * Same idea, and the same reason, as rehearse-live.mts: this code only runs during a game,
 * which is exactly when nobody can fix it. So feed the SAME parseSummary() the app ships a
 * real summary payload and print what each tab would render. A column that lands under the
 * wrong header, a team split onto the wrong side, a drive with no plays — all of it shows
 * up here as wrong text instead of as a wrong screen on a Saturday.
 *
 * Usage (no build step; Node 24 strips the types):
 *     node scripts/rehearse-summary.mts                 # last completed WVU game
 *     node scripts/rehearse-summary.mts <espnEventId>   # a specific game, live or finished
 *
 * The MODULE_TYPELESS_PACKAGE_JSON warning is noise — see the note in rehearse-live.mts.
 */

import { parseSummary, BOX_LABEL, periodLabel } from '../src/lib/game-summary.ts';

const SITE = 'https://site.api.espn.com/apis/site/v2/sports/football/college-football';
const WVU = '277';
const UA = { 'User-Agent': 'MountaineerPulse/1.0 (+https://github.com/tysongraham7/Mountaineer-Pulse)' };

async function json(url: string) {
  const r = await fetch(url, { headers: UA });
  if (!r.ok) throw new Error(`${r.status} ${url}`);
  return r.json() as Promise<Record<string, unknown>>;
}

async function lastCompleted(): Promise<string> {
  const seasons = [2026, 2025];
  for (const season of seasons) {
    const s = await json(`${SITE}/teams/${WVU}/schedule?season=${season}`);
    const events = (s.events ?? []) as Record<string, unknown>[];
    for (const ev of [...events].reverse()) {
      const comp = ((ev.competitions ?? []) as Record<string, unknown>[])[0];
      const status = (comp?.status ?? {}) as Record<string, unknown>;
      const type = (status.type ?? {}) as Record<string, unknown>;
      if (type.completed) return String(ev.id);
    }
  }
  throw new Error('no completed WVU game found');
}

const arg = process.argv[2];
const eventId = arg && /^\d+$/.test(arg) ? arg : await lastCompleted();

const raw = await json(`${SITE}/summary?event=${eventId}`);

// Which side WVU is on, read the same way the app reads it off the games row.
const comp = ((raw.header as Record<string, unknown>)?.competitions as Record<string, unknown>[])?.[0];
const competitors = (comp?.competitors ?? []) as Record<string, unknown>[];
const wvuHome = competitors.some(
  (c) => String((c.team as Record<string, unknown>)?.id) === WVU && c.homeAway === 'home',
);

const s = parseSummary(raw, wvuHome);
if (!s) {
  console.error('parseSummary returned null — the payload shape changed.');
  process.exit(1);
}

const line = (n = 66) => console.log('-'.repeat(n));

console.log(`\nevent ${eventId}   wvuHome=${wvuHome}   state=${s.state}`);
line();
console.log(`SCOREBOARD   ${s.wvuAbbr} ${s.wvuScore}  -  ${s.oppScore} ${s.oppAbbr}    ${s.detail}`);
console.log(`  ${s.wvuAbbr.padEnd(5)} ${s.wvuLine.join('  ')}`);
console.log(`  ${s.oppAbbr.padEnd(5)} ${s.oppLine.join('  ')}`);
console.log(`  logos: ${s.wvuLogo ? 'yes' : 'MISSING'} / ${s.oppLogo ? 'yes' : 'MISSING'}`);

line();
console.log('TEAM STATS');
for (const r of s.teamStats) {
  console.log(`  ${String(r.wvu).padStart(9)}  ${r.label.padEnd(16)}  ${r.opp}`);
}
if (!s.teamStats.length) console.log('  (none)');

line();
console.log('BOX SCORE');
for (const t of s.box) {
  console.log(`\n  ${t.isWvu ? '>>' : '  '} ${t.team} (${t.abbr})`);
  for (const cat of t.categories) {
    console.log(`     ${BOX_LABEL[cat.name] ?? cat.name}   ${cat.labels.join(' | ')}`);
    for (const a of cat.athletes.slice(0, 4)) {
      const wrong = a.stats.length !== cat.labels.length ? '   <-- COLUMN COUNT MISMATCH' : '';
      console.log(`        ${a.name.padEnd(22)} ${a.stats.join(' | ')}${wrong}`);
    }
    if (cat.athletes.length > 4) console.log(`        ...${cat.athletes.length - 4} more`);
  }
  if (!t.categories.length) console.log('     (no categories with athletes)');
}

line();
console.log(`SCORING (${s.scoringPlays.length}, newest first)`);
for (const p of s.scoringPlays.slice(0, 6)) {
  console.log(`  ${periodLabel(p.period)} ${p.clock.padStart(5)}  ${s.wvuAbbr} ${p.wvuScore}-${p.oppScore} ${s.oppAbbr}  ${p.text.slice(0, 70)}`);
}

line();
console.log(`DRIVES (${s.drives.length}, newest first)  hasPlays=${s.hasPlays}`);
for (const d of s.drives.slice(0, 4)) {
  console.log(`\n  [${d.isWvu ? 'WVU' : 'OPP'}] ${d.team} — ${d.description} — ${d.result}${d.current ? '  (IN PROGRESS)' : ''}`);
  for (const p of d.plays.slice(0, 3)) {
    console.log(`      ${periodLabel(p.period)} ${p.clock.padStart(5)}  ${(p.downDistance ?? '').padEnd(18)} ${p.text.slice(0, 62)}`);
  }
  if (d.plays.length > 3) console.log(`      ...${d.plays.length - 3} more plays`);
  if (!d.plays.length) console.log('      (no plays)');
}

line();
const problems: string[] = [];
if (!s.box.length) problems.push('box score empty');
if (s.box[0] && !s.box[0].isWvu) problems.push('WVU is not first in the box score');
if (!s.teamStats.length) problems.push('team stats empty');
if (s.state !== 'pre' && !s.hasPlays) problems.push('no plays on a started game');
for (const t of s.box) {
  for (const cat of t.categories) {
    for (const a of cat.athletes) {
      if (a.stats.length !== cat.labels.length) {
        problems.push(`${t.abbr} ${cat.name}: ${a.name} has ${a.stats.length} stats for ${cat.labels.length} columns`);
      }
    }
  }
}
console.log(problems.length ? `PROBLEMS:\n  - ${problems.join('\n  - ')}` : 'No problems detected.');
