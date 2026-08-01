# Mountaineer Pulse — App Store / Play Store Listing

Ready-to-paste copy for App Store Connect and Google Play, with character limits noted.
Written for an **unofficial fan app** (no WVU affiliation claimed).

**Search strategy (read first):** Apple's App Store search only indexes three fields —
**App Name, Subtitle, and the Keywords field** (NOT the description). So every high-value
term goes in those three, and no word is repeated across them (Apple combines them and
auto-handles plurals). Below, the **Subtitle carries "WVU," "West Virginia," and "sports"**
so you rank for *WVU*, *West Virginia*, *WVU sports*, and *West Virginia sports*; the **Name
carries "Mountaineer(s)."** Together they cover every term you asked for. You do **not** need
"WVU" in the app name to rank for it — the subtitle is weighted just as highly for search,
and putting a trademark in the app name raises Apple-review and trademark risk (see note).

---

## App name  (App Store: 30 char max)
**Mountaineer Pulse**  *(17 chars)*

> Keep the name clean. "Mountaineers"/the Flying WV are WVU marks; shipping as a clearly
> *unofficial* fan app (disclaimer in the description + privacy policy) is the safe path,
> and Apple sometimes rejects apps that put a third-party trademark like "WVU" in the name.
> You still rank for "WVU"/"West Virginia" via the subtitle below.

## Subtitle  (App Store: 30 char max)  ← the search workhorse
**WVU & West Virginia sports**  *(26 chars)*

Covers, as search tokens: `WVU` · `West Virginia` · `WVU sports` · `West Virginia sports` · `sports`.
Alternatives if you prefer:
- `WVU sports: scores & pulse` (26)
- `West Virginia Mountaineers` (26)

## Promotional text  (App Store: 170 char max — editable anytime, no review)
**Feel every win, loss, and roster move. A daily briefing and a live Pulse score for WVU football, basketball & baseball — plus scores, rosters, and roster movement.**  *(~161)*

---

## Keywords  (App Store: 100 char max, comma-separated, NO spaces after commas)
`college football,basketball,baseball,scores,schedule,roster,recruiting,transfer,gameday,hoops,eers`  *(98)*

> Deliberately excludes words already in the Name/Subtitle (mountaineer, wvu, west
> virginia, sports, pulse) — repeating them wastes characters. Apple tokenizes multi-word
> entries, so "college football" also yields the `college` and `football` tokens, letting
> "WVU football" match by combining with the subtitle.

---

## Description  (App Store: 4000 char max)

Mountaineer Pulse is the daily home for West Virginia University sports — WVU football,
men's basketball, and baseball — in one fast, clean, dark-themed app. Follow the
Mountaineers without scrolling ten sites: open Mountaineer Pulse and see exactly where
every program stands today.

THE PULSE
Every program gets a single 0–100 "Pulse" score that moves with real events — wins and
losses, national ranking, roster additions and departures, and genuine news. Tap any
program to see its Pulse charted day by day, with the exact drivers behind every rise and
fall. When something big happens — a marquee transfer, a key player drafted — you watch it
move.

DAILY BRIEFING
Each morning, a researched briefing reads the day's real West Virginia sports stories and
sums them up in tight, per-sport sections — the draft picks, the commitments, who's staying
and who's leaving — with actual detail, not vague headlines.

SCORES & SCHEDULE
Final scores and upcoming games across all three sports, from a WVU-first point of view.

TEAM
- Projected rosters with incoming transfers and signees
- Depth charts by position
- Roster movement: transfers in and out, signings, and departures — dated and sourced
- Players who are drafted but still deciding, flagged so you know what's in the air
- Season stat leaders

MAKE IT YOURS
Star your favorite sports to float them to the top. No account, no sign-up — just open it
and go.

BUILT FOR FANS
No ads. No login. No personal information — no name, no email, no account, ever. Just
anonymous usage counts and crash reports so we can fix what breaks, and public West
Virginia University sports info, fast.

Mountaineer Pulse is an independent, unofficial fan app. It is not affiliated with, endorsed
by, or sponsored by West Virginia University. All team names, logos, and trademarks are the
property of their respective owners; all data is drawn from publicly available sources.

Let's go, Mountaineers.

