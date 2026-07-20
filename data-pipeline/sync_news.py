"""
Mountaineer Pulse - News Pipeline: Google News RSS -> Supabase
==============================================================
Pulls current WVU sports headlines, classifies each by sport, and upserts into
the news_items table. We store headline + source + link only and link OUT.

Classification is name-first: if a WVU player or coach is named in the headline,
it's tagged for that person's sport (the most specific signal). Otherwise it
falls back to sport keywords.

Run:  python sync_news.py
"""

import hashlib
import html
import os
import re
import sys
import unicodedata
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import requests
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

SB_URL = os.getenv("SUPABASE_URL")
SB_KEY = os.getenv("SUPABASE_SECRET_KEY")

QUERY = '"West Virginia" Mountaineers (football OR basketball OR baseball)'
RSS_URL = (
    "https://news.google.com/rss/search"
    f"?q={requests.utils.quote(QUERY)}&hl=en-US&gl=US&ceid=US:en"
)

# Sport keyword fallback -> sport_id (first match wins). Space-padded position
# abbreviations (" ol ", " wr ", ...) are strong football signals; "point guard"
# is used instead of bare "guard" (which is also a football O-lineman).
SPORT_KEYWORDS = [
    ("baseball", ("baseball", "college world series", "cws", "diamond", " mlb", "pitcher",
                  "shortstop", "outfielder", "home run", " rbi", "bullpen")),
    ("mbb", ("basketball", "hoops", " nba", "march madness", "final four", "point guard")),
    ("football", ("football", "quarterback", " qb ", " rb ", " wr ", " ol ", " dl ", " cb ",
                  " te ", " lb ", "gridiron", "running back", "wide receiver", "offensive line",
                  "defensive line", "linebacker", "cornerback", "tight end", " fpi", " nfl ",
                  "recruiting class")),
]

# Coaches aren't in the players table — tag them explicitly. Add staff here as
# needed (name -> sport); safe because they only tag when the name appears.
COACHES = {
    # Football
    "Rich Rodriguez": "football",
    "Rich Rod": "football",
    "Coach Rod": "football",
    "Zac Alley": "football",  # defensive coordinator
    # Men's Basketball
    "Ross Hodge": "mbb",  # head coach
    # Baseball
    "Steve Sabins": "baseball",  # head coach
}

# Surnames that double as common words / are too ambiguous to match alone; these
# only tag via a full-name match, never last-name-only.
STOP_LASTNAMES = {
    "brown", "green", "white", "young", "rush", "price", "law", "long", "case",
    "day", "may", "west", "black", "best", "love", "hall", "king", "bell",
    "woods", "fields", "banks", "james", "lee", "cook", "ford", "moore",
}


def die(msg: str) -> None:
    print(f"\n[X] {msg}")
    sys.exit(1)


def norm(s: str) -> str:
    """Lowercase, strip accents/punctuation/suffixes -> a space-delimited string."""
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    s = s.lower()
    s = re.sub(r"[.\-']", " ", s)
    s = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", " ", s)
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def build_name_index(sb):
    """Return (full, last): full-name -> sport, and unambiguous last-name -> sport."""
    full: dict[str, str] = {}
    last_multi: dict[str, set[str]] = {}

    def add(name: str, sport: str) -> None:
        n = norm(name)
        if not n or not sport:
            return
        full[n] = sport
        parts = n.split()
        if len(parts) >= 2:
            ln = parts[-1]
            if len(ln) >= 4 and ln not in STOP_LASTNAMES:
                last_multi.setdefault(ln, set()).add(sport)

    for p in sb.table("players").select("first_name,last_name,sport_id").execute().data:
        add(f"{p.get('first_name') or ''} {p.get('last_name') or ''}", p.get("sport_id"))
    for m in sb.table("roster_moves").select("player_name,sport_id").execute().data:
        add(m.get("player_name") or "", m.get("sport_id"))
    # player_stats covers anyone who's played (incl. last-season players who've since
    # left the roster but are still in the news, e.g. MLB-draft picks); depth_chart
    # covers projected additions.
    for r in sb.table("player_stats").select("player_name,sport_id").execute().data:
        add(r.get("player_name") or "", r.get("sport_id"))
    for r in sb.table("depth_chart").select("player_name,sport_id").execute().data:
        add(r.get("player_name") or "", r.get("sport_id"))
    for name, sport in COACHES.items():
        add(name, sport)

    # A last name is only usable if it points to exactly ONE sport.
    last = {ln: next(iter(s)) for ln, s in last_multi.items() if len(s) == 1}
    return full, last


