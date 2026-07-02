// Official West Virginia University athletics colors.
export const Brand = {
  blue: '#002855',      // WVU Blue
  blueDeep: '#001A38',
  gold: '#EAAA00',      // WVU Old Gold
  win: '#1a7f37',
  loss: '#b42318',
};

// Theme-aware surface colors used across screens.
export const surfaces = (dark: boolean) => ({
  bg: dark ? '#0b0d10' : '#f3f4f6',
  card: dark ? '#15181c' : '#ffffff',
  text: dark ? '#f5f6f7' : '#0a0a0a',
  textSecondary: dark ? '#9aa0a6' : '#60646c',
  border: dark ? '#23262b' : '#e6e7ea',
});
