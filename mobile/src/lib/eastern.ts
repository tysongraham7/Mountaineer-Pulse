/**
 * US Eastern time helpers.
 *
 * Kickoffs are announced in Eastern and fans talk about them in Eastern, so the app
 * shows Eastern and labels it — not device-local, which would quietly show the wrong
 * hour to anyone travelling.
 *
 * The offset is computed by hand rather than via `toLocaleString({ timeZone })`,
 * because Hermes' Intl time-zone support varies by platform and build; when it's
 * missing the call silently falls back to device-local and looks correct on the
 * developer's Eastern-time phone.
 */

/** UTC ms of the nth Sunday of a month, at 07:00 UTC (~2am Eastern, when DST flips). */
function nthSundayUTC(year: number, monthIdx: number, n: number): number {
  const firstOfMonth = Date.UTC(year, monthIdx, 1);
  const dow = new Date(firstOfMonth).getUTCDay();
  const day = 1 + ((7 - dow) % 7) + (n - 1) * 7;
  return Date.UTC(year, monthIdx, day, 7);
}

/** DST runs from the 2nd Sunday of March to the 1st Sunday of November. */
function isEasternDST(d: Date): boolean {
  const y = d.getUTCFullYear();
  return d.getTime() >= nthSundayUTC(y, 2, 2) && d.getTime() < nthSundayUTC(y, 10, 1);
}

/**
 * Shift an instant onto Eastern wall-clock time. Read the result with the getUTC*
 * accessors — the returned Date is a carrier for the shifted fields, not an instant.
 */
export function toEastern(iso: string): { d: Date; abbrev: 'EDT' | 'EST' } {
  const utc = new Date(iso);
  const dst = isEasternDST(utc);
  return {
    d: new Date(utc.getTime() + (dst ? -4 : -5) * 3_600_000),
    abbrev: dst ? 'EDT' : 'EST',
  };
}

const DAYS = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December'];

/** "Saturday, September 5, 2026" */
export function easternDateLong(iso: string): string {
  const { d } = toEastern(iso);
  return `${DAYS[d.getUTCDay()]}, ${MONTHS[d.getUTCMonth()]} ${d.getUTCDate()}, ${d.getUTCFullYear()}`;
}

/** "Sat, Sep 5" — the list form of easternDateLong, so a card and its detail agree. */
export function easternDateShort(iso: string): string {
  const { d } = toEastern(iso);
  return `${DAYS[d.getUTCDay()].slice(0, 3)}, ${MONTHS[d.getUTCMonth()].slice(0, 3)} ${d.getUTCDate()}`;
}

/**
 * "12:00 PM EDT", or null when the kickoff time isn't set yet.
 *
 * CFBD represents an unannounced kickoff as midnight Eastern rather than a null, so
 * half the schedule would read "12:00 AM" if taken literally. No college game starts
 * at midnight, which makes it a safe sentinel.
 */
export function easternTime(iso: string): string | null {
  const { d, abbrev } = toEastern(iso);
  const h = d.getUTCHours();
  const m = d.getUTCMinutes();
  if (h === 0 && m === 0) return null;
  const hour12 = h % 12 === 0 ? 12 : h % 12;
  return `${hour12}:${String(m).padStart(2, '0')} ${h < 12 ? 'AM' : 'PM'} ${abbrev}`;
}

/** Whole days from today until the game, in Eastern. Negative once it's past. */
export function daysUntil(iso: string): number {
  const { d: game } = toEastern(iso);
  const { d: now } = toEastern(new Date().toISOString());
  const gameDay = Date.UTC(game.getUTCFullYear(), game.getUTCMonth(), game.getUTCDate());
  const today = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate());
  return Math.round((gameDay - today) / 86_400_000);
}

/** "Today", "Tomorrow", "In 12 days" — or null when it's in the past. */
export function countdownLabel(iso: string): string | null {
  const n = daysUntil(iso);
  if (n < 0) return null;
  if (n === 0) return 'Today';
  if (n === 1) return 'Tomorrow';
  return `In ${n} days`;
}

/**
 * Kickoff as a timestamp, or null when the time hasn't been announced.
 *
 * Guarded by easternTime rather than reading the instant directly: an unannounced
 * kickoff is stored as midnight Eastern, and counting down to that would show a
 * confident timer to a time nobody has set.
 */
export function kickoffAt(iso: string): number | null {
  return easternTime(iso) === null ? null : new Date(iso).getTime();
}

/** "3:42:15", or "12:05" inside the last hour. Largest unit first, no leading zero. */
export function formatCountdown(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const pad = (n: number) => String(n).padStart(2, '0');
  return h > 0 ? `${h}:${pad(m)}:${pad(s)}` : `${m}:${pad(s)}`;
}