# Strong, unambiguous per-sport markers used to detect a SECOND sport even when a player is
# already named — so a multi-sport roundup (a MAILBAG that names a hoops player but also asks
# about "QB1" and "Bowl hopes") is caught as football+basketball and left unlabeled. Kept tight
# and rarely-metaphorical, unlike the broad fallback list, so it doesn't split routine stories.
STRONG_SPORT = {
    "football": ("quarterback", "qb1", "qb2", "touchdown", "gridiron", "bowl game",
                 "bowl hopes", "bowl eligible", "bowl bid", "fall camp", "spring game"),
    "baseball": ("home run", "no-hitter", "grand slam", "shutout", "bullpen", "rbi", "world series"),
    "mbb": ("point guard", "three-pointer", "double-double", "buzzer-beater", "final four"),
}


def sports_in(headline: str, full: dict, last: dict) -> set[str]:
    """Every distinct sport a headline implicates. Named players/coaches are the specific signal;
    STRONG_SPORT markers add a second sport even alongside a name (catching multi-sport roundups);
    the broad keyword list is a single-sport fallback only when nobody is named and no strong
    marker fires (so a routine 'baseball recruiting class' isn't split by a football keyword)."""
    h = f" {norm(headline)} "
    hl = f" {headline.lower()} "
    found: set[str] = set()
    consumed: set[str] = set()  # tokens already explained by a full-name match
    for name, sport in full.items():
        if f" {name} " in h:
            found.add(sport)
            consumed.update(name.split())
    for ln, sport in last.items():
        # Skip a surname that's really the first name of a full name we already matched
        # (e.g. "Ryan" the WVU football surname vs "Ryan Brown" the baseball transfer) —
        # otherwise the collision fakes a second sport and the story gets left unlabeled.
        if f" {ln} " in h and ln not in consumed:
            found.add(sport)
    for sport, words in STRONG_SPORT.items():
        if any(w in hl for w in words):
            found.add(sport)
    if not found:
        for sport, words in SPORT_KEYWORDS:  # first match wins — a single fallback sport
            if any(w in hl for w in words):
                found.add(sport)
                break
    return found


def classify(headline: str, full: dict, last: dict) -> str | None:
    """One sport, or None. A headline that implicates TWO+ sports (e.g. a football and a
    baseball player in the same story) is left UNLABELED rather than forced into one — it
    still shows under the 'All' news filter, just not mis-filed under a single sport."""
    found = sports_in(headline, full, last)
    return next(iter(found)) if len(found) == 1 else None


# Words too generic to signal "same story" — every WVU headline has them, so they'd make
# unrelated stories look similar. Sport words included so similarity keys on the actual news.
STORY_STOP = {
    "the", "a", "an", "and", "or", "but", "for", "to", "of", "in", "on", "at", "with", "from",
    "as", "is", "are", "be", "by", "vs", "his", "her", "its", "new", "how", "why", "what",
    "who", "will", "has", "have", "after", "over", "into", "out", "up", "off", "wvu", "west",
    "virginia", "mountaineer", "mountaineers", "football", "baseball", "basketball", "hoops",
}


