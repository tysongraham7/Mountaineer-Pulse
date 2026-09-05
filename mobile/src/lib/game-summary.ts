/**
 * ESPN's game summary — box score, play-by-play, team stats — turned into what the game
 * sheet renders.
 *
 * Same split as live-game-parse.ts, and for the same reason: no React, no React Native, no
 * fetch. A live game happens once a week and can't be replayed on demand, so the only way
 * to know this is right is to run it over a real game's JSON. It imports nothing that needs
 * a phone, so scripts/rehearse-live.mts can do exactly that.
 *
 * WHY THE SITE API HERE, when the live card uses the core API. The card needs two numbers
 * every twenty seconds and gets them in 2.3 KB. This screen needs a box score, and ESPN
 * only assembles that in one place: the summary endpoint, 178 KB of which about 105 KB is
 * boxscore + drives and the rest is news, standings and betting lines we throw away. That
 * is far too much to poll on a timer, which is why it is fetched when someone opens the
 * sheet and refreshed on a slow tick — see use-game-summary.ts.
 */

export const WVU_ID = '277';

export type BoxCategory = {
  /** ESPN's key: passing, rushing, receiving, defensive, kicking, punting, ... */
  name: string;
  /** Column headers: ['C/ATT', 'YDS', 'AVG', 'TD', 'INT'] */
  labels: string[];
  athletes: { name: string; stats: string[] }[];
};

export type TeamBox = {
  team: string;
  abbr: string;
  isWvu: boolean;
  categories: BoxCategory[];
};

/** One row of the side-by-side team comparison. */
export type TeamStatRow = { label: string; wvu: string; opp: string };

export type PlayItem = {
  id: string;
  period: number;
  clock: string;
  text: string;
  scoringPlay: boolean;
  /** Score AFTER the play, from WVU's side. */
  wvuScore: number | null;
  oppScore: number | null;
  /** "3rd & 5 at CCU 49", when the feed states one. */
  downDistance: string | null;
};

export type DriveItem = {
  id: string;
  team: string;
  isWvu: boolean;
  /** "9 plays, 92 yards, 3:33" */
  description: string;
  /** "Touchdown", "Punt", "End of Half" */
  result: string;
  isScore: boolean;
  /** True for the drive still being played. */
  current: boolean;
  plays: PlayItem[];
};

export type GameSummary = {
  state: 'pre' | 'in' | 'post';
  /** ESPN's label — "2:21 - 1st", "Final", "Halftime". */
  detail: string;
  period: number;
  clock: string;
  wvuScore: number | null;
  oppScore: number | null;
  wvuAbbr: string;
  oppAbbr: string;
  wvuName: string;
  oppName: string;
  wvuLogo: string | null;
  oppLogo: string | null;
  /** Points per quarter, index 0 = 1st. */
  wvuLine: string[];
  oppLine: string[];
  teamStats: TeamStatRow[];
  box: TeamBox[];
  drives: DriveItem[];
  scoringPlays: PlayItem[];
  /** Whether ESPN says it has play-by-play for this game at all. */
  hasPlays: boolean;
};

type Json = Record<string, unknown>;

const obj = (v: unknown): Json => (v && typeof v === 'object' ? (v as Json) : {});
const arr = (v: unknown): Json[] => (Array.isArray(v) ? (v as Json[]) : []);
const str = (v: unknown): string => (typeof v === 'string' ? v : '');
const int = (v: unknown): number | null => {
  const n = typeof v === 'string' ? Number(v) : v;
  return typeof n === 'number' && Number.isFinite(n) ? n : null;
};

/** Team stats we show, in the order a fan reads them. ESPN sends fifteen; these are the
 *  ones that decide games, and the rest (yards per rush, red-zone attempts) are noise on a
 *  phone-width column. Keyed on ESPN's `name` so a relabeling upstream can't scramble it. */
const TEAM_STAT_ORDER: [string, string][] = [
  ['totalYards', 'Total Yards'],
  ['firstDowns', 'First Downs'],
  ['netPassingYards', 'Passing'],
  ['rushingYards', 'Rushing'],
  ['thirdDownEff', '3rd Down'],
  ['fourthDownEff', '4th Down'],
  ['totalPenaltiesYards', 'Penalties'],
  ['turnovers', 'Turnovers'],
  ['possessionTime', 'Possession'],
];

