import { useState } from 'react';
import { Image, Pressable, StyleSheet, Text, useWindowDimensions, View } from 'react-native';

import { Brand, Font, StatusMeta, surfaces } from '@/constants/brand';
import { normName, playerFullName } from '@/lib/names';
import { DepthEntry, Player } from '@/lib/types';

const c = surfaces(true);

/**
 * A spot on the field. x/y are percentages of the field box and mark the CENTER of the
 * player's head; the position chip and name hang below it, so two rows need ~13% of
 * vertical space between them or the names collide. The offensive line is staggered on
 * purpose (center highest, tackles lowest) — five names on one straight line overlap at
 * phone width, and the stagger reads as a line splitting anyway.
 */
type Spot = { position: string; x: number; y: number; small?: boolean };
type Formation = { id: string; label: string; spots: Spot[] };

// Positions come from depth_chart.json, so the codes here must match it exactly
// (SE/FL/SLOT rather than X/Y/Z) — the full list view labels them the same way.
const FORMATIONS: Formation[] = [
  {
    id: 'offense',
    label: 'Offense',
    spots: [
      { position: 'SE', x: 10, y: 34 },
      { position: 'FL', x: 89, y: 36 },
      { position: 'SLOT', x: 13, y: 55 },
      { position: 'LT', x: 25, y: 45, small: true },
      { position: 'LG', x: 35, y: 40, small: true },
      { position: 'C', x: 45, y: 36, small: true },
      { position: 'RG', x: 55, y: 40, small: true },
      { position: 'RT', x: 65, y: 45, small: true },
      { position: 'TE', x: 77, y: 47, small: true },
      { position: 'QB', x: 45, y: 60 },
      { position: 'RB', x: 45, y: 82 },
      // No fullback: base personnel is eleven men, and the chart lists a FB behind the
      // backs. Putting him on the field too would draw a twelve-man offense. He's on the
      // Full Depth tab with everyone else.
    ],
  },
  {
    id: 'defense',
    label: 'Defense',
    spots: [
      // 3-3-5: three down linemen, the Bandit on the edge, two off-ball backers,
      // the Nickel over the slot, two corners and two safeties.
      { position: 'DE', x: 31, y: 50, small: true },
      { position: 'NT', x: 44, y: 55, small: true },
      { position: 'DT', x: 58, y: 50, small: true },
      { position: 'BAN', x: 78, y: 48, small: true },
      { position: 'MIKE', x: 42, y: 30 },
      { position: 'OLB', x: 63, y: 30 },
      { position: 'NKL', x: 15, y: 38 },
      { position: 'CB1', x: 9, y: 14 },
      { position: 'CB2', x: 91, y: 14 },
      { position: 'FS', x: 34, y: 8 },
      { position: 'SS', x: 63, y: 8 },
    ],
  },
  {
    id: 'special',
    label: 'Special',
    spots: [
      { position: 'LS', x: 45, y: 38 },
      { position: 'PK', x: 58, y: 57 },
      { position: 'P', x: 35, y: 75 },
    ],
  },
];

// Token metrics at a 350pt-wide field (a 390pt phone). Everything about a token scales
// with the field, because the positions are percentages: heads sized in fixed points
// crowd into each other's names on a small phone and swim on a big one.
const TOKEN_W = 66;
const FIELD_REF_W = 350;
// Yard lines below the end zone, with the number painted on each side.
const YARD_LINES: [number, string][] = [
  [22, '20'],
  [33, '30'],
  [44, '40'],
  [55, '50'],
  [66, '40'],
  [77, '30'],
  [88, '20'],
];

function lastName(full: string): string {
  const parts = (full || '').trim().split(/\s+/);
  // Keep a suffix attached to the surname ("Hawkins Jr.") — dropping it can turn two
  // different players on the same roster into the same label.
  if (parts.length > 2 && /^(jr\.?|sr\.?|ii|iii|iv|v)$/i.test(parts[parts.length - 1])) {
    return `${parts[parts.length - 2]} ${parts[parts.length - 1]}`;
  }
  return parts.length > 1 ? parts[parts.length - 1] : (parts[0] ?? '');
}

