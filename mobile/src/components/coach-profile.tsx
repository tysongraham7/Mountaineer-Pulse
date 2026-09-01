import { Ionicons } from '@expo/vector-icons';
import { LinearGradient } from 'expo-linear-gradient';
import { useEffect, useState } from 'react';
import { Image, Linking, Modal, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';

import { ReportModal } from '@/components/report-modal';
import { SectionLabel, SheetHeader } from '@/components/ui';
import { Brand, Font, Gradients, surfaces } from '@/constants/brand';
import { trackFeature } from '@/lib/analytics';
import { supabase } from '@/lib/supabase';
import { Coach } from '@/lib/types';

const c = surfaces(true);

const SPORT_LABEL: Record<string, string> = {
  football: 'Football',
  mbb: "Men's Basketball",
  baseball: 'Baseball',
};

// Enough prose to see what kind of bio it is before deciding to read it. Coach bios run
// far longer than players' — Rich Rodriguez's is fourteen thousand characters.
const BIO_PREVIEW_LINES = 5;

export function coachName(coach: Coach): string {
  return `${coach.first_name ?? ''} ${coach.last_name ?? ''}`.trim() || 'Coach';
}

/** "2nd season at WVU", counting from the year the current stint began. Returns null when
 *  the bio page never listed a start year, which is common for support staff. */
export function seasonAtWvu(coach: Coach, now = new Date()): string | null {
  const start = Number(coach.first_year);
  if (!Number.isFinite(start) || start < 1900) return null;
  // A football year and a basketball year both belong to the season that started in the
  // previous calendar year until roughly July, so count seasons from the start year, not
  // from today's date.
  const seasonYear = now.getMonth() >= 6 ? now.getFullYear() : now.getFullYear() - 1;
  const n = seasonYear - start + 1;
  if (n < 1) return null;
  const suffix = n % 10 === 1 && n % 100 !== 11 ? 'st'
    : n % 10 === 2 && n % 100 !== 12 ? 'nd'
      : n % 10 === 3 && n % 100 !== 13 ? 'rd' : 'th';
  return `${n}${suffix} season at WVU`;
}

export function CoachProfile({ coach, onClose }: { coach: Coach | null; onClose: () => void }) {
  const [bio, setBio] = useState<{ text: string; url: string | null } | null>(null);
  const [bioOpen, setBioOpen] = useState(false);
  const [reportOpen, setReportOpen] = useState(false);
  const [notesOpen, setNotesOpen] = useState<Record<number, boolean>>({});

  const openId = coach?.id;
  useEffect(() => {
    if (openId) trackFeature('coach_profile_open');
  }, [openId]);

  // Same split as the player profile: the staff list loads without bios, and the prose is
  // fetched here so opening one coach doesn't cost the weight of all forty-five.
  useEffect(() => {
    if (!coach) return;
    setBio(null);
    setBioOpen(false);
    setNotesOpen({});
    supabase
      .from('coaches')
      .select('bio,bio_url')
      .eq('id', coach.id)
      .maybeSingle()
      .then(({ data }) => {
        if (data?.bio) setBio({ text: data.bio, url: data.bio_url ?? null });
      });
  }, [coach]);

  const bioLines = bio ? bio.text.split('\n').filter(Boolean) : [];
  const bioTruncated = bioLines.length > BIO_PREVIEW_LINES;
  const shownBioLines = bioOpen ? bioLines : bioLines.slice(0, BIO_PREVIEW_LINES);

  const career = coach?.career ?? [];
  const history = coach?.history ?? [];
  const tenure = coach ? seasonAtWvu(coach) : null;

  const facts: [string, string][] = [];
  if (coach?.hometown) facts.push(['Hometown', coach.hometown]);
  if (coach?.education) facts.push(['Education', coach.education]);
  if (coach?.playing_career) facts.push(['Played', coach.playing_career]);

  return (
    <Modal visible={!!coach} animationType="slide" onRequestClose={onClose}>
      <View style={{ flex: 1, backgroundColor: c.bg }}>
        {coach && (
          <>
            <SheetHeader title={coachName(coach)} onClose={onClose} />
            <ScrollView contentContainerStyle={{ paddingBottom: 40 }}>
              <LinearGradient
                colors={Gradients.hero}
                start={{ x: 0.2, y: 0 }}
                end={{ x: 0.9, y: 1 }}
                style={styles.hero}>
                <SectionLabel style={{ color: c.blueLabel } as never}>
                  {SPORT_LABEL[coach.sport_id] ?? 'Coaching Staff'}
                </SectionLabel>

                <View style={styles.heroBody}>
                  {coach.photo_url ? (
                    <Image source={{ uri: coach.photo_url }} style={styles.photo} />
                  ) : (
                    <View style={[styles.photo, styles.photoFallback]}>
                      <Text style={styles.photoInitials}>
                        {(coach.first_name?.[0] ?? '') + (coach.last_name?.[0] ?? '')}
                      </Text>
                    </View>
                  )}
                  <View style={{ flex: 1 }}>
                    <Text style={styles.name}>{coachName(coach)}</Text>
                    {coach.title ? <Text style={styles.heroTitle}>{coach.title}</Text> : null}
                    {tenure ? <Text style={styles.heroSub}>{tenure}</Text> : null}
                  </View>
                </View>

                {/* The single number most people came for, when the page states one. */}
                {coach.career_record ? (
                  <View style={styles.recordBox}>
                    <Text style={styles.recordLabel}>CAREER RECORD AS A HEAD COACH</Text>
                    <Text style={styles.recordValue}>{coach.career_record}</Text>
                  </View>
                ) : null}
              </LinearGradient>

              <View style={{ paddingHorizontal: 20 }}>
                {/* Where he's been, and how it went. Notes are long enough to bury the
                    numbers, so each row keeps them behind a tap. */}
                {career.length > 0 && (
                  <>
                    <SectionLabel tone="muted" style={styles.head as never}>Record by School</SectionLabel>
                    <View style={styles.table}>
                      <View style={[styles.tableRow, { paddingVertical: 8 }]}>
                        <Text style={[styles.headText, { flex: 2 }]}>SCHOOL</Text>
                        <Text style={[styles.headText, styles.numCell]}>OVERALL</Text>
                        <Text style={[styles.headText, styles.numCell]}>CONF</Text>
                      </View>
                      {career.map((r, i) => (
                        <View key={i} style={[styles.rowWrap, i === career.length - 1 && styles.lastRow]}>
                          <Pressable
                            style={styles.tableRow}
                            disabled={!r.notes}
                            onPress={() => setNotesOpen((o) => ({ ...o, [i]: !o[i] }))}>
                            <View style={{ flex: 2, flexDirection: 'row', alignItems: 'center', gap: 4 }}>
                              <Text style={styles.schoolCell} numberOfLines={1}>{r.school ?? '—'}</Text>
                              {r.notes ? (
                                <Ionicons
                                  name={notesOpen[i] ? 'chevron-up' : 'chevron-down'}
                                  size={11}
                                  color={c.textMuted}
                                />
                              ) : null}
                            </View>
                            <Text style={[styles.numText, styles.numCell]}>{r.record ?? '—'}</Text>
                            <Text style={[styles.numText, styles.numCell, { color: c.textSecondary }]}>
                              {r.conf ?? '—'}
                            </Text>
                          </Pressable>
                          {r.notes && notesOpen[i] ? (
                            <Text style={styles.noteBody}>{r.notes}</Text>
                          ) : null}
                        </View>
                      ))}
                    </View>
                  </>
                )}

                {/* The full résumé. Reversed so the current job is first — the page prints
                    it oldest-first, which buries what he does now at the bottom. */}
                {history.length > 0 && (
                  <>
                    <SectionLabel tone="muted" style={styles.head as never}>Coaching History</SectionLabel>
                    <View style={styles.card}>
                      {[...history].reverse().map((s, i, arr) => (
                        <View key={i} style={[styles.stopRow, i === arr.length - 1 && styles.lastRow]}>
                          <Text style={styles.stopYears}>{s.years ?? ''}</Text>
                          <View style={{ flex: 1 }}>
                            <Text style={styles.stopSchool}>{s.school ?? ''}</Text>
                            {s.role ? <Text style={styles.stopRole}>{s.role}</Text> : null}
                          </View>
                        </View>
                      ))}
                    </View>
                  </>
                )}

                {facts.length > 0 && (
                  <>
                    <SectionLabel tone="muted" style={styles.head as never}>Background</SectionLabel>
                    <View style={styles.card}>
                      {facts.map(([label, value], i) => (
                        <View key={label} style={[styles.factRow, i === facts.length - 1 && styles.lastRow]}>
                          <Text style={styles.factLabel}>{label}</Text>
                          <Text style={styles.factValue}>{value}</Text>
                        </View>
                      ))}
                    </View>
                  </>
                )}

                {bioLines.length > 0 && (
                  <>
                    <SectionLabel tone="muted" style={styles.head as never}>Bio</SectionLabel>
                    <View style={[styles.card, { paddingVertical: 14 }]}>
                      {shownBioLines.map((line, i) => (
                        <Text key={i} style={[styles.bioPara, i > 0 && { marginTop: 10 }]}>{line}</Text>
                      ))}
                      {bioTruncated && (
                        <Pressable onPress={() => setBioOpen((v) => !v)} hitSlop={8} style={styles.bioToggle}>
                          <Text style={styles.bioToggleText}>
                            {bioOpen ? 'Show less' : `Read the full bio (${bioLines.length} paragraphs)`}
                          </Text>
                          <Ionicons
                            name={bioOpen ? 'chevron-up' : 'chevron-down'}
                            size={13}
                            color={Brand.gold}
                          />
                        </Pressable>
                      )}
                    </View>
                    <Pressable
                      onPress={() => bio?.url && Linking.openURL(bio.url)}
                      disabled={!bio?.url}
                      hitSlop={8}>
                      <Text style={[styles.note, bio?.url && styles.creditLink]}>
                        Bio courtesy of WVUsports.com{bio?.url ? ' ↗' : ''}
                      </Text>
                    </Pressable>
                  </>
                )}

                <Pressable style={styles.reportBtn} onPress={() => setReportOpen(true)} hitSlop={8}>
                  <Ionicons name="flag-outline" size={13} color={c.textMuted} />
                  <Text style={styles.reportText}>Report incorrect info</Text>
                </Pressable>
              </View>
            </ScrollView>
          </>
        )}
        <ReportModal
          visible={reportOpen}
          onClose={() => setReportOpen(false)}
          context={{
            screen: 'coach',
            sport: coach?.sport_id,
            player: coach ? coachName(coach) : undefined,
          }}
        />
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  hero: { paddingHorizontal: 20, paddingTop: 16, paddingBottom: 20 },
  heroBody: { flexDirection: 'row', alignItems: 'center', gap: 16, marginTop: 14 },
  photo: { width: 76, height: 76, borderRadius: 38, borderWidth: 2, borderColor: Brand.gold, backgroundColor: c.card },
  photoFallback: { alignItems: 'center', justifyContent: 'center' },
  photoInitials: { color: Brand.gold, fontSize: 24, fontFamily: Font.black },
  name: { fontFamily: Font.black, fontSize: 24, color: c.text, letterSpacing: -0.4 },
  heroTitle: { fontSize: 13.5, color: Brand.gold, marginTop: 4, fontFamily: Font.bodySemi, lineHeight: 18 },
  heroSub: { fontSize: 12.5, color: c.blueLabel, marginTop: 3, fontFamily: Font.body },
  recordBox: {
    marginTop: 16,
    paddingVertical: 10,
    borderRadius: 12,
    alignItems: 'center',
    backgroundColor: 'rgba(0,0,0,0.22)',
  },
  recordLabel: { fontSize: 9.5, color: c.blueLabel, fontFamily: Font.bodyBold, letterSpacing: 0.8 },
  recordValue: { fontSize: 20, color: Brand.gold, fontFamily: Font.black, marginTop: 2, fontVariant: ['tabular-nums'] },

  head: { marginTop: 20, marginBottom: 8 },
  card: { backgroundColor: c.card, borderWidth: 1, borderColor: c.border, borderRadius: 16, paddingHorizontal: 16 },
  table: { backgroundColor: c.card, borderWidth: 1, borderColor: c.border, borderRadius: 16, paddingHorizontal: 16, overflow: 'hidden' },
  rowWrap: { borderBottomWidth: 1, borderBottomColor: c.border },
  lastRow: { borderBottomWidth: 0 },
  tableRow: { flexDirection: 'row', alignItems: 'center', paddingVertical: 11 },
  headText: { fontSize: 9.5, color: Brand.gold, fontFamily: Font.bodyBold, letterSpacing: 0.7 },
  numCell: { flex: 1, textAlign: 'right' },
  schoolCell: { fontSize: 13, color: c.text, fontFamily: Font.bodyMed, flexShrink: 1 },
  numText: { fontSize: 13, color: c.text, fontFamily: Font.bodySemi, fontVariant: ['tabular-nums'] },
  noteBody: { fontSize: 12.5, color: c.textSecondary, lineHeight: 19, fontFamily: Font.body, paddingBottom: 12, paddingRight: 4 },

  stopRow: { flexDirection: 'row', gap: 12, paddingVertical: 10, borderBottomWidth: 1, borderBottomColor: c.border },
  stopYears: { width: 84, fontSize: 12.5, color: Brand.gold, fontFamily: Font.bodyBold, fontVariant: ['tabular-nums'] },
  stopSchool: { fontSize: 13.5, color: c.text, fontFamily: Font.bodySemi },
  stopRole: { fontSize: 12.5, color: c.textSecondary, marginTop: 1, fontFamily: Font.body, lineHeight: 17 },

  factRow: { paddingVertical: 11, borderBottomWidth: 1, borderBottomColor: c.border },
  factLabel: { fontSize: 10, color: Brand.gold, fontFamily: Font.bodyBold, letterSpacing: 0.6, marginBottom: 3 },
  factValue: { fontSize: 13.5, color: c.text, fontFamily: Font.body, lineHeight: 20 },

  bioPara: { fontSize: 14, color: c.text, lineHeight: 21, fontFamily: Font.body },
  bioToggle: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 5, marginTop: 12, paddingTop: 10, borderTopWidth: 1, borderTopColor: c.border },
  bioToggleText: { fontSize: 12.5, color: Brand.gold, fontFamily: Font.bodySemi },
  note: { textAlign: 'center', marginTop: 16, fontSize: 12, color: c.textMuted, lineHeight: 18, fontFamily: Font.body },
  creditLink: { color: c.blueLabel, textDecorationLine: 'underline' },
  reportBtn: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 6, marginTop: 24, paddingVertical: 8 },
  reportText: { fontSize: 12.5, color: c.textMuted, fontFamily: Font.bodyMed },
});
