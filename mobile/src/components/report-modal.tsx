import { Ionicons } from '@expo/vector-icons';
import { useEffect, useState } from 'react';
import {
  ActivityIndicator,
  KeyboardAvoidingView,
  Modal,
  Platform,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { Brand, Font, surfaces } from '@/constants/brand';
import { ReportCategory, ReportContext, submitErrorReport } from '@/lib/reports';

const c = surfaces(true);

const CATEGORIES: { id: ReportCategory; label: string; icon: keyof typeof Ionicons.glyphMap }[] = [
  { id: 'data', label: 'Wrong data', icon: 'stats-chart-outline' },
  { id: 'bug', label: "Something's broken", icon: 'bug-outline' },
  { id: 'idea', label: 'Feature idea', icon: 'bulb-outline' },
  { id: 'other', label: 'Other', icon: 'chatbubble-ellipses-outline' },
];

const PLACEHOLDER: Record<ReportCategory, string> = {
  data: "What's wrong, and what should it say? (player, stat, team…)",
  bug: 'What happened, and what were you doing when it did?',
  idea: "What would you like to see? We're listening.",
  other: 'Tell us what’s on your mind.',
};

export function ReportModal({
  visible,
  onClose,
  context,
  initialCategory = 'data',
}: {
  visible: boolean;
  onClose: () => void;
  context?: ReportContext;
  initialCategory?: ReportCategory;
}) {
  const insets = useSafeAreaInsets();
  const [category, setCategory] = useState<ReportCategory>(initialCategory);
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);

  // Reset to a clean slate every time the sheet opens.
  useEffect(() => {
    if (visible) {
      setCategory(initialCategory);
      setMessage('');
      setBusy(false);
      setSent(false);
    }
  }, [visible, initialCategory]);

  const submit = async () => {
    if (busy || !message.trim()) return;
    setBusy(true);
    const ok = await submitErrorReport(category, message, context);
    setBusy(false);
    if (ok) {
      setSent(true);
    } else {
      // Surface a soft failure without a blocking alert; keep their text.
      setSent(false);
    }
  };

  return (
    <Modal visible={visible} animationType="slide" transparent onRequestClose={onClose}>
      <View style={styles.backdrop}>
        <Pressable style={StyleSheet.absoluteFill} onPress={onClose} />
        <KeyboardAvoidingView
          behavior={Platform.OS === 'ios' ? 'padding' : undefined}
          style={styles.avoider}>
          <View style={[styles.sheet, { paddingBottom: insets.bottom + 16 }]}>
            <View style={styles.grip} />

            {sent ? (
              <View style={styles.done}>
                <View style={styles.check}>
                  <Ionicons name="checkmark" size={34} color={Brand.green} />
                </View>
                <Text style={styles.doneTitle}>Thank you</Text>
                <Text style={styles.doneSub}>
                  Your report went straight to the team. Fixing the little things is how we earn your
                  trust — we read every one.
                </Text>
                <Pressable style={styles.primary} onPress={onClose}>
                  <Text style={styles.primaryText}>Done</Text>
                </Pressable>
              </View>
            ) : (
              <>
                <View style={styles.headerRow}>
                  <Text style={styles.title}>Report an issue</Text>
                  <Pressable hitSlop={12} onPress={onClose}>
                    <Ionicons name="close" size={22} color={c.textMuted} />
                  </Pressable>
                </View>
                <Text style={styles.sub}>
                  See a wrong stat or something off? Tell us — it goes straight to the team.
                </Text>

                <View style={styles.chips}>
                  {CATEGORIES.map((cat) => {
                    const on = cat.id === category;
                    return (
                      <Pressable
                        key={cat.id}
                        onPress={() => setCategory(cat.id)}
                        style={[styles.chip, on && styles.chipOn]}>
                        <Ionicons
                          name={cat.icon}
                          size={14}
                          color={on ? Brand.onGold : c.textSecondary}
                        />
                        <Text style={[styles.chipText, on && styles.chipTextOn]}>{cat.label}</Text>
                      </Pressable>
                    );
                  })}
                </View>

                <TextInput
                  style={styles.input}
                  placeholder={PLACEHOLDER[category]}
                  placeholderTextColor={c.textMuted}
                  value={message}
                  onChangeText={setMessage}
                  multiline
                  autoFocus
                  maxLength={2000}
                  textAlignVertical="top"
                />

                <Pressable
                  style={[styles.primary, (busy || !message.trim()) && { opacity: 0.5 }]}
                  disabled={busy || !message.trim()}
                  onPress={submit}>
                  {busy ? (
                    <ActivityIndicator color={Brand.onGold} />
                  ) : (
                    <Text style={styles.primaryText}>Send report</Text>
                  )}
                </Pressable>
                <Text style={styles.privacy}>
                  Anonymous — we only receive your note and your app version.
                </Text>
              </>
            )}
          </View>
        </KeyboardAvoidingView>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: { flex: 1, backgroundColor: 'rgba(0,0,0,0.55)', justifyContent: 'flex-end' },
  avoider: { width: '100%' },
  sheet: {
    backgroundColor: c.card,
    borderTopLeftRadius: 24,
    borderTopRightRadius: 24,
    borderWidth: 1,
    borderColor: c.borderStrong,
    paddingHorizontal: 22,
    paddingTop: 10,
  },
  grip: {
    alignSelf: 'center',
    width: 40,
    height: 4,
    borderRadius: 2,
    backgroundColor: c.surface2,
    marginBottom: 14,
  },
  headerRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  title: { fontFamily: Font.display, fontSize: 20, color: c.text, letterSpacing: -0.3 },
  sub: { fontFamily: Font.body, fontSize: 13.5, lineHeight: 19, color: c.textSecondary, marginTop: 6 },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginTop: 16 },
  chip: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    paddingVertical: 8,
    paddingHorizontal: 12,
    borderRadius: 999,
    backgroundColor: c.surface2,
    borderWidth: 1,
    borderColor: c.border,
  },
  chipOn: { backgroundColor: Brand.gold, borderColor: Brand.gold },
  chipText: { fontFamily: Font.bodySemi, fontSize: 13, color: c.textSecondary },
  chipTextOn: { color: Brand.onGold },
  input: {
    marginTop: 16,
    minHeight: 120,
    borderRadius: 14,
    backgroundColor: c.bg,
    borderWidth: 1,
    borderColor: c.borderStrong,
    padding: 14,
    fontFamily: Font.body,
    fontSize: 15,
    lineHeight: 21,
    color: c.text,
  },
  primary: {
    marginTop: 16,
    backgroundColor: Brand.gold,
    borderRadius: 14,
    paddingVertical: 15,
    alignItems: 'center',
    justifyContent: 'center',
  },
  primaryText: { fontFamily: Font.display, fontSize: 15, color: Brand.onGold, letterSpacing: 0.2 },
  privacy: {
    fontFamily: Font.body,
    fontSize: 11.5,
    color: c.textMuted,
    textAlign: 'center',
    marginTop: 12,
  },
  done: { alignItems: 'center', paddingVertical: 12 },
  check: {
    width: 72,
    height: 72,
    borderRadius: 36,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: Brand.greenTint,
    borderWidth: 1,
    borderColor: Brand.greenBorder,
    marginBottom: 16,
  },
  doneTitle: { fontFamily: Font.display, fontSize: 22, color: c.text, letterSpacing: -0.3 },
  doneSub: {
    fontFamily: Font.body,
    fontSize: 14,
    lineHeight: 21,
    color: c.textSecondary,
    textAlign: 'center',
    marginTop: 10,
    maxWidth: 320,
  },
});
