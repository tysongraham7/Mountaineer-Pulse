import { useLocalSearchParams } from 'expo-router';
import * as WebBrowser from 'expo-web-browser';
import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { OfflineNotice } from '@/components/offline-notice';
import { NewsCardSkeleton, SkeletonList } from '@/components/skeleton';
import { Segmented } from '@/components/ui';
import { Brand, Font, surfaces } from '@/constants/brand';
import { supabase } from '@/lib/supabase';
import { useForegroundRefresh } from '@/lib/use-foreground-refresh';

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
  const [loadError, setLoadError] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [filter, setFilter] = useState('all');

  // Set when a breaking-news push brought us here (see lib/use-push-routing.ts). The alerted
  // story gets pinned to the top and marked, so the tap lands on the thing it promised rather
  // than somewhere in a list of eighty headlines.
  const { highlight } = useLocalSearchParams<{ highlight?: string }>();

  const load = useCallback(async () => {
    const { data, error } = await supabase
      .from('news_items')
      .select('*')
      .order('published_at', { ascending: false })
      .limit(80);
    if (error) {
      setLoadError(true);
    } else {
      setItems((data ?? []) as NewsItem[]);
      setLoadError(false);
    }
    setLoading(false);
    setRefreshing(false);
  }, []);

  useEffect(() => {
    load();
  }, [load]);
  useForegroundRefresh(load);

  const filtered = filter === 'all' ? items : items.filter((n) => n.sport_id === filter);

  // Pin the alerted story to the top of whatever filter is showing. Sorting rather than
  // scrolling: the story is minutes old and already near the top, and a scroll-to-index would
  // fight the pull-to-refresh and land on nothing if the filter excludes it.
  const visible = useMemo(() => {
    if (!highlight) return filtered;
    const hit = filtered.find((n) => n.id === highlight);
    return hit ? [hit, ...filtered.filter((n) => n.id !== highlight)] : filtered;
  }, [filtered, highlight]);

  const alerted = highlight ? items.find((n) => n.id === highlight) : undefined;
  const updated = items[0] ? relativeTime(items[0].published_at) : '';

  return (
    <View style={{ flex: 1, backgroundColor: c.bg, paddingTop: insets.top + 10 }}>
      {/* Header + sport filter — pinned above the scroll (stays put like the Team tab) */}
      <View style={styles.header}>
        <Text style={styles.title}>News</Text>
        {updated ? <Text style={styles.headerMeta}>Updated {updated} ago</Text> : null}
      </View>
      <View style={styles.filterBar}>
        <Segmented options={FILTERS} value={filter} onChange={setFilter} />
      </View>

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
      <View style={{ marginTop: 16, gap: 8 }}>
        {loading && (
          <SkeletonList count={6}>
            <NewsCardSkeleton />
          </SkeletonList>
        )}
        {!loading && loadError && items.length === 0 && (
          <OfflineNotice onRetry={() => { setLoading(true); load(); }} />
        )}
        {!loading && !loadError && visible.length === 0 && (
          <Text style={styles.empty}>No headlines in this filter yet.</Text>
        )}
        {!loading && visible.map((n) => {
          const isAlerted = !!highlight && n.id === highlight;
          return (
            <Pressable
              key={n.id}
              onPress={() => WebBrowser.openBrowserAsync(n.url)}
              style={({ pressed }) => [
                styles.card,
                isAlerted && styles.cardAlerted,
                { opacity: pressed ? 0.75 : 1 },
              ]}>
              <View style={styles.metaRow}>
                {isAlerted && (
                  <View style={styles.breakingTag}>
                    <Text style={styles.breakingText}>ALERTED</Text>
                  </View>
                )}
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
              {/* The headline alone doesn't say the article lives elsewhere. On a story someone
                  was just interrupted for, spell out that the tap leaves the app. */}
              {isAlerted && (
                <Text style={styles.readAt}>Tap to read at {n.source_name ?? 'the source'} →</Text>
              )}
            </Pressable>
          );
        })}
        {/* The alerted story exists but the active filter hides it — say so instead of
            showing a list that silently doesn't contain what the push was about. */}
        {!loading && !!alerted && !visible.some((n) => n.id === highlight) && (
          <Pressable onPress={() => setFilter('all')} style={styles.missingBanner}>
            <Text style={styles.missingText}>
              The story you were alerted about is filed under{' '}
              {SPORT_LABEL[alerted.sport_id ?? ''] ?? 'another sport'}. Tap to show all news.
            </Text>
          </Pressable>
        )}
      </View>
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  center: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  content: { paddingHorizontal: 20, paddingBottom: 40 },
  header: { flexDirection: 'row', alignItems: 'baseline', justifyContent: 'space-between', paddingHorizontal: 20, paddingVertical: 8 },
  filterBar: { paddingHorizontal: 20, marginBottom: 4 },
  title: { fontFamily: Font.display, fontSize: 24, color: c.text, letterSpacing: -0.4 },
  headerMeta: { fontFamily: Font.body, fontSize: 12, color: c.textMuted },
  empty: { textAlign: 'center', marginTop: 24, fontSize: 14, color: c.textSecondary, fontFamily: Font.body },
  card: { backgroundColor: c.card, borderWidth: 1, borderColor: c.border, borderRadius: 16, padding: 14 },
  cardAlerted: { borderColor: Brand.gold, borderWidth: 1.5, backgroundColor: Brand.goldTint },
  breakingTag: { backgroundColor: Brand.gold, borderRadius: 999, paddingHorizontal: 8, paddingVertical: 2 },
  breakingText: { color: Brand.onGold, fontSize: 10, fontFamily: Font.bodyBold, letterSpacing: 0.6 },
  readAt: { marginTop: 8, fontSize: 12, color: Brand.gold, fontFamily: Font.bodySemi },
  missingBanner: { backgroundColor: Brand.goldTint, borderWidth: 1, borderColor: Brand.gold, borderRadius: 14, padding: 12 },
  missingText: { fontSize: 13, color: c.text, fontFamily: Font.body, lineHeight: 18 },
  metaRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  tag: { backgroundColor: Brand.goldTint, borderRadius: 999, paddingHorizontal: 8, paddingVertical: 2 },
  tagText: { color: Brand.gold, fontSize: 10, fontFamily: Font.bodyBold },
  source: { fontSize: 11, color: c.textMuted, flex: 1, fontFamily: Font.body },
  headline: { fontFamily: Font.displaySemi, fontSize: 15, color: c.text, lineHeight: 21, marginTop: 7 },
});
