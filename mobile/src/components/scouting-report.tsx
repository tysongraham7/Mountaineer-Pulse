import { StyleSheet, Text, View } from 'react-native';

import { SectionLabel } from '@/components/ui';
import { Brand, Font, surfaces } from '@/constants/brand';
import { easternDateLong } from '@/lib/eastern';

/** The scouting report generate_matchup.py writes, ~10 days out from kickoff. */
export type Matchup = {
  headline: string;
  opponent: { record: string; snapshot: string };
  history: string;
  keys: { topic: string; body: string }[];
  strengths: string;
  exploit: string;
  injuries: string;
  line: string;
  weather: string;
  /** Set when the report was written. Its contents move, so the sheet says when. */
  generated_at?: string;
};

const c = surfaces(true);

/** Same page the Pulse share points at. */
const SHARE_URL = 'https://tysongraham7.github.io/Mountaineer-Pulse/';

/**
 * The report as a text message. The headline and the keys are the parts a fan would
 * actually paste into a group chat; the weather and the series history are not. Text
 * rather than an image for the same reason the Pulse share is — it ships over the air.
 */
export function scoutShareText(scout: Matchup, matchup: string): string {
  const keys = (scout.keys ?? []).map((k) => `• ${k.topic}`);
  const lines = [
    `WVU ${matchup} — Scouting Report`,
    scout.headline || null,
    scout.opponent?.record ? `${scout.opponent.record}` : null,
    ...(keys.length ? ['', 'Keys to Victory', ...keys] : []),
    scout.line?.trim() ? ['', `Expected outcome: ${scout.line.trim()}`].join('\n') : null,
    '',
    `via Mountaineer Pulse — ${SHARE_URL}`,
  ].filter((l) => l !== null) as string[];
  return lines.join('\n');
}

/**
 * The scouting report body. Before kickoff it sits at the bottom of the game sheet; once
 * the game has started it becomes a tab beside the box score, so the same component is
 * rendered from two places. The section label is the caller's — a tab already names it.
 */
export function ScoutingReport({ scout, titled }: { scout: Matchup; titled?: boolean }) {
  return (
    <View>
      {titled && <SectionLabel style={styles.head as never}>Scouting Report</SectionLabel>}
      {!!scout.headline && <Text style={styles.scoutLede}>{scout.headline}</Text>}

      {(!!scout.opponent?.record || !!scout.opponent?.snapshot) && (
        <View style={styles.scoutCard}>
          {!!scout.opponent.record && (
            <Text style={styles.scoutRecord}>{scout.opponent.record}</Text>
          )}
          {!!scout.opponent.snapshot && (
            <Text style={styles.scoutBody}>{scout.opponent.snapshot}</Text>
          )}
        </View>
      )}

      {!!scout.keys?.length && (
        <Text style={styles.scoutSub}>Keys to Victory</Text>
      )}
      {scout.keys?.map((w, i) => (
        <View key={i} style={styles.scoutCard}>
          <Text style={styles.scoutTopic}>{w.topic}</Text>
          <Text style={styles.scoutBody}>{w.body}</Text>
        </View>
      ))}

      {[['What They Do Well', scout.strengths], ['Where to Attack', scout.exploit]]
        .filter(([, v]) => !!(v || '').trim())
        .map(([label, v]) => (
          <View key={label} style={styles.scoutCard}>
            <Text style={styles.scoutTopic}>{label}</Text>
            <Text style={styles.scoutBody}>{v}</Text>
          </View>
        ))}

      {/* "Expected Outcome", not "Line": the number is here so a fan knows what
          kind of game to expect, not as a betting tip. */}
      {[['Series', scout.history], ['Injuries', scout.injuries],
        ['Expected Outcome', scout.line], ['Weather', scout.weather]]
        .filter(([, v]) => !!(v || '').trim())
        .map(([label, v]) => (
          <View key={label} style={styles.scoutCard}>
            <Text style={styles.scoutTopic}>{label}</Text>
            <Text style={styles.scoutBody}>{v}</Text>
          </View>
        ))}

      <Text style={styles.scoutNote}>
        {scout.generated_at
          ? `Researched from public sources on ${easternDateLong(scout.generated_at)}. Injuries and availability can change before kickoff.`
          : 'Researched from public sources. Injuries and availability can change before kickoff.'}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  head: { marginTop: 20, marginBottom: 8 },
  // Same card language as Game Info on the sheet so it reads as one surface.
  scoutLede: { fontFamily: Font.displaySemi, fontSize: 16, lineHeight: 23, color: c.text, marginBottom: 12 },
  scoutCard: {
    backgroundColor: c.card,
    borderColor: c.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 14,
    marginBottom: 10,
  },
  scoutSub: { fontFamily: Font.bodyBold, fontSize: 11, letterSpacing: 1.3, color: c.textMuted, marginTop: 6, marginBottom: 8 },
  scoutRecord: { fontFamily: Font.bodyBold, fontSize: 12, letterSpacing: 0.6, color: Brand.gold, marginBottom: 6 },
  scoutTopic: { fontFamily: Font.displaySemi, fontSize: 14.5, color: c.text, marginBottom: 5 },
  scoutBody: { fontFamily: Font.body, fontSize: 13.5, lineHeight: 20, color: c.textSecondary },
  scoutNote: { fontFamily: Font.body, fontSize: 11.5, lineHeight: 17, color: c.textMuted, marginTop: 4 },
});
