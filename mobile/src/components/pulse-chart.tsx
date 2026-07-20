import * as Haptics from 'expo-haptics';
import { useEffect, useMemo, useRef, useState } from 'react';
import { Dimensions, PanResponder, StyleSheet, Text, View } from 'react-native';
import Animated, {
  Easing,
  cancelAnimation,
  runOnJS,
  useAnimatedProps,
  useAnimatedStyle,
  useSharedValue,
  withTiming,
} from 'react-native-reanimated';
import Svg, { Circle, Defs, Line, LinearGradient, Polygon, Polyline, Stop, Text as SvgText } from 'react-native-svg';

import { Brand, Font, surfaces } from '@/constants/brand';

const c = surfaces(true);

// SVG elements driven from the UI thread — the line "draws" via strokeDashoffset
// and the gradient fill fades in underneath it, all without JS-thread jank.
const APolyline = Animated.createAnimatedComponent(Polyline);
const APolygon = Animated.createAnimatedComponent(Polygon);

const DRAW_MS = 900; // one orchestrated beat: line draw + score count-up finish together

export type ChartPoint = { date: string; score: number };

// Parse a 'YYYY-MM-DD' as a LOCAL calendar date. `new Date('2026-07-20')` parses as UTC
// midnight, which in a western timezone renders as the PREVIOUS day — so the chart's last
// point read "Jul 19" instead of today. Building the date from its parts keeps it put.
function localDate(iso: string): Date {
  const [y, m, d] = iso.slice(0, 10).split('-').map(Number);
  return new Date(y, m - 1, d);
}

function shortDate(iso: string): string {
  const d = localDate(iso);
  return `${d.getMonth() + 1}/${d.getDate()}`;
}

function tooltipDate(iso: string): string {
  return localDate(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric' }).toUpperCase();
}

const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));