---

## App Review Notes  (App Store Connect → version page → App Review Information)

Paste verbatim. Each paragraph preempts a specific rejection: (1) reviewers blocked by a
login they can't get past, (2) guideline 5.2.1 third-party trademarks — the real risk for an
unofficial college-team app — and 4.2 minimum functionality, (3) consistency with the App
Privacy answers.

```
Mountaineer Pulse is an independent, unofficial fan app for West Virginia
University sports. No account or login is required — all features are
available immediately on launch, so no demo credentials are needed.

All content is factual sports information (scores, schedules, rosters, and
publicly reported roster moves) compiled from publicly available sources,
plus an original computed "Pulse" score and a daily briefing that summarizes
public news. The app uses no West Virginia University logos, marks, or
branding, and the app description states that it is not affiliated with,
endorsed by, or sponsored by the university. News items link out to the
original publishers.

Player biographies shown on player profiles are the university athletics
department's published bios. Each is credited on-screen as "Bio courtesy of
WVUsports.com" and links to the original page it was taken from.

The app collects no personal information and requests no permissions other
than optional push notifications.
```

**Sign-In Information:** leave unchecked (no account required).
**IDFA / Advertising Identifier:** No.
**Version Release:** *Manually release this version* — so approval doesn't publish the app
before the launch posts are ready.

## Category
- Primary: **Sports**
- Secondary: **News**

## Age rating
**4+** (no objectionable content; links out to third-party news sites)

## URLs
- **Support URL:** `https://tysongraham7.github.io/Mountaineer-Pulse/`
- **Marketing URL:** `https://tysongraham7.github.io/Mountaineer-Pulse/`  *(optional)*
- **Privacy Policy URL:** `https://tysongraham7.github.io/Mountaineer-Pulse/privacy.html`  *(required)*
- **Support email (App Information):** `mountaineerpulse@gmail.com`

---

## Google Play extras
Google Play **does** index the full description for search, so the West Virginia / WVU /
Mountaineers mentions in the description above do double duty there.
- **App name (30 char max):** `Mountaineer Pulse`
- **Short description (80 char max):** `The daily pulse of WVU football, basketball & baseball — scores, roster & news.` *(78)*
- **Full description:** reuse the App Store description above (Play allows 4000 char).
- Data safety form: **not** "no data collected" (same reason as the App Privacy note below).
  Declare *App activity → App interactions*, *App info & performance → Crash logs*, and the
  free-text of in-app reports. Mark all as **collected, not shared, not linked to a user**,
  and tick *Data is encrypted in transit* and *Users can request deletion* (email support).

---

## App Privacy (App Store Connect questionnaire)

> **Do NOT answer "Data Not Collected."** That was true before the July 2026 analytics,
> in-app reports, and Sentry crash reporting shipped. `privacy.html` already discloses all
> three, and Apple compares your questionnaire against your linked privacy policy — a
> mismatch is a rejection now and a removal risk later. Declare all four rows below.

Everything is **"Not Linked to You"** (no account, no name, no email, no advertising ID —
just a random per-install string) and **Tracking: NO** (nothing is shared with data brokers
or linked across other companies' apps/sites, so no ATT permission prompt is needed).

| Data type | Why we collect it | Purpose to select |
|---|---|---|
| **Diagnostics → Crash Data** | Sentry, `sendDefaultPii: false`, `tracesSampleRate: 0` — crashes only | App Functionality |
| **Usage Data → Product Interaction** | `analytics_events`: app opens, screen views, push opens | Analytics |
| **User Content → Customer Support** | free-text of in-app bug/feedback reports | App Functionality |
| **Identifiers → User ID** | random per-install id used to count unique installs and rate-limit reports | Analytics, App Functionality |

> The two random ids (`mp-anon-id` for analytics, `mp-reporter-id` for reports) are generated
> on-device, are deliberately different from each other, and are not device identifiers.
> Declaring them is the conservative, honest call — under-disclosing is what gets punished.

**Sentry setting to check:** in the Sentry project, turn on *Prevent Storing of IP Addresses*
(Settings → Security & Privacy). The SDK doesn't send PII, but Sentry's ingest can retain the
request IP by default, which would undercut the "no personal information" claim above.
