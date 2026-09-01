import { Player } from '@/lib/types';

/**
 * Loose key for matching a person across tables that don't share an id — the curated
 * depth chart and roster_moves store a typed-in `player_name`, while `players` comes
 * from the scraper as first/last. Drops case, punctuation and generational suffixes so
 * "Michael Hawkins Jr." and "Michael Hawkins" are the same person.
 *
 * Mirrors norm_name() in data-pipeline/sync_depth.py — keep the two in step.
 */
export function normName(n: string): string {
  return (n || '')
    .toLowerCase()
    .replace(/[.'-]/g, ' ')
    .replace(/\b(jr|sr|ii|iii|iv|v)\b/g, '')
    .replace(/\s+/g, ' ')
    .trim();
}

export function playerFullName(p: Player): string {
  return `${p.first_name ?? ''} ${p.last_name ?? ''}`.trim();
}
