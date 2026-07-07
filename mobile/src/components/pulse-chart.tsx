import { useEffect, useMemo, useState } from 'react';
import { Dimensions, PanResponder, View } from 'react-native';
import Svg, {
  Circle,
  Defs,
  Line,
  LinearGradient,
  Polygon,
  Polyline,
  Rect,
  Stop,
  Text as SvgText,
} from 'react-native-svg';

import { Brand } from '@/constants/brand';

export type ChartPoint = { date: string; score: number };
// 'up'/'down' = a notable scoring jump (green/red); 'move' = a roster move (gold).
export type ChartMarker = { index: number; kind: 'up' | 'down' | 'move' };

function shortDate(iso: string): string {
  const d = new Date(iso);
  return `${d.getMonth() + 1}/${d.getDate()}`;
}

const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));

export function PulseChart({
  data,
  markers = [],
  color = Brand.gold,
  textColor,
  gridColor,
  height = 210,
  width,
  onActiveChange,
}: {
  data: ChartPoint[];
  markers?: ChartMarker[];
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
        onStartShouldSetPanResponder: () => false,
        // Claim the touch only for a horizontal drag, so vertical page scroll still works.
        onMoveShouldSetPanResponder: (_evt, g) =>
          Math.abs(g.dx) > 6 && Math.abs(g.dx) > Math.abs(g.dy),
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

  // Tooltip box (date + score), clamped inside the chart width.
  const tw = 74;
  const tx = clamp(ax - tw / 2, pad.left, W - tw - 2);

  return (
    <View {...panResponder.panHandlers}>
      <Svg width={W} height={height}>
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

        {/* event markers: green/red for scoring jumps, gold for roster moves */}
        {markers.map((m) => {
          if (m.index < 0 || m.index >= n) return null;
          const mc = m.kind === 'up' ? Brand.win : m.kind === 'down' ? Brand.loss : Brand.gold;
          const base = m.kind === 'move' ? 3.5 : 4.5;
          return (
            <Circle
              key={`m${m.index}`}
              cx={x(m.index)}
              cy={y(data[m.index].score)}
              r={m.index === ai ? base + 1.5 : base}
              fill={mc}
              stroke="#fff"
              strokeWidth={1.5}
            />
          );
        })}

        {/* active crosshair + dot */}
        <Line x1={ax} y1={pad.top} x2={ax} y2={pad.top + h} stroke={color} strokeWidth={1} strokeDasharray="3,3" opacity={0.7} />
        <Circle cx={ax} cy={ay} r={5} fill={color} stroke="#fff" strokeWidth={1.5} />

        {/* tooltip */}
        <Rect x={tx} y={2} width={tw} height={18} rx={4} fill={color} opacity={0.95} />
        <SvgText x={tx + tw / 2} y={14} fontSize={10} fontWeight="bold" fill={Brand.blueDeep} textAnchor="middle">
          {shortDate(data[ai].date)} · {data[ai].score}
        </SvgText>

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
    </View>
  );
}
