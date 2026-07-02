import { Ionicons } from '@expo/vector-icons';
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
  useColorScheme,
} from 'react-native';

import { Brand, surfaces } from '@/constants/brand';
import { supabase } from '@/lib/supabase';

type NewsItem = {
  id: string;
  sport_id: string | null;
  headline: string;
  source_name: string | null;
  url: string;
  published_at: string | null;
};

const SPORT_LABEL: Record<string, string> = {
  football: 'Football',
  mbb: 'Basketball',
  baseball: 'Baseball',
};

function relativeTime(iso: string | null): string {
  if (!iso) return '';
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.round(diff / 60000);
  if (mins < 60) return `${Math.max(1, mins)}m ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.round(hrs / 24);
  return `${days}d ago`;
}

export default function NewsScreen() {
  const dark = useColorScheme() === 'dark';
  const c = surfaces(dark);

  const [items, setItems] = useState<NewsItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    const { data } = await supabase
      .from('news_items')
      .select('*')
      .order('published_at', { ascending: false })
      .limit(60);
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
        <Text style={{ color: c.textSecondary, marginTop: 12 }}>Loading WVU news…</Text>
      </View>
    );
  }

  return (
    <ScrollView
      style={{ backgroundColor: c.bg }}
      contentContainerStyle={styles.content}
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
      {items.length === 0 && (
        <Text style={[styles.empty, { color: c.textSecondary }]}>
          No headlines yet — run the news pipeline to populate the feed.
        </Text>
      )}

      {items.map((n) => (
        <Pressable
          key={n.id}
          onPress={() => WebBrowser.openBrowserAsync(n.url)}
          style={({ pressed }) => [
            styles.card,
            { backgroundColor: c.card, borderColor: c.border, opacity: pressed ? 0.7 : 1 },
          ]}>
          <View style={styles.metaRow}>
            {n.sport_id && SPORT_LABEL[n.sport_id] && (
              <View style={styles.tag}>
                <Text style={styles.tagText}>{SPORT_LABEL[n.sport_id]}</Text>
              </View>
            )}
            <Text style={[styles.source, { color: c.textSecondary }]} numberOfLines={1}>
              {n.source_name ?? 'News'} · {relativeTime(n.published_at)}
            </Text>
          </View>
          <View style={styles.headlineRow}>
            <Text style={[styles.headline, { color: c.text }]}>{n.headline}</Text>
            <Ionicons name="open-outline" size={16} color={c.textSecondary} style={{ marginTop: 3 }} />
          </View>
        </Pressable>
      ))}

      {items.length > 0 && (
        <Text style={[styles.footer, { color: c.textSecondary }]}>
          Aggregated from across the web · tap to read at the source
        </Text>
      )}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  center: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  content: { padding: 16, paddingBottom: 40 },
  empty: { textAlign: 'center', marginTop: 40, fontSize: 14 },
  card: { borderWidth: 1, borderRadius: 14, padding: 14, marginBottom: 10 },
  metaRow: { flexDirection: 'row', alignItems: 'center', gap: 8, marginBottom: 6 },
  tag: { backgroundColor: Brand.blue, borderRadius: 6, paddingHorizontal: 8, paddingVertical: 2 },
  tagText: { color: Brand.gold, fontSize: 11, fontWeight: '800' },
  source: { fontSize: 12, fontWeight: '600', flex: 1 },
  headlineRow: { flexDirection: 'row', gap: 8, alignItems: 'flex-start' },
  headline: { flex: 1, fontSize: 16, fontWeight: '700', lineHeight: 22 },
  footer: { textAlign: 'center', marginTop: 16, fontSize: 12 },
});