function initials(full: string): string {
  const parts = (full || '').trim().split(/\s+/);
  return ((parts[0]?.[0] ?? '') + (parts.length > 1 ? parts[1][0] : '')).toUpperCase();
}

/**
 * A depth-chart-only stand-in for a player with no row in `players`. Everyone on the
 * chart matches the scraped roster today, but a name typed into depth_chart.json before
 * the scraper sees him must still open a profile rather than swallow the tap.
 */
function synthPlayer(e: DepthEntry): Player {
  const parts = (e.player_name || '').trim().split(/\s+/);
  const first = parts.shift() ?? '';
  return {
    id: `depth_${e.id}`,
    sport_id: e.sport_id,
    season: e.season,
    first_name: first,
    last_name: parts.join(' '),
    jersey: null,
    position: e.position,
    height: null,
    weight: null,
    height_display: null,
    class_display: e.class_year,
    home_city: null,
    home_state: null,
    photo_url: null,
  };
}

type Slotted = { spot: Spot; entry: DepthEntry; player: Player | null; projected: boolean };

export function DepthField({
  entries,
  players,
  onPick,
}: {
  entries: DepthEntry[];
  players: Player[];
  onPick: (p: Player) => void;
}) {
  const [unit, setUnit] = useState('offense');
  const formation = FORMATIONS.find((f) => f.id === unit) ?? FORMATIONS[0];
  // The field is the screen minus the 20pt page gutters.
  const { width } = useWindowDimensions();
  const scale = Math.max(0.8, Math.min(1.18, (width - 40) / FIELD_REF_W));

  const byPosition = new Map<string, DepthEntry[]>();
  for (const e of entries) {
    if (!byPosition.has(e.position)) byPosition.set(e.position, []);
    byPosition.get(e.position)!.push(e);
  }
  const roster = new Map(players.map((p) => [normName(playerFullName(p)), p]));

  const slotted: Slotted[] = [];
  for (const spot of formation.spots) {
    const ordered = [...(byPosition.get(spot.position) ?? [])].sort((a, b) => a.rank - b.rank);
    if (ordered.length === 0) continue; // position not on the chart yet — leave the spot empty
    // Same rule as the list view: a starter who's out or doubtful doesn't hold the spot,
    // the next available man does, and he's marked as the projected starter.
    const idx = ordered.findIndex((p) => p.status !== 'out' && p.status !== 'doubtful');
    const pick = idx > 0 ? ordered[idx] : ordered[0];
    slotted.push({
      spot,
      entry: pick,
      player: roster.get(normName(pick.player_name)) ?? null,
      projected: idx > 0,
    });
  }
  // Deeper players draw first so the ones nearer the bottom of the screen overlap them,
  // which is how the eye expects a crowd to stack.
  slotted.sort((a, b) => a.spot.y - b.spot.y);

  const notes = slotted.filter(
    ({ entry, projected }) =>
      projected || (entry.status && entry.status !== 'active') || entry.alert || entry.note,
  );

  return (
    <>
      <View style={styles.unitRow}>
        {FORMATIONS.map((f) => {
          const active = f.id === formation.id;
          return (
            <Pressable
              key={f.id}
              onPress={() => setUnit(f.id)}
              style={[
                styles.unitBtn,
                active
                  ? { backgroundColor: Brand.gold }
                  : { backgroundColor: c.card, borderWidth: 1, borderColor: c.border },
              ]}>
              <Text style={[styles.unitText, { color: active ? Brand.onGold : c.textSecondary }]}>
                {f.label}
              </Text>
            </Pressable>
          );
        })}
      </View>

      <View style={styles.field}>
        {/* Mown stripes, then yard lines painted on top of them. */}
        {[0, 1, 2, 3, 4, 5, 6, 7, 8, 9].map((i) => (
          <View
            key={i}
            style={[
              styles.stripe,
              { top: `${i * 10}%`, backgroundColor: i % 2 ? 'rgba(255,255,255,0.05)' : 'transparent' },
            ]}
          />
        ))}
        <Text style={styles.watermark}>WV</Text>
        {YARD_LINES.map(([y, label]) => (
          <View key={y} style={[styles.yardLine, { top: `${y}%` }]}>
            <Text style={styles.yardNum}>{label}</Text>
            <View style={styles.yardRule} />
            <Text style={styles.yardNum}>{label}</Text>
          </View>
        ))}
        <View style={styles.endzone}>
          <Text style={styles.endzoneText}>MOUNTAINEERS</Text>
        </View>

        {slotted.map((s) => (
          <FieldPlayer
            key={s.spot.position}
            slot={s}
            scale={scale}
            onPress={() => onPick(s.player ?? synthPlayer(s.entry))}
          />
        ))}
      </View>

      <Text style={styles.hint}>
        Tap a player for his profile · switch to Full Depth for the whole two-deep
      </Text>

      {notes.length > 0 && (
        <View style={styles.notes}>
          {notes.map(({ spot, entry, projected }) => (
            <View key={spot.position} style={styles.noteRow}>
              <Text style={styles.notePos}>{spot.position}</Text>
              <View style={{ flex: 1 }}>
                <Text style={styles.noteText}>
                  <Text style={styles.noteName}>{entry.player_name}</Text>
                  {projected ? ' is the projected starter' : ''}
                  {entry.status && entry.status !== 'active'
                    ? `${projected ? ' and is' : ' is'} ${entry.status}`
                    : ''}
                  {entry.note ? ` — ${entry.note}` : ''}
                </Text>
                {entry.alert ? <Text style={styles.noteAlert}>{entry.alert}</Text> : null}
              </View>
            </View>
          ))}
        </View>
      )}
    </>
  );
}

