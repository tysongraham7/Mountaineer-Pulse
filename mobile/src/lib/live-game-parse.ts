/**
 * Turning ESPN's raw live-game JSON into what the game-day card renders.
 *
 * Deliberately separate from use-live-game.ts, and deliberately free of any React or
 * React Native import. A live game happens once a week for three hours and cannot be
 * paused, rewound, or made to produce a 3rd & goal on demand — so the only way to know
 * this logic is right before kickoff is to run it over a finished game's plays. That is
 * what scripts/rehearse-live.ts does, and it can only do it because this file imports
 * nothing that needs a phone.
 */

/** ESPN's team id for WVU, the same one the pipeline uses. */
export const WVU_TEAM_ID = '277';

export type LiveGame = {
  /** ESPN's own view of whether this has started, which beats guessing from the clock. */
  state: 'pre' | 'in' | 'post';
  /** Quarter. 5+ is overtime. */
  period: number;
  /** "8:14". Empty between periods. */
  clock: string;
  /** ESPN's label — "Final", "End of 3rd Quarter", "1st Quarter". */
  detail: string;
  wvuScore: number | null;
  oppScore: number | null;
  /** "2nd & 7", or null when there is no live down (kickoff, halftime, final). */
  downDistance: string | null;
  /**
   * "WVU 43". Null unless possession is known — a field position drawn on the wrong half
   * of the field is worse than none, and possession is the part ESPN is least explicit
   * about between plays.
   */
  fieldPosition: string | null;
  /** True when WVU has the ball, false when the opponent does, null when unknown. */
  wvuHasBall: boolean | null;
  isRedZone: boolean;
  /** ESPN's sentence for the most recent play, already containing the player names. */
  lastPlay: string | null;
};

export type Situation = {
  down?: number;
  distance?: number;
  yardLine?: number;
  isRedZone?: boolean;
  possession?: string | { $ref?: string };
  lastPlay?: { $ref?: string };
};

export type ParseOpts = {
  /** Which side of ESPN's home/away scores is WVU. */
  wvuHome: boolean;
  /** Short names used in the field-position label. */
  wvuAbbr: string;
  oppAbbr: string;
};

const ORDINAL = ['', '1st', '2nd', '3rd', '4th'];

const num = (v: unknown) => (typeof v === 'number' && Number.isFinite(v) ? v : null);

/** Pull the numeric team id out of any core-API team reference. */
export function teamIdFrom(ref: unknown): string | null {
  if (typeof ref === 'string') {
    return /^\d+$/.test(ref) ? ref : (ref.match(/\/teams\/(\d+)/)?.[1] ?? null);
  }
  if (ref && typeof ref === 'object') {
    const inner = (ref as { $ref?: string }).$ref;
    if (typeof inner === 'string') return inner.match(/\/teams\/(\d+)/)?.[1] ?? null;
  }
  return null;
}

/**
 * "WVU 43" from ESPN's yard line.
 *
 * `yardLine` is an ABSOLUTE field coordinate: 0 is the home team's goal line and 100 is the
 * away team's, regardless of who has the ball. It is emphatically NOT measured from the
 * offense's own goal, which is the intuitive reading and the one that puts the ball on the
 * wrong half of the field.
 *
 * Measured over all 187 plays of Texas Tech at West Virginia (ESPN event 401756968), where
 * WVU was home: with the HOME team in possession, yardLine + yardsToEndzone came to 100 in
 * 56 of 68 plays; with the AWAY team in possession, yardsToEndzone equalled yardLine in 109
 * of 119. Only an absolute coordinate satisfies both — a relative one would have given the
 * same relationship for both teams. (The stragglers are kickoffs, turnovers and end-of-period
 * rows, where `end` describes a different snap than the one that follows.)
 *
 * The useful consequence is that naming the spot needs only home and away, never possession
 * — so this stays correct through a turnover ESPN hasn't reported possession for yet.
 */
export function fieldPositionLabel(
  yardLine: number,
  homeAbbr: string,
  awayAbbr: string,
): string | null {
  if (!Number.isFinite(yardLine) || yardLine <= 0 || yardLine >= 100) return null;
  if (yardLine === 50) return '50';
  return yardLine < 50 ? `${homeAbbr} ${yardLine}` : `${awayAbbr} ${100 - yardLine}`;
}

