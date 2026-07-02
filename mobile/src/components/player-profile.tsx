import { Ionicons } from '@expo/vector-icons';
import { Image, Modal, Pressable, ScrollView, StyleSheet, Text, View, useColorScheme } from 'react-native';

import { Brand, surfaces } from '@/constants/brand';
import { Player } from '@/lib/types';

function fullName(p: Player): string {
  return `${p.first_name ?? ''} ${p.last_name ?? ''}`.trim() || 'Player';
}

function hometown(p: Player): string | null {
  const parts = [p.home_city, p.home_state].filter(Boolean);
  return parts.length ? parts.join(', ') : null;
}

export function PlayerProfile({ player, onClose }: { player: Player | null; onClose: () => void }) {
  const dark = useColorScheme() === 'dark';
  const c = surfaces(dark);

  const stats: { label: string; value: string }[] = [];
  if (player) {
    if (player.position) stats.push({ label: 'Position', value: player.position });
    if (player.jersey != null) stats.push({ label: 'Number', value: `#${player.jersey}` });
    if (player.class_display) stats.push({ label: 'Class', value: player.class_display });
    if (player.height_display) stats.push({ label: 'Height', value: player.height_display });
    if (player.weight) stats.push({ label: 'Weight', value: `${player.weight} lb` });
    const town = hometown(player);
    if (town) stats.push({ label: 'Hometown', value: town });
  }

  return (
    <Modal visible={!!player} animationType="slide" onRequestClose={onClose}>
      <View style={{ flex: 1, backgroundColor: c.bg }}>
        <View style={[styles.header, { backgroundColor: Brand.blue }]}>
          <Pressable onPress={onClose} hitSlop={12}>
            <Ionicons name="close" size={26} color="#fff" />
          </Pressable>
        </View>

        {player && (
          <ScrollView contentContainerStyle={styles.content}>
            <View style={styles.hero}>
              {player.photo_url ? (
                <Image source={{ uri: player.photo_url }} style={styles.photo} />
              ) : (
                <View style={[styles.photo, styles.photoFallback, { backgroundColor: Brand.blue }]}>
                  <Text style={styles.photoInitials}>
                    {(player.first_name?.[0] ?? '') + (player.last_name?.[0] ?? '')}
                  </Text>
                </View>
              )}
              {player.jersey != null && (
                <Text style={[styles.jersey, { color: Brand.gold }]}>#{player.jersey}</Text>
              )}
              <Text style={[styles.name, { color: c.text }]}>{fullName(player)}</Text>
              <Text style={[styles.sub, { color: c.textSecondary }]}>
                {[player.position, player.class_display].filter(Boolean).join(' · ')}
              </Text>
            </View>

            <View style={[styles.statCard, { backgroundColor: c.card, borderColor: c.border }]}>
              {stats.map((s, i) => (
                <View
                  key={s.label}
                  style={[
                    styles.statRow,
                    { borderBottomColor: c.border, borderBottomWidth: i === stats.length - 1 ? 0 : 1 },
                  ]}>
                  <Text style={[styles.statLabel, { color: c.textSecondary }]}>{s.label}</Text>
                  <Text style={[styles.statValue, { color: c.text }]}>{s.value}</Text>
                </View>
              ))}
            </View>

            <Text style={[styles.note, { color: c.textSecondary }]}>
              Season stats coming soon.
            </Text>
          </ScrollView>
        )}
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  header: { paddingTop: 54, paddingBottom: 12, paddingHorizontal: 18 },
  content: { padding: 20, paddingBottom: 40 },
  hero: { alignItems: 'center', marginBottom: 20 },
  photo: { width: 128, height: 128, borderRadius: 64, backgroundColor: '#0002' },
  photoFallback: { alignItems: 'center', justifyContent: 'center' },
  photoInitials: { color: '#fff', fontSize: 40, fontWeight: '900' },
  jersey: { fontSize: 16, fontWeight: '900', marginTop: 10 },
  name: { fontSize: 26, fontWeight: '900', marginTop: 4, textAlign: 'center' },
  sub: { fontSize: 15, fontWeight: '600', marginTop: 4 },
  statCard: { borderWidth: 1, borderRadius: 14, paddingHorizontal: 16 },
  statRow: { flexDirection: 'row', justifyContent: 'space-between', paddingVertical: 14 },
  statLabel: { fontSize: 14, fontWeight: '600' },
  statValue: { fontSize: 15, fontWeight: '800' },
  note: { textAlign: 'center', marginTop: 18, fontSize: 12 },
});
