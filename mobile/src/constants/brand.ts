// ============================================================================
// Mountaineer Pulse — Design System "2C: Midnight Editorial on Navy"
// Dark-only. WVU Old Gold as the luxury accent over a near-black navy canvas.
// ============================================================================

export const Brand = {
  // Brand
  blue: '#002855', // WVU Blue
  blueMid: '#0A1B38', // gradient mid-stop
  blueDeep: '#001A38',
  gold: '#EAAA00', // WVU Old Gold — hero accent
  goldBright: '#F3C346',
  onGold: '#141414', // text/icon on a gold fill

  // Semantic (roster in/out, wins/losses, trends)
  green: '#4BC97E',
  red: '#E5636B',
  win: '#4BC97E',
  loss: '#E5636B',

  // Tints (fills behind accented chips/icons)
  goldTint: 'rgba(234,170,0,0.10)',
  goldBorder: 'rgba(234,170,0,0.25)',
  greenTint: 'rgba(75,201,126,0.12)',
  greenBorder: 'rgba(75,201,126,0.30)',
  redTint: 'rgba(229,99,107,0.12)',
  redBorder: 'rgba(229,99,107,0.30)',
} as const;

// Surface + text tokens. `surfaces()` keeps its (dark) signature for drop-in
// compatibility, but the app is dark-only so the argument is ignored.
export const surfaces = (_dark?: boolean) => ({
  bg: '#060B16', // canvas
  card: '#0D1524', // surface-1
  surface2: '#131D30', // surface-2 (pills, progress tracks, avatars)
  surface3: '#111A2C', // round icon buttons
  text: '#EFF2F7', // text-primary
  textSecondary: '#8E9AAC', // text-secondary
  textMuted: '#5E6C80', // text-tertiary / captions
  blueLabel: '#9FB4CE', // labels on blue gradients
  border: 'rgba(159,180,206,0.10)', // hairline
  borderStrong: 'rgba(159,180,206,0.14)',
});

// Font families (loaded in _layout via @expo-google-fonts). Because each weight
// is its own family, pick the family for the weight you want — fontWeight is a
// no-op on custom-loaded fonts.
export const Font = {
  black: 'Archivo_900Black', // pulse numbers, big scores
  display: 'Archivo_800ExtraBold', // titles
  displaySemi: 'Archivo_700Bold', // headlines
  displayMed: 'Archivo_600SemiBold',
  body: 'InstrumentSans_400Regular',
  bodyMed: 'InstrumentSans_500Medium',
  bodySemi: 'InstrumentSans_600SemiBold',
  bodyBold: 'InstrumentSans_700Bold',
} as const;

// Gradients (pass to expo-linear-gradient `colors`).
export const Gradients = {
  hero: ['#002855', '#0A1B38', '#060B16'] as const, // overall-pulse / profile header
  splash: ['#002855', '#0A1A36', '#060B16'] as const,
  icon: ['#002855', '#0A1F42'] as const,
};

// Shared metrics.
export const Radius = { chip: 999, control: 10, cardSm: 14, card: 18, hero: 20, tab: 26 };
export const Elevation = {
  hero: {
    shadowColor: '#000',
    shadowOpacity: 0.45,
    shadowRadius: 24,
    shadowOffset: { width: 0, height: 12 },
    elevation: 12,
  },
  float: {
    shadowColor: '#000',
    shadowOpacity: 0.5,
    shadowRadius: 26,
    shadowOffset: { width: 0, height: 14 },
    elevation: 16,
  },
};
