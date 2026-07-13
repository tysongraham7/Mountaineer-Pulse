// Shared 2C design-system primitives, so every screen composes the same
// section labels, segmented controls, sparklines, chips and logo mark.
import { ReactNode } from 'react';
import { Pressable, StyleSheet, Text, View, ViewStyle } from 'react-native';
import Svg, { Path, Polyline } from 'react-native-svg';

import { Brand, Font, surfaces } from '@/constants/brand';

const c = surfaces(true);

// The ridge-pulse brand mark (swaps for the Flying WV once cleared).
// `boxed` (default) draws the dashed logo tile for headers; `boxed={false}` renders
// just the waveform glyph — used as the Pulse tab icon, tinted by the tab color.
export function RidgeMark({
  size = 34,
  color = Brand.gold,
  boxed = true,
}: {
  size?: number;
  color?: string;
  boxed?: boolean;
}) {
  const wave = (glyphW: number, sw: number) => (
    <Svg width={glyphW} height={glyphW * 0.6} viewBox="0 0 24 14">
      <Path
        d="M1,12 L6,4 L9,9 L12,2 L14,12 L17,7 L23,7"
        fill="none"
        stroke={color}
        strokeWidth={sw}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </Svg>
  );
  if (!boxed) return wave(size, 2.4);
  return (
    <View
      style={{
        width: size,
        height: size,
        borderRadius: Math.round(size * 0.26),
        borderWidth: 1.5,
        borderColor: 'rgba(234,170,0,0.5)',
        borderStyle: 'dashed',
        alignItems: 'center',
        justifyContent: 'center',
      }}>
      {wave(Math.round(size * 0.6), 1.8)}
    </View>
  );
}

export function Wordmark({ size = 17 }: { size?: number }) {
  return (
    <Text style={{ fontFamily: Font.display, fontSize: size, color: c.text, letterSpacing: -0.3 }}>
      MOUNTAINEER <Text style={{ color: Brand.gold }}>PULSE</Text>
    </Text>
  );
}

export function SectionLabel({
  children,
  tone = 'gold',
  style,
}: {
  children: ReactNode;
  tone?: 'gold' | 'muted';
  style?: ViewStyle;
}) {
  return (
    <Text
      style={[
        {
          fontFamily: Font.bodyBold,
          fontSize: 11,
          letterSpacing: 1.5,
          color: tone === 'gold' ? Brand.gold : c.textMuted,
        },
        style as never,
      ]}>
      {typeof children === 'string' ? children.toUpperCase() : children}
    </Text>
  );
}

export function Card({ children, style }: { children: ReactNode; style?: ViewStyle }) {
  return (
    <View
      style={[
        { backgroundColor: c.card, borderWidth: 1, borderColor: c.border, borderRadius: 18 },
        style,
      ]}>
      {children}
    </View>
  );
}

type Opt = { key: string; label: string };

// Segmented control. `variant`: 'pill' = rounded track with a sliding gold pill
// (sport switcher); 'solid' = equal rounded-rect buttons (Team sub-tabs).
export function Segmented({
  options,
  value,
  onChange,
  variant = 'pill',
  size = 'md',
}: {
  options: Opt[];
  value: string;
  onChange: (k: string) => void;
  variant?: 'pill' | 'solid';
  size?: 'sm' | 'md';
}) {
  const padV = size === 'sm' ? 5 : 7;
  if (variant === 'solid') {
    return (
      <View style={{ flexDirection: 'row', gap: 6 }}>
        {options.map((o) => {
          const active = o.key === value;
          return (
            <Pressable
              key={o.key}
              onPress={() => onChange(o.key)}
              style={[
                st.solidBtn,
                { paddingVertical: padV },
                active
                  ? { backgroundColor: Brand.gold }
                  : { backgroundColor: c.card, borderWidth: 1, borderColor: c.border },
              ]}>
              <Text
                style={{
                  fontFamily: active ? Font.bodyBold : Font.bodySemi,
                  fontSize: 12,
                  color: active ? Brand.onGold : c.textSecondary,
                }}>
                {o.label}
              </Text>
            </Pressable>
          );
        })}
      </View>
    );
  }
  return (
    <View style={[st.pillTrack, { padding: size === 'sm' ? 3 : 4 }]}>
      {options.map((o) => {
        const active = o.key === value;
        return (
          <Pressable
            key={o.key}
            onPress={() => onChange(o.key)}
            style={[
              st.pillBtn,
              { paddingVertical: padV },
              active && { backgroundColor: Brand.gold },
            ]}>
            <Text
              style={{
                fontFamily: active ? Font.bodyBold : Font.bodySemi,
                fontSize: size === 'sm' ? 11 : 12,
                color: active ? Brand.onGold : c.textSecondary,
              }}>
              {o.label}
            </Text>
          </Pressable>
        );
      })}
    </View>
  );
}

// Small sparkline. `data` are raw scores; auto-scaled. Colour defaults to gold.
export function Sparkline({
  data,
  color = Brand.gold,
  width = 56,
  height = 30,
}: {
  data: number[];
  color?: string;
  width?: number;
  height?: number;
}) {
  if (!data || data.length < 2) return <View style={{ width, height }} />;
  const min = Math.min(...data);
  const max = Math.max(...data);
  const span = max - min || 1;
  const pad = 3;
  const pts = data
    .map((v, i) => {
      const x = (i / (data.length - 1)) * width;
      const y = pad + (1 - (v - min) / span) * (height - pad * 2);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(' ');
  return (
    <Svg width={width} height={height}>
      <Polyline
        points={pts}
        fill="none"
        stroke={color}
        strokeWidth={2}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </Svg>
  );
}

// Trend glyph + delta, coloured by direction.
export function TrendTag({ trend, delta }: { trend: string; delta?: number }) {
  const up = trend === 'up';
  const down = trend === 'down';
  const color = up ? Brand.green : down ? Brand.red : c.textSecondary;
  const glyph = up ? '▲' : down ? '▼' : '▶';
  return (
    <Text style={{ fontFamily: Font.bodyBold, fontSize: 11, color }}>
      {glyph}
      {delta !== undefined ? ` ${Math.abs(delta)}` : ''}
    </Text>
  );
}

const st = StyleSheet.create({
  pillTrack: {
    flexDirection: 'row',
    gap: 6,
    backgroundColor: c.card,
    borderWidth: 1,
    borderColor: c.border,
    borderRadius: 999,
  },
  pillBtn: { flex: 1, alignItems: 'center', borderRadius: 999 },
  solidBtn: { flex: 1, alignItems: 'center', borderRadius: 10 },
});
