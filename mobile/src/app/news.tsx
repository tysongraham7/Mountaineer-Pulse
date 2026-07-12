import * as WebBrowser from 'expo-web-browser';
import { useCallback, useEffect, useState } from 'react';
import {
  ActivityIndicator,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { Segmented } from '@/components/ui';
import { Brand, Font, surfaces } from '@/constants/brand';
import { supabase } from '@/lib/supabase';

const c = surfaces(true);

type NewsItem = {
  id: string;
  sport_id: string | null;
  headline: string;
  source_name: string | null;
  url: string;
  published_at: string | null;
};

const FILTERS = [
  { key: 'all', label: 'All' },
  { key: 'football', label: 'Football' },
  { key: 'mbb', label: 'Basketball' },
  { key: 'baseball', label: 'Baseball' },
];
const SPORT_LABEL: Record<string, string> = { football: 'Football', mbb: 'Basketball', baseball: 'Baseball' };

function relativeTime(iso: string | null): string {
  if (!iso) return '';
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.round(diff / 60000);
  if (mins < 60) return `${Math.max(1, mins)}m`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs}h`;
  return `${Math.round(hrs / 24)}d`;
}

export default function NewsScreen() {
  const insets = useSafeAreaInsets();
  const [items, setItems] = useState<NewsItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [filter, setFilter] = useState('all');

  const load = useCallback(async () => {
    const { data } = await supabase
      .from('news_items')
      .select('*')
      .order('published_at', { ascending: false })
      .limit(80);
    setItems((data ?? []) as NewsItem[]);
    setLoading(false);
    setRefreshing(false);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  if (loading) {
    return (
      <View style={[styles.center, { backgroundColor: c.bg }]}>
        <ActivityIndicator size="large" color={Brand.gold} />
        <Text style={{ color: c.textSecondary, marginTop: 12, fontFamily: Font.bodyMed }}>
          Loading WVU news…
        </Text>
      </View>
    );
  }

  const visible = filter === 'all' ? items : items.filter((n) => n.sport_id === filter);
  const updated = items[0] ? relativeTime(items[0].published_at) : '';

  return (
    <ScrollView
      style={{ backgroundColor: c.bg }}
      contentContainerStyle={[styles.content, { paddingTop: insets.top + 10 }]}
      refreshControl={
        <RefreshControl
          refreshing={refreshing}
          onRefresh={() => {
            setRefreshing(true);
            load();
          }}
          tintColor={Brand.gold}
        />
      }>
      <View style={styles.header}>
        <Text style={styles.title}>News</Text>
        {updated ? <Text style={styles.headerMeta}>Updated {updated} ago</Text> : null}
      </View>

      <Segmented options={FILTERS} value={filter} onChange={setFilter} />

      <View style={{ marginTop: 16, gap: 8 }}>
        {visible.length === 0 && (
          <Text style={styles.empty}>No headlines in this filter yet.</Text>
        )}
        {visible.map((n) => (
          <Pressable
            key={n.id}
            onPress={() => WebBrowser.openBrowserAsync(n.url)}
            style={({ pressed }) => [styles.card, { opacity: pressed ? 0.75 : 1 }]}>
            <View style={styles.metaRow}>
              {n.sport_id && SPORT_LABEL[n.sport_id] && (
                <View style={styles.tag}>
                  <Text style={styles.tagText}>{SPORT_LABEL[n.sport_id]}</Text>
                </View>
              )}
              <Text style={styles.source} numberOfLines={1}>
                {n.source_name ?? 'News'} · {relativeTime(n.published_at)}
              </Text>
            </View>
            <Text style={styles.headline}>{n.headline}</Text>
          </Pressable>
        ))}
      </View>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  center: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  content: { paddingHorizontal: 20, paddingBottom: 40 },
  header: { flexDirection: 'row', alignItems: 'baseline', justifyContent: 'space-between', paddingVertical: 8 },
  title: { fontFamily: Font.display, fontSize: 24, color: c.text, letterSpacing: -0.4 },
  headerMeta: { fontFamily: Font.body, fontSize: 12, color: c.textMuted },
  empty: { textAlign: 'center', marginTop: 24, fontSize: 14, color: c.textSecondary, fontFamily: Font.body },
  card: { backgroundColor: c.card, borderWidth: 1, borderColor: c.border, borderRadius: 16, padding: 14 },
  metaRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  tag: { backgroundColor: Brand.goldTint, borderRadius: 999, paddingHorizontal: 8, paddingVertical: 2 },
  tagText: { color: Brand.gold, fontSize: 10, fontFamily: Font.bodyBold },
  source: { fontSize: 11, color: c.textMuted, flex: 1, fontFamily: Font.body },
  headline: { fontFamily: Font.displaySemi, fontSize: 15, color: c.text, lineHeight: 21, marginTop: 7 },
});
