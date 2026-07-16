import { Ionicons } from '@expo/vector-icons';
import { useState } from 'react';
import { ActivityIndicator, Modal, Pressable, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { RidgeMark, SportIcon, Wordmark } from '@/components/ui';
import { Brand, Font, surfaces } from '@/constants/brand';
import { enableAlerts } from '@/lib/notifications';

const c = surfaces(true);

const SAMPLE = [
  { sport: 'football', n: 67 },
  { sport: 'mbb', n: 77 },
  { sport: 'baseball', n: 85 },
];

export function Onboarding({ visible, onDone }: { visible: boolean; onDone: () => void }) {
  const insets = useSafeAreaInsets();
  const [step, setStep] = useState(0);
  const [busy, setBusy] = useState(false);
  const last = step === 2;

  const enable = async () => {
    setBusy(true);
    await enableAlerts(); // fires the iOS permission dialog; result doesn't gate finishing
    setBusy(false);
    onDone();
  };

  return (
    <Modal visible={visible} animationType="fade" transparent={false} onRequestClose={onDone}>
      <View style={[styles.root, { paddingTop: insets.top + 24, paddingBottom: insets.bottom + 20 }]}>
        {/* Progress dots */}
        <View style={styles.dots}>
          {[0, 1, 2].map((i) => (
            <View key={i} style={[styles.dot, i === step && styles.dotOn]} />
          ))}
        </View>

        <View style={styles.body}>
          {step === 0 && (
            <>
              <View style={styles.hero}>
                <RidgeMark size={72} />
              </View>
              <Wordmark size={30} />
              <Text style={styles.title}>WVU sports,{'\n'}one heartbeat.</Text>
              <Text style={styles.sub}>
                Your daily home for West Virginia football, men's basketball, and baseball — scores,
                rosters, roster movement, and a morning briefing, all in one place.
              </Text>
            </>
          )}

          {step === 1 && (
            <>
              <View style={styles.pulseRow}>
                {SAMPLE.map((s) => (
                  <View key={s.sport} style={styles.pulseCard}>
                    <SportIcon sport={s.sport} size={22} color={Brand.gold} />
                    <Text style={styles.pulseNum}>{s.n}</Text>
                    <Text style={styles.pulseLbl}>PULSE</Text>
                  </View>
                ))}
              </View>
              <Text style={styles.title}>Meet the Pulse</Text>
              <Text style={styles.sub}>
                Every program gets a live 0–100 score that moves with real events — wins, losses,
                national ranking, and roster moves. Tap any team to see exactly what's driving it,
                day by day.
              </Text>
            </>
          )}

          {step === 2 && (
            <>
              <View style={styles.bell}>
                <Ionicons name="notifications" size={40} color={Brand.gold} />
              </View>
              <Text style={styles.title}>Never miss a moment</Text>
              <Text style={styles.sub}>
                Turn on alerts to get the morning briefing and breaking WVU news the second it drops.
                You can change this anytime in the You tab.
              </Text>
            </>
          )}
        </View>

        <View style={styles.footer}>
          {!last ? (
            <>
              <Pressable style={styles.primary} onPress={() => setStep(step + 1)}>
                <Text style={styles.primaryText}>Continue</Text>
              </Pressable>
              <Pressable hitSlop={10} onPress={onDone}>
                <Text style={styles.skip}>Skip</Text>
              </Pressable>
            </>
          ) : (
            <>
              <Pressable style={[styles.primary, busy && { opacity: 0.7 }]} disabled={busy} onPress={enable}>
                {busy ? (
                  <ActivityIndicator color={Brand.onGold} />
                ) : (
                  <Text style={styles.primaryText}>Enable alerts</Text>
                )}
              </Pressable>
              <Pressable hitSlop={10} onPress={onDone} disabled={busy}>
                <Text style={styles.skip}>Maybe later</Text>
              </Pressable>
            </>
          )}
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: c.bg, paddingHorizontal: 28, alignItems: 'center' },
  dots: { flexDirection: 'row', gap: 8, marginBottom: 8 },
  dot: { width: 7, height: 7, borderRadius: 4, backgroundColor: c.border },
  dotOn: { backgroundColor: Brand.gold, width: 22 },
  body: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: 4 },
  hero: {
    width: 118, height: 118, borderRadius: 30, marginBottom: 22,
    alignItems: 'center', justifyContent: 'center',
    backgroundColor: Brand.goldTint, borderWidth: 1, borderColor: Brand.goldBorder,
  },
  bell: {
    width: 96, height: 96, borderRadius: 48, marginBottom: 26,
    alignItems: 'center', justifyContent: 'center',
    backgroundColor: Brand.goldTint, borderWidth: 1, borderColor: Brand.goldBorder,
  },
  title: {
    fontFamily: Font.black, fontSize: 30, lineHeight: 34, color: c.text,
    textAlign: 'center', letterSpacing: -0.6, marginTop: 18,
  },
  sub: {
    fontFamily: Font.body, fontSize: 15.5, lineHeight: 23, color: c.textSecondary,
    textAlign: 'center', marginTop: 14, maxWidth: 340,
  },
  pulseRow: { flexDirection: 'row', gap: 12, marginBottom: 4 },
  pulseCard: {
    width: 88, paddingVertical: 16, borderRadius: 18, alignItems: 'center', gap: 4,
    backgroundColor: c.card, borderWidth: 1, borderColor: c.border,
  },
  pulseNum: { fontFamily: Font.black, fontSize: 28, color: Brand.gold, marginTop: 4 },
  pulseLbl: { fontFamily: Font.bodyBold, fontSize: 9, letterSpacing: 1, color: c.textMuted },
  footer: { width: '100%', alignItems: 'center', gap: 16 },
  primary: {
    width: '100%', backgroundColor: Brand.gold, borderRadius: 16, paddingVertical: 17,
    alignItems: 'center', justifyContent: 'center',
  },
  primaryText: { fontFamily: Font.display, fontSize: 16, color: Brand.onGold, letterSpacing: 0.2 },
  skip: { fontFamily: Font.bodySemi, fontSize: 14, color: c.textMuted },
});