def story_tokens(headline: str) -> set[str]:
    """The distinctive words of a headline — lowercased, punctuation-stripped, generic words
    and 1-2 char tokens dropped. Two articles about the SAME story share most of these."""
    return {w for w in norm(headline).split() if len(w) >= 3 and w not in STORY_STOP}


def near_duplicate(a: set[str], b: set[str], thresh: float = 0.65) -> bool:
    """True when two headlines are the same story: the smaller token set is mostly contained
    in the larger (containment handles a short 'X signs' vs a longer 'X signs deal with Y')."""
    if not a or not b:
        return False
    return len(a & b) / min(len(a), len(b)) >= thresh


def main() -> None:
    if not SB_URL or not SB_KEY:
        die("Missing SUPABASE_URL or SUPABASE_SECRET_KEY in .env")

    sb = create_client(SB_URL, SB_KEY)
    full, last = build_name_index(sb)
    print(f"name index: {len(full)} full names, {len(last)} unambiguous surnames")

    resp = requests.get(RSS_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    resp.raise_for_status()
    root = ET.fromstring(resp.content)
    items = root.findall(".//item")

    rows = []
    seen = set()
    for item in items:
        raw_title = html.unescape(item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        if not raw_title or not link:
            continue

        source_el = item.find("source")
        source = source_el.text.strip() if source_el is not None and source_el.text else None

        # Google News titles are "Headline - Source"; strip the trailing source.
        headline = raw_title
        if source and headline.endswith(f" - {source}"):
            headline = headline[: -(len(source) + 3)].strip()

        pub = item.findtext("pubDate")
        published_at = None
        if pub:
            try:
                published_at = parsedate_to_datetime(pub).isoformat()
            except (TypeError, ValueError):
                published_at = None

        uid = hashlib.md5(f"{source}|{headline}".encode("utf-8")).hexdigest()
        if uid in seen:
            continue
        seen.add(uid)

        rows.append({
            "id": uid,
            "sport_id": classify(headline, full, last),
            "headline": headline,
            "source_name": source,
            "url": link,
            "published_at": published_at,
        })

    if rows:
        sb.table("news_items").upsert(rows).execute()

    # De-dupe near-identical headlines: Google News syndicates the same story from many
    # outlets ("Estridge signs with Astros" x4), and beat sites re-post the same piece, so the
    # feed showed the same news three or four times. Within each sport bucket, walk newest-first
    # and drop any item that's the SAME STORY as one we've already kept (shared distinctive
    # words). Only near-identical headlines are removed, so genuinely different stories — even
    # about the same player days apart — are left alone.
    DEDUP_WINDOW_DAYS = 21
    cutoff = (datetime.now(timezone.utc) - timedelta(days=DEDUP_WINDOW_DAYS)).isoformat()
    recent = (sb.table("news_items").select("id,sport_id,headline,published_at")
              .gte("published_at", cutoff).order("published_at", desc=True).execute().data or [])
    by_bucket: dict[str, list] = {}
    for r in recent:
        by_bucket.setdefault(r.get("sport_id") or "general", []).append(r)  # newest-first
    removed_dupes = 0
    for items in by_bucket.values():
        kept: list[set[str]] = []
        for r in items:
            toks = story_tokens(r.get("headline") or "")
            if any(near_duplicate(toks, k) for k in kept):
                sb.table("news_items").delete().eq("id", r["id"]).execute()
                removed_dupes += 1
            else:
                kept.append(toks)

    by_sport: dict[str, int] = {}
    for r in rows:
        key = r["sport_id"] or "general"
        by_sport[key] = by_sport.get(key, 0) + 1

    print(f"news_items -> upserted {len(rows)} headlines")
    for k, v in sorted(by_sport.items()):
        print(f"   {k:<10} {v}")
    if removed_dupes:
        print(f"   collapsed {removed_dupes} near-duplicate headline(s) to the latest")
    print("\n[OK] News synced to Supabase.")


if __name__ == "__main__":
    main()
