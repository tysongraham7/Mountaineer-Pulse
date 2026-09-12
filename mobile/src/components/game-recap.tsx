import { StyleSheet, Text, View } from 'react-native';

import { Brand, Font, surfaces } from '@/constants/brand';

/** The post-game "By the Numbers" generate_recap.py writes once a football game is final. */
export type Recap = {
  headline: string;
  notes: {
    /** The number, rendered large: "71", "2-0", "316". Empty when the note is prose only. */
    figure: string;
    /** What the figure is: "yard TD run", "start", "rushing yards". */
    label: string;
    body: string;
    /** Where the context came from: "WVU Athletics postgame notes", "AP", "Box score". */
    source?: string;
  }[];
  generated_at?: string;
};

const c = surfaces(true);

/**
 * The numbers a fan repeats on Monday, at the top of the Summary tab. The scouting report
 * is the game before it happens; this is the game after. Same card language as the
 * scoring plays below it so the tab reads as one column.
 *
 * Sources are named once at the bottom rather than under every card: a fan wants the
 * fact, and the attribution is there for the one who wants to check it.
 */
export function GameRecap({ recap }: { recap: Recap }) {
  const notes = (recap.notes ?? []).filter((n) => !!n.body?.trim());
  if (!notes.length) return null;
  // "Box score" is where the numbers come from, not a source anyone needs pointing to.
  const sources = Array.from(
    new Set(notes.map((n) => (n.source ?? '').trim()).filter((s) => s && !/^box score$/i.test(s))),
  );

  return (
    <View>
      <Text style={styles.label}>BY THE NUMBERS</Text>
      {!!recap.headline?.trim() && <Text style={styles.lede}>{recap.headline.trim()}</Text>}
      {notes.map((n, i) => (
        <View key={i} style={styles.card}>
          {!!n.figure?.trim() && (
            <View style={styles.figureCol}>
              <Text style={styles.figure} numberOfLines={1} adjustsFontSizeToFit minimumFontScale={0.6}>
                {n.figure.trim()}
              </Text>
              {!!n.label?.trim() && (
                <Text style={styles.figureLabel} numberOfLines={2}>{n.label.trim()}</Text>
              )}
            </View>
          )}
          <Text style={styles.body}>{n.body.trim()}</Text>
        </View>
      ))}
      {sources.length > 0 && (
        <Text style={styles.note}>Context from {sources.join(', ')}.</Text>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  // Matches the section labels in game-live.tsx so this sits in the same rhythm.
  label: { fontFamily: Font.bodyBold, fontSize: 10.5, letterSpacing: 1.2, color: Brand.gold, marginTop: 18, marginBottom: 7 },
  lede: { fontFamily: Font.displaySemi, fontSize: 15.5, lineHeight: 22, color: c.text, marginBottom: 4 },
  card: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 14,
    backgroundColor: c.card,
    borderWidth: 1,
    borderColor: c.border,
    borderRadius: 12,
    padding: 13,
    marginTop: 8,
  },
  // Fixed width so the body text lines up down the column whether the figure is "4" or
  // "316"; the figure shrinks to fit rather than pushing the text around.
  figureCol: { width: 74, alignItems: 'center' },
  figure: { fontFamily: Font.black, fontSize: 28, color: Brand.gold, letterSpacing: -0.8, fontVariant: ['tabular-nums'] },
  figureLabel: { fontFamily: Font.bodySemi, fontSize: 10, color: c.textSecondary, textAlign: 'center', marginTop: 1, lineHeight: 13 },
  body: { flex: 1, fontFamily: Font.body, fontSize: 13, lineHeight: 19, color: c.text },
  note: { fontFamily: Font.body, fontSize: 11.5, color: c.textMuted, lineHeight: 17, marginTop: 10 },
});