/** ESPN's own verdict on whether the game has started, which beats inferring from a clock. */
export function statusState(status: Record<string, unknown> | null): LiveGame['state'] {
  const type = (status?.type ?? {}) as Record<string, unknown>;
  return (type.state as LiveGame['state']) ?? 'pre';
}

/**
 * A stoppage with no next snap: halftime, the end of a quarter, a weather delay.
 *
 * ESPN keeps `state` at "in" through all of these AND keeps serving the last live
 * situation, so at halftime the situation endpoint still answers "2nd & 10 at WVU 12" —
 * the down that will never be played, left over from the kneel-down before the break.
 * Printing it under "Halftime" states something that isn't true.
 *
 * Matched on the status NAME rather than an exhaustive list of ids, because the failure
 * mode of a name ESPN adds later is a stale down reappearing, and these four substrings
 * cover every break the feed has ever used for football.
 */
export function inBreak(status: Record<string, unknown> | null): boolean {
  const name = String(((status?.type ?? {}) as Record<string, unknown>).name ?? '');
  return /HALFTIME|END_PERIOD|DELAY|SUSPEND/.test(name);
}

/** Turn the three raw ESPN payloads into what the card renders. */
export function parseLive(
  status: Record<string, unknown> | null,
  situation: Situation | null,
  play: Record<string, unknown> | null,
  opts: ParseOpts,
): LiveGame {
  const { wvuHome, wvuAbbr, oppAbbr } = opts;
  const type = (status?.type ?? {}) as Record<string, unknown>;
  const state = statusState(status);
  const detail = (type.shortDetail as string) ?? (type.description as string) ?? '';

  const base: LiveGame = {
    state,
    period: Number(status?.period ?? 0),
    clock: (status?.displayClock as string) ?? '',
    detail,
    wvuScore: null,
    oppScore: null,
    downDistance: null,
    fieldPosition: null,
    wvuHasBall: null,
    isRedZone: false,
    lastPlay: null,
  };

  if (state === 'pre') return base;

  // The score rides on the last play — it is the score AFTER that play, so it is both the
  // current score and guaranteed consistent with the play text shown beside it.
  const wvuScore = wvuHome ? num(play?.homeScore) : num(play?.awayScore);
  const oppScore = wvuHome ? num(play?.awayScore) : num(play?.homeScore);

  // Possession: ESPN states it outright during live play; between plays we fall back to
  // whoever ended the last play with the ball. Null when neither is available, which
  // suppresses the field position rather than guessing at it.
  const end = (play?.end ?? {}) as Record<string, unknown>;
  const possId = teamIdFrom(situation?.possession) ?? teamIdFrom(end.team) ?? teamIdFrom(play?.team);
  const wvuHasBall = possId === null ? null : possId === WVU_TEAM_ID;

  const down = Number(situation?.down ?? 0);
  const distance = Number(situation?.distance ?? -1);
  const downDistance =
    down >= 1 && down <= 4 && distance >= 0
      ? distance === 0
        ? `${ORDINAL[down]} & Goal`
        : `${ORDINAL[down]} & ${distance}`
      : null;

  // Home/away, not offense/defense — see fieldPositionLabel. This is why the yard line
  // survives a turnover that possession hasn't caught up with yet.
  const fieldPosition = fieldPositionLabel(
    Number(situation?.yardLine ?? NaN),
    wvuHome ? wvuAbbr : oppAbbr,
    wvuHome ? oppAbbr : wvuAbbr,
  );

  // No next snap: the game is over, or it's halftime / between quarters / delayed. ESPN
  // keeps serving the last live situation through all of those, so "1st & 10" under a
  // final score — or "2nd & 10" under "Halftime" — is a lie the feed will happily tell.
  const noNextSnap = state === 'post' || inBreak(status);
  return {
    ...base,
    wvuScore,
    oppScore,
    downDistance: noNextSnap ? null : downDistance,
    fieldPosition: noNextSnap ? null : fieldPosition,
    wvuHasBall: noNextSnap ? null : wvuHasBall,
    isRedZone: !noNextSnap && !!situation?.isRedZone,
    lastPlay: (play?.text as string) ?? null,
  };
}
