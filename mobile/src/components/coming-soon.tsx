import { Ionicons } from '@expo/vector-icons';
import { StyleSheet, Text, View, useColorScheme } from 'react-native';

import { Brand, surfaces } from '@/constants/brand';

export function ComingSoon({
  icon,
  title,
  blurb,
}: {
  icon: keyof typeof Ionicons.glyphMap;
  title: string;
  blurb: string;
}) {
  const dark = useColorScheme() === 'dark';
  const c = surfaces(dark);
  return (
    <View style={[styles.container, { backgroundColor: c.bg }]}>
      <View style={[styles.iconWrap, { backgroundColor: Brand.blue }]}>
        <Ionicons name={icon} size={34} color={Brand.gold} />
      </View>
      <Text style={[styles.title, { color: c.text }]}>{title}</Text>
      <Text style={[styles.blurb, { color: c.textSecondary }]}>{blurb}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 32 },
  iconWrap: { width: 72, height: 72, borderRadius: 36, alignItems: 'center', justifyContent: 'center', marginBottom: 18 },
  title: { fontSize: 24, fontWeight: '800', marginBottom: 10 },
  blurb: { fontSize: 15, lineHeight: 22, textAlign: 'center', maxWidth: 320 },
});
