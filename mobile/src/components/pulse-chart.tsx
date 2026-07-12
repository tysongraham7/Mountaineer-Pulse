import { useEffect, useMemo, useState } from 'react';
import { Dimensions, PanResponder, StyleSheet, Text, View } from 'react-native';
import Svg, { Circle, Defs, Line, LinearGradient, Polygon, Polyline, Stop, Text as SvgText } from 'react-native-svg';

import { Brand, Font, surfaces } from '@/constants/brand';

const c = surfaces(true);

export type ChartPoint = { date: string; score: number };

function shortDate(iso: string): string {
  const d = new Date(iso);
  return `${d.getMonth() + 1}/${d.getDate()}`;
}

function tooltipDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric' }).toUpperCase();
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
}: {
  data: ChartPoint[];
  color?: string;
  textColor: string;
  gridColor: string;
  height?: number;
  width?: number;
  onActiveChange?: (index: number) => void;
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
  }, [n]);
  useEffect(() => {
    if (n >= 2) onActiveChange?.(active);
  }, [active, n, onActiveChange]);

  const scores = data.map((d) => d.score);
  const lo = Math.max(0, Math.min(...scores) - 6);
  const hi = Math.min(100, Math.max(...scores) + 6);
  const span = Math.max(1, hi - lo);

  const x = (i: number) => pad.left + (i / (n - 1)) * w;
  const y = (s: number) => pad.top + (1 - (s - lo) / span) * h;

  const idxFromX = (px: number) => clamp(Math.round(((px - pad.left) / w) * (n - 1)), 0, n - 1);

  const panResponder = useMemo(
    () =>
      PanResponder.create({
        // Grab the touch immediately so tapping/dragging the chart scrubs it
        // (on native the SVG would otherwise swallow the gesture).
        onStartShouldSetPanResponder: () => true,
        onStartShouldSetPanResponderCapture: () => true,
        onMoveShouldSetPanResponder: () => true,
        onPanResponderTerminationRequest: () => false,
        onPanResponderGrant: (evt) => setActive(idxFromX(evt.nativeEvent.locationX)),
        onPanResponderMove: (evt) => setActive(idxFromX(evt.nativeEvent.locationX)),
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

  // Floating tooltip (date + score + trend), following the active point.
  const prevScore = ai > 0 ? data[ai - 1].score : data[ai].score;
  const dir = data[ai].score > prevScore ? 'up' : data[ai].score < prevScore ? 'down' : 'flat';
  const arrowColor = dir === 'up' ? Brand.green : dir === 'down' ? Brand.red : c.textSecondary;
  const arrow = dir === 'up' ? '▲' : dir === 'down' ? '▼' : '▶';
  const ttW = 96;
  const ttLeft = clamp(ax - ttW / 2, 2, W - ttW - 2);
  const ttTop = ay - 54 > 2 ? ay - 54 : ay + 14;

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

        {/* area + line */}
        <Polygon points={area} fill="url(#pulseFill)" />
        <Polyline points={line} fill="none" stroke={color} strokeWidth={2.5} />

        {/* active crosshair + hollow dot */}
        <Line x1={ax} y1={pad.top} x2={ax} y2={pad.top + h} stroke={color} strokeWidth={1} strokeDasharray="3,4" opacity={0.5} />
        <Circle cx={ax} cy={ay} r={8} fill={color} opacity={0.18} />
        <Circle cx={ax} cy={ay} r={5} fill="#060B16" stroke={color} strokeWidth={2.5} />

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

      {/* floating tooltip card — matches the 2C design */}
      <View pointerEvents="none" style={[styles.tooltip, { left: ttLeft, top: ttTop, width: ttW }]}>
        <Text style={styles.ttDate}>{tooltipDate(data[ai].date)}</Text>
        <Text style={styles.ttScore}>
          {data[ai].score} <Text style={{ color: arrowColor, fontSize: 11 }}>{arrow}</Text>
        </Text>
      </View>
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