function FieldPlayer({ slot, scale, onPress }: { slot: Slotted; scale: number; onPress: () => void }) {
  const { spot, entry, player, projected } = slot;
  const size = Math.round((spot.small ? 34 : 42) * scale);
  const tokenW = Math.round(TOKEN_W * scale);
  const nameSize = (spot.small ? 10 : 11) * scale;
  const meta = entry.status && entry.status !== 'active' ? StatusMeta[entry.status] : null;
  const ring = meta ? meta.color : projected ? Brand.gold : 'rgba(255,255,255,0.85)';

  return (
    <Pressable
      onPress={onPress}
      hitSlop={4}
      style={({ pressed }) => [
        styles.token,
        {
          left: `${spot.x}%`,
          top: `${spot.y}%`,
          width: tokenW,
          transform: [{ translateX: -tokenW / 2 }, { translateY: -size / 2 }],
          opacity: pressed ? 0.7 : 1,
        },
      ]}>
      <View style={{ width: size, height: size }}>
        {player?.photo_url ? (
          <Image
            source={{ uri: player.photo_url }}
            style={[styles.head, { width: size, height: size, borderRadius: size / 2, borderColor: ring }]}
          />
        ) : (
          <View
            style={[
              styles.head,
              styles.headFallback,
              { width: size, height: size, borderRadius: size / 2, borderColor: ring },
            ]}>
            <Text style={[styles.initialsText, { fontSize: 12 * scale }]}>{initials(entry.player_name)}</Text>
          </View>
        )}
        {player?.jersey != null && (
          <View style={[styles.numBadge, { minWidth: 19 * scale, height: 19 * scale, borderRadius: 10 * scale }]}>
            <Text style={[styles.numText, { fontSize: 10 * scale }]}>{player.jersey}</Text>
          </View>
        )}
        {meta && (
          <View style={[styles.statusBadge, { backgroundColor: meta.color }]}>
            <Text style={styles.statusText}>{meta.label}</Text>
          </View>
        )}
      </View>
      <View style={[styles.posChip, projected && { backgroundColor: Brand.gold }]}>
        <Text style={[styles.posText, { fontSize: 9 * scale }, projected && { color: Brand.onGold }]}>
          {spot.position}
        </Text>
      </View>
      <Text style={[styles.tokenName, { fontSize: nameSize }]} numberOfLines={1}>
        {lastName(entry.player_name)}
      </Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  unitRow: { flexDirection: 'row', gap: 8, marginTop: 12, marginBottom: 10 },
  unitBtn: { flex: 1, paddingVertical: 8, borderRadius: 10, alignItems: 'center' },
  unitText: { fontSize: 12, fontFamily: Font.bodyBold, letterSpacing: 0.4 },

  field: {
    width: '100%',
    aspectRatio: 0.86,
    borderRadius: 16,
    overflow: 'hidden',
    backgroundColor: '#20512c',
    borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.12)',
  },
  stripe: { position: 'absolute', left: 0, right: 0, height: '10%' },
  yardLine: { position: 'absolute', left: 8, right: 8, flexDirection: 'row', alignItems: 'center', gap: 6 },
  yardRule: { flex: 1, height: 1, backgroundColor: 'rgba(255,255,255,0.30)' },
  yardNum: { color: 'rgba(255,255,255,0.38)', fontSize: 9, fontFamily: Font.display },
  watermark: {
    position: 'absolute',
    top: '40%',
    left: 0,
    right: 0,
    textAlign: 'center',
    color: 'rgba(255,255,255,0.07)',
    fontFamily: Font.black,
    fontSize: 92,
  },
  endzone: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    height: '11%',
    backgroundColor: Brand.blue,
    alignItems: 'center',
    justifyContent: 'center',
    borderBottomWidth: 2,
    borderBottomColor: 'rgba(255,255,255,0.55)',
  },
  endzoneText: { color: Brand.gold, fontFamily: Font.display, fontSize: 12, letterSpacing: 4 },

  token: { position: 'absolute', alignItems: 'center' },
  head: { backgroundColor: c.surface2, borderWidth: 2 },
  headFallback: { alignItems: 'center', justifyContent: 'center', backgroundColor: Brand.blue },
  initialsText: { color: '#fff', fontFamily: Font.display, fontSize: 12 },
  numBadge: {
    position: 'absolute',
    right: -6,
    bottom: -3,
    minWidth: 19,
    height: 19,
    paddingHorizontal: 4,
    borderRadius: 10,
    backgroundColor: '#0B111D',
    borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.5)',
    alignItems: 'center',
    justifyContent: 'center',
  },
  numText: { color: '#fff', fontSize: 10, fontFamily: Font.bodyBold },
  statusBadge: { position: 'absolute', left: -8, top: -2, borderRadius: 5, paddingHorizontal: 4, paddingVertical: 1 },
  statusText: { color: '#fff', fontSize: 8, fontFamily: Font.bodyBold },
  posChip: {
    marginTop: 4,
    backgroundColor: 'rgba(6,11,22,0.88)',
    borderRadius: 5,
    paddingHorizontal: 5,
    paddingVertical: 2,
  },
  posText: { color: '#fff', fontSize: 9, fontFamily: Font.bodyBold, letterSpacing: 0.3 },
  tokenName: {
    marginTop: 2,
    color: '#fff',
    fontSize: 11,
    fontFamily: Font.bodySemi,
    textShadowColor: 'rgba(0,0,0,0.85)',
    textShadowOffset: { width: 0, height: 1 },
    textShadowRadius: 3,
  },

  hint: { marginTop: 10, fontSize: 11, fontStyle: 'italic', color: c.textMuted, fontFamily: Font.body },
  notes: { marginTop: 10, gap: 8 },
  noteRow: {
    flexDirection: 'row',
    gap: 10,
    backgroundColor: c.card,
    borderWidth: 1,
    borderColor: c.border,
    borderRadius: 12,
    padding: 12,
  },
  notePos: { width: 40, color: Brand.gold, fontSize: 12, fontFamily: Font.black },
  noteText: { color: c.textSecondary, fontSize: 12, lineHeight: 17, fontFamily: Font.body },
  noteName: { color: c.text, fontFamily: Font.bodySemi },
  noteAlert: { marginTop: 4, color: Brand.gold, fontSize: 11, lineHeight: 15, fontFamily: Font.bodySemi },
});