/** Categories worth a table, in the order they matter. ESPN sends eleven per team and most
 *  are empty for most of a game — an empty one is dropped rather than rendered as a header
 *  over nothing. */
const BOX_ORDER = [
  'passing', 'rushing', 'receiving', 'defensive', 'interceptions',
  'fumbles', 'kicking', 'punting', 'kickReturns', 'puntReturns',
];

export const BOX_LABEL: Record<string, string> = {
  passing: 'Passing',
  rushing: 'Rushing',
  receiving: 'Receiving',
  defensive: 'Defense',
  interceptions: 'Interceptions',
  fumbles: 'Fumbles',
  kicking: 'Kicking',
  punting: 'Punting',
  kickReturns: 'Kick Returns',
  puntReturns: 'Punt Returns',
};

function stateOf(status: Json): 'pre' | 'in' | 'post' {
  const s = str(obj(obj(status).type).state);
  return s === 'in' || s === 'post' ? s : 'pre';
}

/**
 * Which competitor is WVU.
 *
 * By team id, not by the caller's `wvuHome` flag and not by name. The id is the one thing
 * ESPN never spells differently, and a neutral-site game is exactly where a home/away
 * assumption quietly puts every stat on the wrong side.
 */
function splitCompetitors(competitors: Json[]): { wvu: Json | null; opp: Json | null } {
  let wvu: Json | null = null;
  let opp: Json | null = null;
  for (const c of competitors) {
    const id = str(obj(c.team).id) || str(c.id);
    if (id === WVU_ID) wvu = c;
    else opp = c;
  }
  return { wvu, opp };
}

function logoOf(team: Json): string | null {
  const direct = str(team.logo);
  if (direct) return direct;
  const first = arr(team.logos)[0];
  return str(obj(first).href) || null;
}

function playFrom(p: Json, wvuHome: boolean): PlayItem {
  const home = int(p.homeScore);
  const away = int(p.awayScore);
  return {
    id: str(p.id) || `${str(obj(p.period).number)}-${str(obj(p.clock).displayValue)}-${str(p.text).slice(0, 24)}`,
    period: int(obj(p.period).number) ?? 0,
    clock: str(obj(p.clock).displayValue),
    text: str(p.text),
    scoringPlay: p.scoringPlay === true,
    wvuScore: wvuHome ? home : away,
    oppScore: wvuHome ? away : home,
    downDistance: str(obj(p.start).downDistanceText) || null,
  };
}

/**
 * @param wvuHome Which side of ESPN's home/away SCORES is WVU. Only used for the score
 *   fields on a play, which are the one place ESPN labels by home/away rather than by team.
 */
