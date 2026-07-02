# Expo SDK 54

This project targets **Expo SDK 54** (stable, matches Expo Go on the App Store).
Read the versioned docs at https://docs.expo.dev/versions/v54.0.0/ before writing native code.

Notes:
- expo-router 6: theme exports (`ThemeProvider`, `DarkTheme`, `DefaultTheme`) come from
  `@react-navigation/native`, NOT from `expo-router`.
- Was briefly scaffolded on SDK 57 (a preview); downgraded to 54 so Expo Go works.
