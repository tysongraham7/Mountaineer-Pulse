import { Ionicons } from '@expo/vector-icons';
import { useEffect, useRef } from 'react';
import { Animated, Easing, Pressable, StyleSheet, Text, View } from 'react-native';

import { Brand, Font, surfaces } from '@/constants/brand';

const c = surfaces(true);

/**
 * First-run coaching for the Program Pulse, in two stages.
 *
 * The beta shipped with the Pulse detail opened in only ~4% of sessions, and the cause wasn't
 * that people forgot an onboarding slide — it was that the home screen never asked them to
 * tap. The rows carry a number, a sparkline and no affordance, and the one line of guidance
 * sat *below* all three of them, under the fold on most phones.
 *
 * So the coaching happens where the thing is, in the order a first-timer meets it:
 *   1. ScrollNudge  — a floating pill while the Pulse section is still off-screen, because
 *                     you can't point at a row nobody has scrolled to. Tapping it scrolls.
 *   2. TapCallout   — an inline card directly above the first row once the section is in
 *                     view, pointing down at the thing it wants tapped.
 *
 * Both are inline/absolute views rather than a modal overlay on purpose: no measuring, no
 * chance of the highlight drifting off its target when the briefing above changes height.
 */

/** Stage 1: shown while the Pulse section is still below the fold. */
export function ScrollNudge({ onPress, bottom }: { onPress: () => void; bottom: number }) {
  const bob = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    const loop = Animated.loop(
      Animated.sequence([
        Animated.timing(bob, { toValue: 1, duration: 700, easing: Easing.inOut(Easing.quad), useNativeDriver: true }),
        Animated.timing(bob, { toValue: 0, duration: 700, easing: Easing.inOut(Easing.quad), useNativeDriver: true }),
      ]),
    );
    loop.start();
    return () => loop.stop();
  }, [bob]);

  const translateY = bob.interpolate({ inputRange: [0, 1], outputRange: [0, 4] });

  return (
    <Animated.View style={[styles.nudgeWrap, { bottom }, { transform: [{ translateY }] }]} pointerEvents="box-none">
      <Pressable onPress={onPress} style={({ pressed }) => [styles.nudge, pressed && { opacity: 0.8 }]}>
        <Text style={styles.nudgeText}>See your Program Pulse</Text>
        <Ionicons name="arrow-down" size={15} color={Brand.onGold} />
      </Pressable>
    </Animated.View>
  );
}

/** Stage 2: inline card sitting directly above the first Pulse row. */
export function TapCallout({ onDismiss }: { onDismiss: () => void }) {
  const fade = useRef(new Animated.Value(0)).current;
  const tap = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    Animated.timing(fade, { toValue: 1, duration: 320, useNativeDriver: true }).start();
    const loop = Animated.loop(
      Animated.sequence([
        Animated.timing(tap, { toValue: 1, duration: 620, easing: Easing.out(Easing.quad), useNativeDriver: true }),
        Animated.timing(tap, { toValue: 0, duration: 620, easing: Easing.in(Easing.quad), useNativeDriver: true }),
      ]),
    );
    loop.start();
    return () => loop.stop();
  }, [fade, tap]);

  const scale = tap.interpolate({ inputRange: [0, 1], outputRange: [1, 1.18] });

  return (
    <Animated.View style={[styles.callout, { opacity: fade }]}>
      <View style={styles.calloutRow}>
        <Animated.View style={[styles.calloutIcon, { transform: [{ scale }] }]}>
          <Ionicons name="hand-left" size={16} color={Brand.gold} />
        </Animated.View>
        <View style={{ flex: 1 }}>
          <Text style={styles.calloutTitle}>Tap a Pulse score</Text>
          <Text style={styles.calloutBody}>
            Every program has a live 0–100 score. Tap one to see what moved it — then drag across
            the chart to read any day.
          </Text>
        </View>
        <Pressable hitSlop={10} onPress={onDismiss}>
          <Ionicons name="close" size={18} color={c.textMuted} />
        </Pressable>
      </View>
      {/* Points at the row immediately below. */}
      <View style={styles.beak} />
    </Animated.View>
  );
}

/** A soft breathing ring drawn over the row the callout is pointing at. */
export function AttentionRing() {
  const glow = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    const loop = Animated.loop(
      Animated.sequence([
        Animated.timing(glow, { toValue: 1, duration: 900, easing: Easing.inOut(Easing.quad), useNativeDriver: true }),
        Animated.timing(glow, { toValue: 0, duration: 900, easing: Easing.inOut(Easing.quad), useNativeDriver: true }),
      ]),
    );
    loop.start();
    return () => loop.stop();
  }, [glow]);

  const opacity = glow.interpolate({ inputRange: [0, 1], outputRange: [0.25, 0.9] });

  return <Animated.View pointerEvents="none" style={[styles.ring, { opacity }]} />;
}

const styles = StyleSheet.create({
  nudgeWrap: { position: 'absolute', left: 0, right: 0, alignItems: 'center' },
  nudge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    backgroundColor: Brand.gold,
    borderRadius: 999,
    paddingVertical: 11,
    paddingHorizontal: 18,
    shadowColor: '#000',
    shadowOpacity: 0.35,
    shadowRadius: 12,
    shadowOffset: { width: 0, height: 4 },
    elevation: 6,
  },
  nudgeText: { fontFamily: Font.display, fontSize: 14, color: Brand.onGold, letterSpacing: 0.1 },

  callout: {
    backgroundColor: Brand.goldTint,
    borderWidth: 1,
    borderColor: Brand.goldBorder,
    borderRadius: 16,
    paddingHorizontal: 14,
    paddingVertical: 13,
    marginBottom: 12,
  },
  calloutRow: { flexDirection: 'row', alignItems: 'flex-start', gap: 11 },
  calloutIcon: {
    width: 32,
    height: 32,
    borderRadius: 10,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: 'rgba(0,0,0,0.18)',
    borderWidth: 1,
    borderColor: Brand.goldBorder,
  },
  calloutTitle: { fontFamily: Font.bodyBold, fontSize: 14, color: c.text },
  calloutBody: { fontFamily: Font.body, fontSize: 12.5, lineHeight: 18, color: c.textSecondary, marginTop: 2 },
  beak: {
    position: 'absolute',
    bottom: -6,
    left: 30,
    width: 12,
    height: 12,
    backgroundColor: Brand.goldTint,
    borderRightWidth: 1,
    borderBottomWidth: 1,
    borderColor: Brand.goldBorder,
    transform: [{ rotate: '45deg' }],
  },
  ring: {
    ...StyleSheet.absoluteFillObject,
    borderRadius: 18,
    borderWidth: 1.5,
    borderColor: Brand.gold,
  },
});
