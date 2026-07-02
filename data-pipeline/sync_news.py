"""
Mountaineer Pulse - News Pipeline: Google News RSS -> Supabase
==============================================================
Pulls current WVU sports headlines, classifies each by sport, and upserts into
the news_items table. We store headline + source + link only and link OUT.

Run:  python sync_news.py
"""

import hashlib
import html
import os
import sys
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

# Simple keyword classification -> sport_id (first match wins).
SPORT_KEYWORDS = [
    ("baseball", ("baseball", "college world series", "cws", "diamond")),
    ("mbb", ("basketball", "hoops", "guard", "forward")),
    ("football", ("football", "quarterback", " qb ", "gridiron", "running back")),
]


def die(msg: str) -> None:
    print(f"\n[X] {msg}")
    sys.exit(1)


def classify(headline: str) -> str | None:
    h = f" {headline.lower()} "
    for sport, words in SPORT_KEYWORDS:
        if any(w in h for w in words):
            return sport
    return None


def main() -> None:
    if not SB_URL or not SB_KEY:
        die("Missing SUPABASE_URL or SUPABASE_SECRET_KEY in .env")

    sb = create_client(SB_URL, SB_KEY)

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
            "sport_id": classify(headline),
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