export function parseSummary(json: unknown, wvuHome: boolean): GameSummary | null {
  const root = obj(json);
  const comp = arr(obj(root.header).competitions)[0];
  if (!comp) return null;

  const status = obj(comp.status);
  const { wvu, opp } = splitCompetitors(arr(comp.competitors));
  if (!wvu || !opp) return null;

  const wvuTeam = obj(wvu.team);
  const oppTeam = obj(opp.team);

  const lineOf = (c: Json) => arr(c.linescores).map((l) => str(l.displayValue));

  // --- team stats -----------------------------------------------------------
  const boxRoot = obj(root.boxscore);
  const statsByTeam = new Map<string, Map<string, string>>();
  const namesByTeam = new Map<string, string>();
  for (const t of arr(boxRoot.teams)) {
    const id = str(obj(t.team).id);
    const m = new Map<string, string>();
    for (const s of arr(t.statistics)) m.set(str(s.name), str(s.displayValue));
    statsByTeam.set(id, m);
    namesByTeam.set(id, str(obj(t.team).displayName));
  }
  const wvuStats = statsByTeam.get(WVU_ID) ?? new Map();
  const oppId = str(oppTeam.id);
  const oppStats = statsByTeam.get(oppId) ?? new Map();
  const teamStats: TeamStatRow[] = TEAM_STAT_ORDER
    .map(([key, label]) => ({ label, wvu: wvuStats.get(key) ?? '', opp: oppStats.get(key) ?? '' }))
    // A stat neither side has yet is a blank row, which reads as a rendering bug.
    .filter((r) => r.wvu !== '' || r.opp !== '');

  // --- player box score -----------------------------------------------------
  const box: TeamBox[] = [];
  for (const p of arr(boxRoot.players)) {
    const team = obj(p.team);
    const id = str(team.id);
    const categories: BoxCategory[] = [];
    for (const st of arr(p.statistics)) {
      const athletes = arr(st.athletes)
        .map((a) => ({
          name: str(obj(a.athlete).displayName),
          stats: arr(a.stats as unknown).length
            ? (a.stats as unknown[]).map((x) => str(x))
            : (Array.isArray(a.stats) ? (a.stats as string[]) : []),
        }))
        .filter((a) => a.name);
      if (!athletes.length) continue; // no header over an empty table
      categories.push({
        name: str(st.name),
        labels: (Array.isArray(st.labels) ? st.labels : []).map((x) => str(x)),
        athletes,
      });
    }
    categories.sort((a, b) => {
      const ai = BOX_ORDER.indexOf(a.name);
      const bi = BOX_ORDER.indexOf(b.name);
      return (ai < 0 ? 99 : ai) - (bi < 0 ? 99 : bi);
    });
    box.push({
      team: str(team.displayName),
      abbr: str(team.abbreviation),
      isWvu: id === WVU_ID,
      categories,
    });
  }
  // WVU first. This is a WVU app; nobody opened it to read Coastal Carolina's box score.
  box.sort((a, b) => Number(b.isWvu) - Number(a.isWvu));

  // --- drives and plays -----------------------------------------------------
  const drivesRoot = obj(root.drives);
  const current = obj(drivesRoot.current);
  const currentId = str(current.id);
  // `previous` ALREADY contains the drive being played, and `current` repeats it. Appending
  // both put the live drive on screen twice, once labeled in-progress and once not. Match on
  // id and flag the existing entry instead; only fall back to appending when the feed hands
  // back a current drive that genuinely isn't in the list yet.
  const rawDrives: [Json, boolean][] = arr(drivesRoot.previous)
    .map((d) => [d, !!currentId && str(d.id) === currentId] as [Json, boolean]);
  if (currentId && !rawDrives.some(([, isCurrent]) => isCurrent)) {
    rawDrives.push([current, true]);
  }

  const drives: DriveItem[] = rawDrives.map(([d, isCurrent]) => {
    const team = obj(d.team);
    return {
      id: str(d.id) || str(d.description),
      team: str(team.shortDisplayName) || str(team.displayName),
      isWvu: str(team.id) === WVU_ID,
      description: str(d.description),
      result: str(d.displayResult) || str(d.result),
      isScore: d.isScore === true,
      current: isCurrent,
      plays: arr(d.plays).map((p) => playFrom(p, wvuHome)),
    };
  });
  // Newest drive first: during a game the one being played is the one you want, and after
  // it the last thing that happened is still the most interesting.
  drives.reverse();

  const scoringPlays = arr(root.scoringPlays).map((p) => playFrom(p, wvuHome));
  scoringPlays.reverse();

  return {
    state: stateOf(status),
    detail: str(obj(status.type).shortDetail) || str(obj(status.type).description),
    period: int(status.period) ?? 0,
    clock: str(status.displayClock),
    wvuScore: int(wvu.score),
    oppScore: int(opp.score),
    wvuAbbr: str(wvuTeam.abbreviation) || 'WVU',
    oppAbbr: str(oppTeam.abbreviation) || 'OPP',
    wvuName: str(wvuTeam.shortDisplayName) || str(wvuTeam.displayName),
    oppName: str(oppTeam.shortDisplayName) || str(oppTeam.displayName),
    wvuLogo: logoOf(wvuTeam),
    oppLogo: logoOf(oppTeam),
    wvuLine: lineOf(wvu),
    oppLine: lineOf(opp),
    teamStats,
    box,
    drives,
    scoringPlays,
    hasPlays: drives.some((d) => d.plays.length > 0),
  };
}

/** "1st", "2nd", "OT", "2OT" — ESPN counts overtime as period 5 and up. */
export function periodLabel(period: number): string {
  if (period <= 0) return '';
  if (period <= 4) return ['', '1st', '2nd', '3rd', '4th'][period];
  return period === 5 ? 'OT' : `${period - 4}OT`;
}
