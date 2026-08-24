import { Ionicons } from '@expo/vector-icons';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { Modal, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { RidgeMark } from '@/components/ui';
import { Brand, Font, surfaces } from '@/constants/brand';
import { ALL_COACH_KEYS } from '@/lib/coach-keys';

const c = surfaces(true);

/**
 * "How the app works", reachable from the You tab.
 *
 * The first-run onboarding is a one-shot: dismiss it and there is no way back to it, which
 * is fine for a welcome and useless as a reference. This is the reference — what each tab
 * holds, in tab-bar order, so the answer to "where do I find X" is one screen rather than a
 * hunt. It's also the only place the coaching can be re-armed after it's been dismissed.
 */

const TABS: { icon: keyof typeof Ionicons.glyphMap | 'ridge'; name: string; body: string }[] = [
  {
    icon: 'ridge',
    name: 'Pulse',
    body: "Home. The next game, this morning's briefing, and a live 0–100 score for each program. Tap any program to see what moved its score and drag the chart to read any day.",
  },
  {
    icon: 'american-football',
    name: 'Scores',
    body: 'Every result and upcoming game. Tap a game for the box score, venue, and how the season looked around it.',
  },
  {
    icon: 'newspaper',
    name: 'News',
    body: 'WVU headlines as they land. Tapping a story opens it at the source.',
  },
  {
    icon: 'people',
    name: 'Team',
    body: 'Rosters and roster movement — transfers in and out, signees, departures. Switch sport at the top, and tap a player for their profile.',
  },
  {
    icon: 'person',
    name: 'You',
    body: 'Favorite sports (starred programs move to the top of your Pulse), alerts, and reporting anything that looks wrong.',
  },
];

export function HelpSheet({
  visible,
  onClose,
  onReplayIntro,
  onOpenPulseExplainer,
}: {
  visible: boolean;
  onClose: () => void;
  onReplayIntro: () => void;
  onOpenPulseExplainer: () => void;
}) {
  const insets = useSafeAreaInsets();

  // Clearing the flags re-arms the home-screen coach mark and the chart's scrub demo. The
  // Pulse tab re-reads them on focus, so this takes effect on the next visit, not a restart.
  const replayTips = async () => {
    await AsyncStorage.multiRemove(ALL_COACH_KEYS).catch(() => {});
    onClose();
  };

  return (
    <Modal visible={visible} animationType="slide" transparent onRequestClose={onClose}>
      <View style={styles.backdrop}>
        <Pressable style={StyleSheet.absoluteFill} onPress={onClose} />
        <View style={[styles.sheet, { paddingBottom: insets.bottom + 16 }]}>
          <View style={styles.grip} />
          <View style={styles.headerRow}>
            <Text style={styles.title}>How the app works</Text>
            <Pressable hitSlop={12} onPress={onClose}>
              <Ionicons name="close" size={22} color={c.textMuted} />
            </Pressable>
          </View>
          <Text style={styles.sub}>Five tabs. Here's what lives in each one.</Text>

          <ScrollView style={{ marginTop: 16 }} contentContainerStyle={{ gap: 12, paddingBottom: 8 }}>
            {TABS.map((t) => (
              <View key={t.name} style={styles.row}>
                <View style={styles.tile}>
                  {t.icon === 'ridge' ? (
                    <RidgeMark size={19} color={Brand.gold} boxed={false} />
                  ) : (
                    <Ionicons name={t.icon as keyof typeof Ionicons.glyphMap} size={17} color={Brand.gold} />
                  )}
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.rowTitle}>{t.name}</Text>
                  <Text style={styles.rowBody}>{t.body}</Text>
                </View>
              </View>
            ))}

            <Text style={styles.moreHead}>More</Text>

            <Pressable style={styles.action} onPress={onOpenPulseExplainer}>
              <Ionicons name="pulse-outline" size={17} color={Brand.gold} />
              <Text style={styles.actionText}>What goes into the Pulse score</Text>
              <Ionicons name="chevron-forward" size={16} color={c.textMuted} />
            </Pressable>

            <Pressable style={styles.action} onPress={onReplayIntro}>
              <Ionicons name="play-circle-outline" size={17} color={Brand.gold} />
              <Text style={styles.actionText}>Replay the welcome tour</Text>
              <Ionicons name="chevron-forward" size={16} color={c.textMuted} />
            </Pressable>

            <Pressable style={styles.action} onPress={replayTips}>
              <Ionicons name="bulb-outline" size={17} color={Brand.gold} />
              <Text style={styles.actionText}>Show the in-app tips again</Text>
              <Ionicons name="chevron-forward" size={16} color={c.textMuted} />
            </Pressable>
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
    maxHeight: '86%',
  },
  grip: { alignSelf: 'center', width: 40, height: 4, borderRadius: 2, backgroundColor: c.surface2, marginBottom: 14 },
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
  moreHead: {
    fontFamily: Font.bodyBold,
    fontSize: 11,
    letterSpacing: 0.8,
    textTransform: 'uppercase',
    color: c.textMuted,
    marginTop: 10,
  },
  action: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    backgroundColor: c.bg,
    borderWidth: 1,
    borderColor: c.border,
    borderRadius: 12,
    paddingHorizontal: 14,
    paddingVertical: 13,
  },
  actionText: { flex: 1, fontFamily: Font.bodySemi, fontSize: 13.5, color: c.text },
});
