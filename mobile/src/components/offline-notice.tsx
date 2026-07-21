import { Ionicons } from '@expo/vector-icons';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { Brand, Font, surfaces } from '@/constants/brand';

const c = surfaces(true);

/**
 * Shown when a first load fails with no data to fall back on — almost always no internet. Gives a
 * clear, calm "you're offline" state with a retry, instead of empty shells or a stuck spinner.
 */
export function OfflineNotice({ onRetry }: { onRetry: () => void }) {
  return (
    <View style={styles.wrap}>
      <View style={styles.iconCircle}>
        <Ionicons name="cloud-offline-outline" size={30} color={c.textSecondary} />
      </View>
      <Text style={styles.title}>No connection</Text>
      <Text style={styles.body}>
        We couldn’t load the latest. Check your internet connection and try again.
      </Text>
      <Pressable
        onPress={onRetry}
        style={({ pressed }) => [styles.btn, pressed && { opacity: 0.75 }]}>
        <Ionicons name="refresh" size={16} color={Brand.onGold} />
        <Text style={styles.btnText}>Try again</Text>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { flex: 1, alignItems: 'center', justifyContent: 'center', paddingHorizontal: 40, paddingVertical: 60, gap: 12 },
  iconCircle: {
    width: 72, height: 72, borderRadius: 36, alignItems: 'center', justifyContent: 'center',
    backgroundColor: c.surface2, borderWidth: 1, borderColor: c.border, marginBottom: 4,
  },
  title: { fontFamily: Font.display, fontSize: 20, color: c.text, letterSpacing: -0.3 },
  body: { fontFamily: Font.body, fontSize: 14, lineHeight: 20, color: c.textSecondary, textAlign: 'center', maxWidth: 300 },
  btn: {
    flexDirection: 'row', alignItems: 'center', gap: 7, marginTop: 8,
    backgroundColor: Brand.gold, borderRadius: 14, paddingVertical: 12, paddingHorizontal: 22,
  },
  btnText: { fontFamily: Font.display, fontSize: 15, color: Brand.onGold },
});