export function PulseChart({
  data,
  color = Brand.gold,
  textColor,
  gridColor,
  height = 210,
  width,
  onActiveChange,
  runDemo = false,
  onDemoComplete,
}: {
  data: ChartPoint[];
  color?: string;
  textColor: string;
  gridColor: string;
  height?: number;
  width?: number;
  onActiveChange?: (index: number) => void;
  runDemo?: boolean;
  onDemoComplete?: () => void;
}) {
  const W = width ?? Dimensions.get('window').width - 64;
  const pad = { top: 22, right: 14, bottom: 26, left: 30 };
  const w = W - pad.left - pad.right;
  const h = height - pad.top - pad.bottom;
  const n = data.length;

  // Active (scrubbed) point — defaults to the latest, resets when data changes.
  const [active, setActive] = useState<number>(n - 1);
  useEffect(() => {
    setActive(n - 1);
  }, [data, n]);
  // Demo (auto-scrub) machinery — see below. Held here so the callback effect can
  // suppress onActiveChange while the demo drives `active`, keeping the detail screen's
  // own state from jumping around during the teaching sweep.
  const demoTimer = useRef<ReturnType<typeof setInterval> | null>(null);
  const demoing = useRef(false);
  const demoRan = useRef(false);

  useEffect(() => {
    if (n >= 2 && !demoing.current) onActiveChange?.(active);
  }, [active, n, onActiveChange]);

  const scores = data.map((d) => d.score);
  const lo = Math.max(0, Math.min(...scores) - 6);
  const hi = Math.min(100, Math.max(...scores) + 6);
  const span = Math.max(1, hi - lo);

  const x = (i: number) => pad.left + (i / (n - 1)) * w;
  const y = (s: number) => pad.top + (1 - (s - lo) / span) * h;

  const idxFromX = (px: number) => clamp(Math.round(((px - pad.left) / w) * (n - 1)), 0, n - 1);

  // ---- Draw-in animation ----------------------------------------------------
  // progress 0→1 reveals the line left-to-right (stroke-dash trick) and fades the
  // area fill in. Interaction is gated on `drawn`; touching mid-draw completes it
  // instantly so scrubbing is never blocked.
  const progress = useSharedValue(0);
  const ring = useSharedValue(0); // one-time endpoint pulse after the draw lands
  const [drawn, setDrawn] = useState(false);
  const drawnRef = useRef(false);
  drawnRef.current = drawn;

  // Total polyline length so strokeDasharray/offset can hide-then-reveal it.
  const totalLen = useMemo(() => {
    if (n < 2) return 1;
    let L = 0;
    for (let i = 1; i < n; i++) {
      L += Math.hypot(x(i) - x(i - 1), y(data[i].score) - y(data[i - 1].score));
    }
    return Math.max(1, L);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, W, height]);

  const finishDraw = () => {
    setDrawn(true);
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light).catch(() => {});
  };

  useEffect(() => {
    if (n < 2) return;
    setDrawn(false);
    ring.value = 0;
    progress.value = 0;
    progress.value = withTiming(1, { duration: DRAW_MS, easing: Easing.out(Easing.cubic) }, (finished) => {
      if (finished) {
        ring.value = withTiming(1, { duration: 650, easing: Easing.out(Easing.quad) });
        runOnJS(finishDraw)();
      }
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data]);

  const lineProps = useAnimatedProps(() => ({
    strokeDashoffset: totalLen * (1 - progress.value),
  }));
  const fillProps = useAnimatedProps(() => ({
    // Fill eases in during the second half of the draw so the line leads the moment.
    opacity: Math.max(0, (progress.value - 0.35) / 0.65),
  }));
  const ringStyle = useAnimatedStyle(() => ({
    opacity: ring.value === 0 ? 0 : (1 - ring.value) * 0.55,
    transform: [{ scale: 0.5 + ring.value * 1.5 }],
  }));

  // ---- One-time "how to scrub" demo ----------------------------------------
  // The first time a user ever opens a Pulse, the crosshair glides across the chart
  // and back once so the hidden scrub gesture is discoverable. Drives the chart's own
  // `active` (so the crosshair + tooltip really move) but suppresses onActiveChange, so
  // it's purely a visual lesson. Fires after the draw-in; a saved flag (in the parent)
  // keeps it to once ever, and any touch cancels it so it never blocks the user.
  const stopDemo = () => {
    if (demoTimer.current) {
      clearInterval(demoTimer.current);
      demoTimer.current = null;
    }
    demoing.current = false;
  };
  const startDemo = () => {
    demoing.current = true;
    const lowIdx = Math.floor((n - 1) * 0.35);
    const steps = 16;
    const seq: number[] = [];
    for (let k = 0; k <= steps; k++) {
      const t = k / steps;
      const tri = t < 0.5 ? t * 2 : (1 - t) * 2; // n-1 → lowIdx → n-1 (a there-and-back sweep)
      seq.push(Math.round(n - 1 - tri * (n - 1 - lowIdx)));
    }
    let k = 0;
    demoTimer.current = setInterval(() => {
      setActive(seq[k]);
      if (k % 4 === 0) Haptics.selectionAsync().catch(() => {}); // a few soft ticks, not a buzz
      k += 1;
      if (k >= seq.length) {
        stopDemo();
        setActive(n - 1);
        onDemoComplete?.();
      }
    }, 80);
  };
  useEffect(() => {
    if (runDemo && drawn && !demoRan.current && n >= 2) {
      demoRan.current = true;
      startDemo();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runDemo, drawn, n]);
  useEffect(() => () => stopDemo(), []); // clean up the interval on unmount

  // ---- Scrub with haptic ticks ---------------------------------------------
  const lastTick = useRef(-1);
  const scrubTo = (px: number) => {
    if (demoTimer.current) stopDemo(); // user takes over → cancel the demo immediately
    if (!drawnRef.current) {
      // A touch mid-draw completes the animation instantly — never fight the user.
      cancelAnimation(progress);
      progress.value = 1;
      setDrawn(true);
    }
    const i = idxFromX(px);
    setActive(i);
    if (i !== lastTick.current) {
      lastTick.current = i;
      Haptics.selectionAsync().catch(() => {}); // per-day tick, the Stocks-app feel
    }
  };

  const panResponder = useMemo(
    () =>
      PanResponder.create({
        // Grab the touch immediately so tapping/dragging the chart scrubs it
        // (on native the SVG would otherwise swallow the gesture).
        onStartShouldSetPanResponder: () => true,
        onStartShouldSetPanResponderCapture: () => true,
        onMoveShouldSetPanResponder: () => true,
        onPanResponderTerminationRequest: () => false,
        onPanResponderGrant: (evt) => scrubTo(evt.nativeEvent.locationX),
        onPanResponderMove: (evt) => scrubTo(evt.nativeEvent.locationX),
        // eslint-disable-next-line react-hooks/exhaustive-deps
      }),
    [n, w, pad.left],
  );

  if (n < 2) return null;

  const line = data.map((d, i) => `${x(i)},${y(d.score)}`).join(' ');
  const area = `${pad.left},${pad.top + h} ${line} ${x(n - 1)},${pad.top + h}`;
  const tickIdx = [0, Math.floor((n - 1) / 2), n - 1];

  const ai = clamp(active, 0, n - 1);
  const ax = x(ai);
  const ay = y(data[ai].score);
  const endX = x(n - 1);
  const endY = y(data[n - 1].score);

  // Floating tooltip (date + score + trend), following the active point.
  const prevScore = ai > 0 ? data[ai - 1].score : data[ai].score;
  const dir = data[ai].score > prevScore ? 'up' : data[ai].score < prevScore ? 'down' : 'flat';
  const arrowColor = dir === 'up' ? Brand.green : dir === 'down' ? Brand.red : c.textSecondary;
  const arrow = dir === 'up' ? '▲' : dir === 'down' ? '▼' : '';
  const ttW = 96;
  const ttLeft = clamp(ax - ttW / 2, 2, W - ttW - 2);
  const ttTop = ay - 54 > 2 ? ay - 54 : ay + 14;

  const RING = 20; // endpoint pulse ring radius (RN view overlay, not SVG)

  return (
    <View {...panResponder.panHandlers} style={{ width: W, height }}>
      <Svg width={W} height={height} pointerEvents="none">
        <Defs>
          <LinearGradient id="pulseFill" x1="0" y1="0" x2="0" y2="1">
            <Stop offset="0" stopColor={color} stopOpacity={0.28} />
            <Stop offset="1" stopColor={color} stopOpacity={0.02} />
          </LinearGradient>
        </Defs>

        {/* horizontal gridlines + y labels (hi / mid / lo) */}
        {[hi, Math.round((hi + lo) / 2), lo].map((v, i) => (
          <Line key={`g${i}`} x1={pad.left} y1={y(v)} x2={pad.left + w} y2={y(v)} stroke={gridColor} strokeWidth={1} />
        ))}
        {[hi, lo].map((v, i) => (
          <SvgText key={`y${i}`} x={pad.left - 6} y={y(v) + 3} fontSize={10} fill={textColor} textAnchor="end">
            {v}
          </SvgText>
        ))}

        {/* area + line — revealed by the draw-in animation */}
        <APolygon points={area} fill="url(#pulseFill)" animatedProps={fillProps} />
        <APolyline
          points={line}
          fill="none"
          stroke={color}
          strokeWidth={2.5}
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeDasharray={`${totalLen},${totalLen}`}
          animatedProps={lineProps}
        />

        {/* active crosshair + hollow dot — after the draw so the reveal stays clean */}
        {drawn && (
          <>
            <Line x1={ax} y1={pad.top} x2={ax} y2={pad.top + h} stroke={color} strokeWidth={1} strokeDasharray="3,4" opacity={0.5} />
            <Circle cx={ax} cy={ay} r={8} fill={color} opacity={0.18} />
            <Circle cx={ax} cy={ay} r={5} fill="#060B16" stroke={color} strokeWidth={2.5} />
          </>
        )}

        {/* x date ticks */}
        {tickIdx.map((i, k) => (
          <SvgText
            key={`x${k}`}
            x={x(i)}
            y={height - 6}
            fontSize={10}
            fill={textColor}
            textAnchor={k === 0 ? 'start' : k === tickIdx.length - 1 ? 'end' : 'middle'}>
            {shortDate(data[i].date)}
          </SvgText>
        ))}
      </Svg>

      {/* one-time endpoint pulse ring, fired the moment the line lands */}
      <Animated.View
        pointerEvents="none"
        style={[
          {
            position: 'absolute',
            left: endX - RING,
            top: endY - RING,
            width: RING * 2,
            height: RING * 2,
            borderRadius: RING,
            borderWidth: 2,
            borderColor: color,
          },
          ringStyle,
        ]}
      />

      {/* floating tooltip card — matches the 2C design */}
      {drawn && (
        <View pointerEvents="none" style={[styles.tooltip, { left: ttLeft, top: ttTop, width: ttW }]}>
          <Text style={styles.ttDate}>{tooltipDate(data[ai].date)}</Text>
          <Text style={styles.ttScore}>
            {data[ai].score}
            {arrow ? <Text style={{ color: arrowColor, fontSize: 11 }}> {arrow}</Text> : null}
          </Text>
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  tooltip: {
    position: 'absolute',
    backgroundColor: '#131D30',
    borderWidth: 1,
    borderColor: 'rgba(234,170,0,0.35)',
    borderRadius: 10,
    paddingHorizontal: 10,
    paddingVertical: 6,
    shadowColor: '#000',
    shadowOpacity: 0.5,
    shadowRadius: 14,
    shadowOffset: { width: 0, height: 8 },
    elevation: 10,
  },
  ttDate: { fontFamily: Font.bodyBold, fontSize: 10, letterSpacing: 0.8, color: c.textMuted },
  ttScore: { fontFamily: Font.black, fontSize: 16, color: Brand.gold, marginTop: 1 },
});
