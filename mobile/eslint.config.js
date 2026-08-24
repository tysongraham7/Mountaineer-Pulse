// https://docs.expo.dev/guides/using-eslint/
const { defineConfig } = require('eslint/config');
const expoConfig = require("eslint-config-expo/flat");

module.exports = defineConfig([
  expoConfig,
  {
    ignores: ["dist/*"],
  },
  {
    rules: {
      // Off because it's a web rule and this is React Native. It guards against a stray
      // quote breaking HTML markup; nothing here renders HTML, so the only thing it can
      // do is push us to write `team&apos;s` in source that displays as "team's" either
      // way -- worse to read, identical on screen. Left on, it reported six "errors" we
      // would never act on, and a lint run that always fails is a lint run nobody reads.
      'react/no-unescaped-entities': 'off',
    },
  },
]);
