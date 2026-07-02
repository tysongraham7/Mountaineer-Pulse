import { Dimensions } from 'react-native';
import Svg, {
  Circle,
  Defs,
  Line,
  LinearGradient,
  Polygon,
  Polyline,
  Stop,
  Text as SvgText,
} from 'react-native-svg';

import { Brand } from '@/constants/brand';

export type ChartPoint = { date: string; score: number };

function shortDate(iso: string): string {
  const d = new Date(iso);
  return `${d.getMonth() + 1}/${d.getDate()}`;
}

export function PulseChart({
  data,
  color = Brand.gold,
  textColor,
  gridColor,
  height = 210,
  width,
}: {
  data: ChartPoint[];
  color?: string;
  textColor: string;
  gridColor: string;
  height?: number;
  width?: number;
}) {
  const W = width ?? Dimensions.get('window').width - 64;
  const pad = { top: 16, right: 14, bottom: 26, left: 30 };
  const w = W - pad.left - pad.right;
  const h = height - pad.top - pad.bottom;

  if (data.length < 2) {
    return null;
  }

  const scores = data.map((d) => d.score);
  const lo = Math.max(0, Math.min(...scores) - 6);
  const hi = Math.min(100, Math.max(...scores) + 6);
  const span = Math.max(1, hi - lo);
  const n = data.length;

  const x = (i: number) => pad.left + (i / (n - 1)) * w;
  const y = (s: number) => pad.top + (1 - (s - lo) / span) * h;

  const line = data.map((d, i) => `${x(i)},${y(d.score)}`).join(' ');
  const area = `${pad.left},${pad.top + h} ${line} ${x(n - 1)},${pad.top + h}`;

  const last = data[n - 1];
  const tickIdx = [0, Math.floor((n - 1) / 2), n - 1];

  return (
    <Svg width={W} height={height}>
      <Defs>
        <LinearGradient id="pulseFill" x1="0" y1="0" x2="0" y2="1">
          <Stop offset="0" stopColor={color} stopOpacity={0.28} />
          <Stop offset="1" stopColor={color} stopOpacity={0.02} />
        </LinearGradient>
      </Defs>

      {/* horizontal gridlines + y labels (hi / mid / lo) */}
      {[hi, Math.round((hi + lo) / 2), lo].map((v, i) => (
        <Line
          key={`g${i}`}
          x1={pad.left}
          y1={y(v)}
          x2={pad.left + w}
          y2={y(v)}
          stroke={gridColor}
          strokeWidth={1}
        />
      ))}
      {[hi, lo].map((v, i) => (
        <SvgText key={`y${i}`} x={pad.left - 6} y={y(v) + 3} fontSize={10} fill={textColor} textAnchor="end">
          {v}
        </SvgText>
      ))}

      {/* area + line */}
      <Polygon points={area} fill="url(#pulseFill)" />
      <Polyline points={line} fill="none" stroke={color} strokeWidth={2.5} />

      {/* end dot */}
      <Circle cx={x(n - 1)} cy={y(last.score)} r={4} fill={color} />

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
  );
}
