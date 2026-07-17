import { useEffect } from 'react';
import { DimensionValue, StyleProp, StyleSheet, View, ViewStyle } from 'react-native';
import Animated, { Easing, useAnimatedStyle, useSharedValue, withRepeat, withTiming } from 'react-native-reanimated';

import { surfaces } from '@/constants/brand';

const c = surfaces(true);

/**
 * A single shimmering placeholder block. All blocks mount together and share the
 * same ~1s breathing curve, so a screen of them pulses in unison rather than as
 * scattered flicker. Runs on the UI thread (Reanimated), so it stays smooth while
 * the real data is still fetching.
 */
export function Skeleton({
  width = '100%',
  height,
  radius = 8,
  style,
}: {
  width?: DimensionValue;
  height: number;
  radius?: number;
  style?: StyleProp<ViewStyle>;
}) {
  const t = useSharedValue(0);
  useEffect(() => {
    t.value = withRepeat(withTiming(1, { duration: 900, easing: Easing.inOut(Easing.ease) }), -1, true);
  }, [t]);
  const anim = useAnimatedStyle(() => ({ opacity: 0.3 + t.value * 0.35 }));
  return <Animated.View style={[{ width, height, borderRadius: radius, backgroundColor: c.surface2 }, anim, style]} />;
}

// ---- Composed skeletons, shaped to match each screen's real content ---------

export function BriefingSkeleton() {
  return (
    <View style={styles.card}>
      <Skeleton width={90} height={11} radius={4} />
      <View style={{ height: 14 }} />
      <Skeleton width={'100%'} height={12} radius={4} />
      <View style={{ height: 8 }} />
      <Skeleton width={'92%'} height={12} radius={4} />
      <View style={{ height: 8 }} />
      <Skeleton width={'70%'} height={12} radius={4} />
    </View>
  );
}

/** Matches the home-screen program row: tile + name/chips + sparkline + score. */
export function PulseRowSkeleton() {
  return (
    <View style={styles.row}>
      <Skeleton width={44} height={44} radius={12} />
      <View style={{ flex: 1, gap: 8 }}>
        <Skeleton width={'55%'} height={13} radius={4} />
        <Skeleton width={'38%'} height={16} radius={999} />
      </View>
      <Skeleton width={56} height={30} radius={6} />
      <Skeleton width={34} height={26} radius={6} />
    </View>
  );
}

/** Matches the scores GameCard: tile + matchup/meta + result. */
export function GameCardSkeleton() {
  return (
    <View style={[styles.row, { marginBottom: 8 }]}>
      <Skeleton width={40} height={40} radius={11} />
      <View style={{ flex: 1, gap: 7 }}>
        <Skeleton width={'60%'} height={14} radius={4} />
        <Skeleton width={'40%'} height={11} radius={4} />
      </View>
      <Skeleton width={52} height={18} radius={5} />
    </View>
  );
}

/** Matches a news card: tag + source line + two headline lines. */
export function NewsCardSkeleton() {
  return (
    <View style={styles.newsCard}>
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
        <Skeleton width={34} height={16} radius={999} />
        <Skeleton width={'45%'} height={11} radius={4} />
      </View>
      <View style={{ height: 10 }} />
      <Skeleton width={'100%'} height={14} radius={4} />
      <View style={{ height: 7 }} />
      <Skeleton width={'75%'} height={14} radius={4} />
    </View>
  );
}

/** A simple roster/leaders row: avatar + two lines + trailing value. */
export function ListRowSkeleton() {
  return (
    <View style={[styles.row, { marginBottom: 8 }]}>
      <Skeleton width={38} height={38} radius={19} />
      <View style={{ flex: 1, gap: 7 }}>
        <Skeleton width={'50%'} height={14} radius={4} />
        <Skeleton width={'32%'} height={11} radius={4} />
      </View>
      <Skeleton width={28} height={16} radius={4} />
    </View>
  );
}

/** Repeats a skeleton element `count` times — for lists. */
export function SkeletonList({ count, children }: { count: number; children: React.ReactNode }) {
  return <>{Array.from({ length: count }).map((_, i) => <View key={i}>{children}</View>)}</>;
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: c.card,
    borderWidth: 1,
    borderColor: c.border,
    borderRadius: 18,
    padding: 18,
  },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    backgroundColor: c.card,
    borderWidth: 1,
    borderColor: c.border,
    borderRadius: 16,
    padding: 14,
  },
  newsCard: {
    backgroundColor: c.card,
    borderWidth: 1,
    borderColor: c.border,
    borderRadius: 16,
    padding: 14,
  },
});
