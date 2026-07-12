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

# Sport keyword fallback -> sport_id (first match wins).
SPORT_KEYWORDS = [
    ("baseball", ("baseball", "college world series", "cws", "diamond")),
    ("mbb", ("basketball", "hoops", "guard", "forward")),
    ("football", ("football", "quarterback", " qb ", "gridiron", "running back")),
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
    for name, sport in COACHES.items():
        add(name, sport)

    # A last name is only usable if it points to exactly ONE sport.
    last = {ln: next(iter(s)) for ln, s in last_multi.items() if len(s) == 1}
    return full, last


def classify(headline: str, full: dict, last: dict) -> str | None:
    h = f" {norm(headline)} "
    # Name-first: a named player/coach is the most specific signal.
    for name, sport in full.items():
        if f" {name} " in h:
            return sport
    for ln, sport in last.items():
        if f" {ln} " in h:
            return sport
    # Fallback: sport keywords.
    hl = f" {headline.lower()} "
    for sport, words in SPORT_KEYWORDS:
        if any(w in hl for w in words):
            return sport
    return None


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

    by_sport: dict[str, int] = {}
    for r in rows:
        key = r["sport_id"] or "general"
        by_sport[key] = by_sport.get(key, 0) + 1

    print(f"news_items -> upserted {len(rows)} headlines")
    for k, v in sorted(by_sport.items()):
        print(f"   {k:<10} {v}")
    print("\n[OK] News synced to Supabase.")


if __name__ == "__main__":
    main()
