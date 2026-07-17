import { Ionicons } from '@expo/vector-icons';
import { Modal, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { Brand, Font, surfaces } from '@/constants/brand';

const c = surfaces(true);

type Driver = { label: string; delta?: number; kind: string };

const PARTS: { icon: keyof typeof Ionicons.glyphMap; title: string; body: string }[] = [
  {
    icon: 'trophy-outline',
    title: 'Record & ranking',
    body: 'The anchor. Wins, losses, and national standing set the baseline — a ranked team starts high.',
  },
  {
    icon: 'trending-up-outline',
    title: 'Recent form',
    body: 'The last five games against the season average. Hot and cold streaks bend the line.',
  },
  {
    icon: 'swap-horizontal-outline',
    title: 'Roster moves',
    body: 'Transfers in and out, signees, and departures each nudge the score — marquee moves count more.',
  },
  {
    icon: 'newspaper-outline',
    title: 'News',
    body: 'Real headlines add or subtract, and they hold — a drop stays until later news offsets it.',
  },
  {
    icon: 'flame-outline',
    title: 'Postseason',
    body: 'Tournament and College World Series runs surge the score; early exits pull it back.',
  },
];

export function PulseExplainer({
  visible,
  onClose,
  sportName,
  drivers,
}: {
  visible: boolean;
  onClose: () => void;
  sportName?: string;
  drivers?: Driver[] | null;
}) {
  const insets = useSafeAreaInsets();
  const live = (drivers ?? []).filter((d) => d.label);

  return (
    <Modal visible={visible} animationType="slide" transparent onRequestClose={onClose}>
      <View style={styles.backdrop}>
        <Pressable style={StyleSheet.absoluteFill} onPress={onClose} />
        <View style={[styles.sheet, { paddingBottom: insets.bottom + 16 }]}>
          <View style={styles.grip} />
          <View style={styles.headerRow}>
            <Text style={styles.title}>How the Pulse works</Text>
            <Pressable hitSlop={12} onPress={onClose}>
              <Ionicons name="close" size={22} color={c.textMuted} />
            </Pressable>
          </View>
          <Text style={styles.sub}>
            One number, 0–100, for the live health of each program. It only moves when something
            real happens — a game, a ranking change, a roster move, or news.
          </Text>

          <ScrollView style={{ marginTop: 16 }} contentContainerStyle={{ gap: 10 }} bounces={false}>
            {PARTS.map((p) => (
              <View key={p.title} style={styles.row}>
                <View style={styles.tile}>
                  <Ionicons name={p.icon} size={17} color={Brand.gold} />
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.rowTitle}>{p.title}</Text>
                  <Text style={styles.rowBody}>{p.body}</Text>
                </View>
              </View>
            ))}

            {live.length > 0 && (
              <>
                <Text style={styles.liveHead}>
                  {`Driving ${sportName ?? 'this team'} right now`}
                </Text>
                <View style={{ gap: 6 }}>
                  {live.map((d, i) => {
                    const has = d.delta !== undefined && d.delta !== null;
                    const pos = (d.delta ?? 0) >= 0;
                    return (
                      <View key={i} style={styles.liveRow}>
                        <Text style={styles.liveLabel}>{d.label}</Text>
                        {has && (
                          <Text style={{ fontFamily: Font.bodyBold, fontSize: 13, color: pos ? Brand.green : Brand.red }}>
                            {pos ? '+' : ''}
                            {d.delta}
                          </Text>
                        )}
                      </View>
                    );
                  })}
                </View>
              </>
            )}

            <Text style={styles.footer}>
              Every move ties to a real event. Scrub the chart to see the exact day anything changed.
            </Text>
          </ScrollView>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: { flex: 1, backgroundColor: 'rgba(0,0,0,0.55)', justifyContent: 'flex-end' },
  sheet: {
    backgroundColor: c.card,
    borderTopLeftRadius: 24,
    borderTopRightRadius: 24,
    borderWidth: 1,
    borderColor: c.borderStrong,
    paddingHorizontal: 22,
    paddingTop: 10,
    maxHeight: '82%',
  },
  grip: {
    alignSelf: 'center',
    width: 40,
    height: 4,
    borderRadius: 2,
    backgroundColor: c.surface2,
    marginBottom: 14,
  },
  headerRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  title: { fontFamily: Font.display, fontSize: 20, color: c.text, letterSpacing: -0.3 },
  sub: { fontFamily: Font.body, fontSize: 13.5, lineHeight: 19, color: c.textSecondary, marginTop: 6 },
  row: { flexDirection: 'row', gap: 12, alignItems: 'flex-start' },
  tile: {
    width: 34,
    height: 34,
    borderRadius: 10,
    backgroundColor: Brand.goldTint,
    borderWidth: 1,
    borderColor: Brand.goldBorder,
    alignItems: 'center',
    justifyContent: 'center',
    marginTop: 1,
  },
  rowTitle: { fontFamily: Font.bodySemi, fontSize: 14, color: c.text },
  rowBody: { fontFamily: Font.body, fontSize: 12.5, lineHeight: 18, color: c.textSecondary, marginTop: 2 },
  liveHead: {
    fontFamily: Font.bodyBold,
    fontSize: 11,
    letterSpacing: 0.8,
    textTransform: 'uppercase',
    color: c.textMuted,
    marginTop: 10,
  },
  liveRow: {
    backgroundColor: c.bg,
    borderWidth: 1,
    borderColor: c.border,
    borderRadius: 12,
    paddingHorizontal: 14,
    paddingVertical: 10,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  liveLabel: { fontSize: 13, color: c.text, fontFamily: Font.bodySemi, flex: 1 },
  footer: {
    fontFamily: Font.body,
    fontSize: 12,
    lineHeight: 17,
    color: c.textMuted,
    textAlign: 'center',
    marginTop: 14,
    marginBottom: 6,
  },
});
